from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AuthToken:
    access_token: str
    token_type: Literal["bearer"]
    expires_in: int


@dataclass(frozen=True)
class AuthProfile:
    role: Literal["admin", "guest"]
    username: str | None
    permissions: tuple[str, ...]
    session_id: str
    expires_at: str
    guest_code_id: int | None = None
    max_backtests_per_day: int | None = None
    max_concurrent_backtests: int | None = None
    max_backtest_days: int | None = None
