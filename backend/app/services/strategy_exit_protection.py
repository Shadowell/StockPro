"""Machine-checkable exit protection contract for directional strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


STOP_LOSS_FIELDS = (
    "stop_loss_bps",
    "stop_loss_pct",
    "stop_buffer_atr",
    "atr_stop_mult",
    "initial_stop_atr_mult",
    "initial_trailing_atr_mult",
    "trailing_atr_mult",
    "hard_inventory_stop_loss_pct",
    "max_basket_loss_equity_pct",
    "max_pool_loss_equity_pct",
)

TAKE_PROFIT_FIELDS = (
    "take_profit_bps",
    "take_profit_pct",
    "take_profit_atr_mult",
    "risk_reward_ratio",
    "profit_target_bps",
    "trailing_start_bps",
    "profit_trailing_start_r",
    "profit_atr_trailing_start_r",
    "profit_floor_start_bps",
)


def _positive_fields(config: Mapping[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    present: list[str] = []
    for field in fields:
        try:
            value = float(config.get(field) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            present.append(field)
    return tuple(present)


@dataclass(frozen=True)
class ExitProtectionAudit:
    has_stop_loss: bool
    has_take_profit: bool
    stop_loss_fields: tuple[str, ...]
    take_profit_fields: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.has_stop_loss and self.has_take_profit

    @property
    def detail(self) -> str:
        missing: list[str] = []
        if not self.has_stop_loss:
            missing.append("硬止损")
        if not self.has_take_profit:
            missing.append("止盈或浮盈锁利")
        if missing:
            return f"缺少{'、'.join(missing)}，禁止启用实盘"
        stop_fields = ", ".join(self.stop_loss_fields)
        profit_fields = ", ".join(self.take_profit_fields)
        return f"止损：{stop_fields}；止盈/锁利：{profit_fields}"


def audit_strategy_exit_protection(config: Mapping[str, Any] | None) -> ExitProtectionAudit:
    cfg = config if isinstance(config, Mapping) else {}
    stop_fields = _positive_fields(cfg, STOP_LOSS_FIELDS)
    take_fields = _positive_fields(cfg, TAKE_PROFIT_FIELDS)
    return ExitProtectionAudit(
        has_stop_loss=bool(stop_fields),
        has_take_profit=bool(take_fields),
        stop_loss_fields=stop_fields,
        take_profit_fields=take_fields,
    )
