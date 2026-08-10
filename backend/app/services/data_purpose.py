"""Derived purpose labels for records created before purpose was persisted."""

from __future__ import annotations

import re
from typing import Any


_ACCEPTANCE_PATTERNS = (
    r"(?<![a-z])acceptance(?![a-z])",
    r"(?<![a-z])fixture(?![a-z])",
    r"(?<![a-z])smoke(?![a-z])",
    r"(?<![a-z])sprint(?:[-_\s]*\d+)?(?![a-z])",
    r"(?<![a-z])qa(?![a-z])",
    r"(?<![a-z])test(?![a-z])",
)
_ACCEPTANCE_CJK_MARKERS = ("验收", "演练", "测试")
_SEED_PATTERNS = (
    r"(?<![a-z])seed(?![a-z])",
    r"(?<![a-z])demo(?![a-z])",
    r"(?<![a-z])sample(?![a-z])",
)
_SEED_CJK_MARKERS = ("示例", "样例")


def infer_data_purpose(*values: Any) -> str:
    """Classify conservatively; ordinary records remain user-owned."""
    text = " ".join(str(value or "") for value in values).lower()
    if any(re.search(pattern, text) for pattern in _ACCEPTANCE_PATTERNS) or any(
        marker in text for marker in _ACCEPTANCE_CJK_MARKERS
    ):
        return "acceptance"
    if any(re.search(pattern, text) for pattern in _SEED_PATTERNS) or any(
        marker in text for marker in _SEED_CJK_MARKERS
    ):
        return "seed"
    return "user"
