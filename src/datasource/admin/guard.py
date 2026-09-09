"""Shared admin-surface method guard (classification-driven, fail-closed).

治理源：每源一份 checked-in 分类映射（method → family），结构同构、更新流程
一致（先改治理文档 → 再改映射）。三段判定（design D2）：

1. 未分类（映射中不存在）        → deny(unclassified)   # 强制先治理后暴露
2. family ∈ 拒绝族              → deny(family_forbidden)  # 与任何开关无关
3. 其余                          → allow
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AdminGuardResult:
    allowed: bool
    family: str | None
    reason: str | None  # "unclassified" | "family_forbidden" | None


class AdminGuard:
    """Per-source admin method guard. Keys are normalized at construction so
    ``evaluate`` is a pure lookup (strip + lower)."""

    def __init__(
        self,
        source: str,
        classification: dict[str, str],
        denied_families: frozenset[str],
    ) -> None:
        self._source = source
        self._classification = {
            name.strip().lower(): family
            for name, family in classification.items()
        }
        self._denied_families = frozenset(denied_families)

    def evaluate(self, method: str) -> AdminGuardResult:
        normalized = (method or "").strip().lower()
        family = self._classification.get(normalized)
        if family is None:
            return AdminGuardResult(allowed=False, family=None, reason="unclassified")
        if family in self._denied_families:
            return AdminGuardResult(
                allowed=False, family=family, reason="family_forbidden"
            )
        return AdminGuardResult(allowed=True, family=family, reason=None)
