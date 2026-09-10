"""TDX history download job registry (submit / background refresh / status).

与 QMT 侧（qmt/history_download.py）同构：backend 统计缺失后提交 job，本模块
后台执行 refresh_kline（每 base period 一次、覆盖整个 stock_list——原生 API
按 stock_list+period 粒度，无日期范围参数，下载范围由终端托管），逐任务状态
可查询；完成后由 backend 轮询发现并继续采集。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.datasource.tdx.http_client import TdxHttpClient

BASE_PERIODS = ("1m", "5m", "1d")
_JOB_TTL_SECONDS = 3600.0


@dataclass
class DownloadTask:
    base_period: str
    stock_list: list[str]
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


class TdxHistoryDownloadRegistry:
    """In-memory TDX download job registry. refresh_kline runs in a background
    task (terminal blocks until each refresh completes — production-measured
    ~100ms incremental); jobs are retained for status queries until TTL."""

    def __init__(
        self,
        *,
        client: TdxHttpClient | None,
        clock: Callable[[], float],
        ttl_seconds: float = _JOB_TTL_SECONDS,
    ) -> None:
        self._client = client
        self._clock = clock
        self._jobs: dict[str, DownloadJob] = {}
        self._ttl_seconds = ttl_seconds

    def set_client(self, client: TdxHttpClient | None) -> None:
        """Rebind the terminal HTTP client (test fixtures swap per test)."""
        self._client = client

    def submit_download_job(
        self,
        stock_list: list[str],
        base_periods: list[str],
    ) -> dict[str, Any]:
        job_id = "tdx-dl-" + uuid.uuid4().hex[:12]
        now = self._clock()
        tasks = [
            DownloadTask(base_period=period, stock_list=list(stock_list))
            for period in base_periods
        ]
        job = DownloadJob(job_id=job_id, tasks=tasks, created_at=now)
        self._jobs[job_id] = job
        self._cleanup(now)
        asyncio.get_running_loop().create_task(self._run_job(job))
        return {
            "jobId": job_id,
            "tasks": [
                {"basePeriod": t.base_period, "stockCount": len(t.stock_list), "state": t.state}
                for t in tasks
            ],
        }

    def job_status(self, job_id: str) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        return {
            "jobId": job.job_id,
            "aggregate": job.aggregate(),
            "tasks": [
                {
                    "basePeriod": t.base_period,
                    "stockList": t.stock_list,
                    "state": t.state,
                    "error": t.error,
                }
                for t in job.tasks
            ],
        }

    async def _run_job(self, job: DownloadJob) -> None:
        if self._client is None:
            for task in job.tasks:
                task.state = "failed"
                task.error = "TDX terminal HTTP client is not initialized"
            job.completed_at = self._clock()
            return
        for task in job.tasks:
            task.state = "running"
            try:
                await self._client.call(
                    "refresh_kline",
                    {"stock_list": task.stock_list, "period": task.base_period},
                )
                task.state = "done"
            except Exception as exc:  # noqa: BLE001 — 逐任务失败不中断同 job 其余任务
                task.state = "failed"
                task.error = str(exc)[:300]
        job.completed_at = self._clock()

    def _cleanup(self, now: float) -> None:
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.completed_at is not None
            and now - job.completed_at > self._ttl_seconds
        ]
        for job_id in expired:
            del self._jobs[job_id]
