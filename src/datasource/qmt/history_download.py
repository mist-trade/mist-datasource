"""QMT history download job registry (submit / serial execution / status).

设计：下载与读取解耦（add-qmt-history-download design D1/D2）——backend collector
统计缺失后提交 job，本模块经命令网关让桥**串行**执行原生
`download_history_data`（每任务一条命令），逐任务状态可查询；
完成后由 backend 轮询发现并继续采集（datasource 不反向回调）。

执行期每条命令延长 busy_until（owner 租约放行——同步下载阻塞桥主循环，
与终端死亡在心跳上不可区分，见 unify-terminal-admin-surface-guards D4）。
"""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.datasource.qmt.realtime.gateway import QmtCommandGateway

BASE_PERIODS = ("1m", "5m", "1d")
MAX_STOCKS_PER_JOB = 64
_JOB_TTL_SECONDS = 3600.0


@dataclass
class DownloadTask:
    symbol: str
    base_period: str
    state: str = "pending"  # pending | running | done | failed
    error: str | None = None


@dataclass
class DownloadJob:
    job_id: str
    tasks: list[DownloadTask] = field(default_factory=list[DownloadTask])
    created_at: float = 0.0
    completed_at: float | None = None

    def aggregate(self) -> str:
        states = [t.state for t in self.tasks]
        if any(s in ("running", "pending") for s in states):
            return "in_progress"
        if any(s == "failed" for s in states):
            return "any_failed"
        return "all_done"


class QmtHistoryDownloadRegistry:
    """In-memory download job registry. Jobs execute serially via the command
    gateway; completed jobs are retained for status queries until TTL expiry."""

    def __init__(
        self,
        *,
        command_gateway: QmtCommandGateway,
        clock: Callable[[], float],
        ttl_seconds: float = _JOB_TTL_SECONDS,
    ) -> None:
        self._gateway = command_gateway
        self._clock = clock
        self._jobs: dict[str, DownloadJob] = {}
        self._ttl_seconds = ttl_seconds

    def set_command_gateway(self, gateway: QmtCommandGateway) -> None:
        """Rebind the command gateway (test fixtures swap gateways per test)."""
        self._gateway = gateway

    def submit_download_job(
        self,
        stock_list: list[str],
        base_periods: list[str],
        start_time: str,
        end_time: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        job_id = "dl-" + uuid.uuid4().hex[:12]
        now = self._clock()
        tasks: list[DownloadTask] = [
            DownloadTask(symbol=symbol.strip().upper(), base_period=period)
            for symbol in stock_list
            for period in base_periods
        ]
        job = DownloadJob(job_id=job_id, tasks=tasks, created_at=now)
        self._jobs[job_id] = job
        self._cleanup(now)
        asyncio.get_running_loop().create_task(
            self._run_job(job, start_time, end_time, timeout_seconds)
        )
        return {
            "jobId": job_id,
            "tasks": [
                {"symbol": t.symbol, "basePeriod": t.base_period, "state": t.state}
                for t in tasks
            ],
        }

    def job_status(self, job_id: str) -> dict[str, Any] | None:
        self._cleanup(self._clock())
        job = self._jobs.get(job_id)
        if job is None:
            return None
        return {
            "jobId": job.job_id,
            "aggregate": job.aggregate(),
            "tasks": [
                {
                    "symbol": t.symbol,
                    "basePeriod": t.base_period,
                    "state": t.state,
                    "error": t.error,
                }
                for t in job.tasks
            ],
        }

    async def _run_job(
        self, job: DownloadJob, start_time: str, end_time: str, timeout_seconds: float
    ) -> None:
        for task in job.tasks:
            task.state = "running"
            self._gateway.extend_busy_until(timeout_seconds + 60)
            try:
                await self._download_one(task, start_time, end_time, timeout_seconds)
                task.state = "done"
            except Exception as exc:  # noqa: BLE001 — 逐任务失败不中断同 job 其余任务
                task.state = "failed"
                task.error = str(exc)[:300]
        job.completed_at = self._clock()

    async def _download_one(
        self,
        task: DownloadTask,
        start_time: str,
        end_time: str,
        timeout_seconds: float,
    ) -> None:
        command = self._gateway.enqueue(
            "download_history_data",
            {
                "stockcode": task.symbol,
                "periods": [task.base_period],
                "startTime": start_time,
                "endTime": end_time,
            },
            timeout_seconds=timeout_seconds,
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while loop.time() < deadline:
            self._gateway.expire_timed_out()
            result = self._gateway.take_result(command.command_id)
            if result is None:
                await asyncio.sleep(0.05)
                continue
            if not result.ok:
                raise RuntimeError(
                    (result.error or {}).get("message", "download command failed")
                )
            return
        raise TimeoutError("download command result timed out")

    def _cleanup(self, now: float) -> None:
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.completed_at is not None
            and now - job.completed_at > self._ttl_seconds
        ]
        for job_id in expired:
            del self._jobs[job_id]
