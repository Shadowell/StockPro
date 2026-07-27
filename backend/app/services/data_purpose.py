"""Derived purpose labels for records created before purpose was persisted."""

from __future__ import annotations

from typing import Any


_ACCEPTANCE_MARKERS = (
    "acceptance",
    "fixture",
    "smoke",
    "sprint",
    "qa",
    "验收",
    "演练",
    "测试",
)
_SEED_MARKERS = ("seed", "demo", "sample", "示例", "样例")


def infer_data_purpose(*values: Any) -> str:
    """Classify conservatively; ordinary records remain user-owned."""
    text = " ".join(str(value or "") for value in values).lower()
    if any(marker in text for marker in _ACCEPTANCE_MARKERS):
        return "acceptance"
    if any(marker in text for marker in _SEED_MARKERS):
        return "seed"
    return "user"
