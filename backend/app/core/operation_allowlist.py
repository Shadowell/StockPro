from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Iterable, Optional


@dataclass(frozen=True)
class OperationPattern:
    method: str
    path_pattern: str


def _parse_operation_pattern(raw: str) -> Optional[OperationPattern]:
    value = raw.strip()
    if not value:
        return None
    parts = value.split(None, 1)
    if len(parts) == 1:
        return OperationPattern(method="*", path_pattern=parts[0])
    return OperationPattern(method=parts[0].upper(), path_pattern=parts[1])


def compile_allowlist(patterns: Iterable[str]) -> list[OperationPattern]:
    compiled: list[OperationPattern] = []
    for raw in patterns:
        pattern = _parse_operation_pattern(raw)
        if pattern is not None:
            compiled.append(pattern)
    return compiled


def is_operation_allowed(
    *,
    allowlist: Iterable[OperationPattern],
    method: str,
    path: str,
) -> bool:
    request_method = method.upper()
    for rule in allowlist:
        if rule.method != "*" and rule.method != request_method:
            continue
        if fnmatch(path, rule.path_pattern):
            return True
    return False

