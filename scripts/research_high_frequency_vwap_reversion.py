#!/usr/bin/env python3
"""Real-data gate for the high-frequency VWAP reversion strategy."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import research_high_frequency_micro_breakout as base


ResearchDataError = base.ResearchDataError
discover_symbol_files = base.discover_symbol_files
load_complete_frames = base.load_complete_frames
simulate_segment = base.simulate_segment
summarize_simulation = base.summarize_simulation
summarize_rolling_fifteen_days = base.summarize_rolling_fifteen_days
freeze_parameter_metadata = base.freeze_parameter_metadata
DAY_MS = base.DAY_MS
FIVE_MINUTES_MS = base.FIVE_MINUTES_MS


VWAP_PARAMETERS = {
    "market_type": "swap",
    "timeframe": "5m",
    "primary_signal_timeframe": "1h",
    "initial_capital": 100,
    "leverage": 5,
    "min_h1_bars": 36,
    "candidate_count": 20,
    "turnover_window": 24,
    "state_confirmations": 2,
    "atr_window": 14,
    "adx_window": 14,
    "adx_min": 8,
    "adx_max": 18,
    "efficiency_window": 24,
    "efficiency_max": 0.18,
    "direction_window": 12,
    "direction_atr_max": 0.80,
    "atr_pct_min": 0.5,
    "atr_pct_max": 5.0,
    "h1_vwap_window": 24,
    "vwap_crosses_min": 4,
    "extension_atr_max": 1.2,
    "vwap_5m_window": 48,
    "z_entry": 2.0,
    "z_recovery_min": 0.25,
    "volume_window": 20,
    "volume_ratio_min": 0.8,
    "volume_ratio_max": 2.5,
    "max_bar_range_atr": 1.8,
    "round_trip_cost_bps": 20,
    "cost_edge_multiple": 3,
    "initial_stop_atr_mult": 0.9,
    "extreme_stop_buffer_atr": 0.35,
    "hard_take_profit_r": 1.10,
    "risk_per_trade_pct": 0.0035,
    "max_position_notional_usdt": 40,
    "max_positions": 4,
    "same_direction_cap": 2,
    "max_total_notional_equity_pct": 1.2,
    "min_order_notional_usdt": 0.5,
    "break_even_at_r": 0.40,
    "profit_trailing_start_r": 0.70,
    "profit_peak_pullback_pct": 0.25,
    "profit_atr_stop_mult": 0.55,
    "regime_break_adx": 24,
    "regime_break_efficiency": 0.35,
    "regime_break_direction_atr": 1.5,
    "max_holding_bars": 24,
    "cooldown_bars": 6,
    "loss_cooldown_count": 4,
    "loss_cooldown_hours": 2,
    "daily_loss_pct": 0.025,
    "daily_lock_activation_pct": 0.015,
    "daily_lock_fraction": 0.50,
    "terminal_floor_equity": 88,
}


def evaluate_gate(metrics):
    reasons = []
    if float(metrics.get("total_return_pct", 0.0)) <= 0:
        reasons.append("盲测总收益不为正")
    if float(metrics.get("profit_factor", 0.0)) < 1.20:
        reasons.append("盲测利润因子低于1.20")
    if float(metrics.get("max_drawdown_pct", 999.0)) > 12.0:
        reasons.append("盲测最大回撤超过12%")
    frequency = float(metrics.get("round_trips_per_day", 0.0))
    if frequency < 20.0:
        reasons.append("盲测日均闭环少于20")
    if frequency > 35.0:
        reasons.append("盲测日均闭环超过35")
    holding = float(metrics.get("avg_holding_minutes", 0.0))
    if holding < 30.0:
        reasons.append("平均持有少于30分钟")
    if holding > 120.0:
        reasons.append("平均持有超过120分钟")
    if float(metrics.get("first_half_return_pct", 0.0)) <= 0:
        reasons.append("盲测前半段不盈利")
    if float(metrics.get("second_half_return_pct", 0.0)) <= 0:
        reasons.append("盲测后半段不盈利")
    if float(metrics.get("positive_rolling_15d_share", 0.0)) < 0.70:
        reasons.append("滚动15日正收益比例低于70%")
    if float(metrics.get("single_symbol_profit_share", 1.0)) > 0.30:
        reasons.append("单一标的正利润贡献超过30%")
    if float(metrics.get("stress_total_return_pct", 0.0)) <= 0:
        reasons.append("压力成本收益不为正")
    if float(metrics.get("stress_profit_factor", 0.0)) < 1.05:
        reasons.append("压力成本利润因子低于1.05")
    if not bool(metrics.get("data_complete", False)):
        reasons.append("真实数据覆盖不完整")
    if not bool(metrics.get("parameter_hash_match", False)):
        reasons.append("验证与盲测参数hash不一致")
    return {"passed": not reasons, "reasons": reasons, **dict(metrics)}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="/opt/bitpro/data/klines/okx")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument(
        "--strategy-source",
        default="scripts/strategy_sources/high_frequency_vwap_reversion.py",
    )
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--train-days", type=int, default=60)
    parser.add_argument("--validation-days", type=int, default=30)
    parser.add_argument("--oos-days", type=int, default=30)
    parser.add_argument("--as-of-lag-hours", type=int, default=4)
    parser.add_argument("--minimum-symbols", type=int, default=20)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-report", required=True)
    return parser.parse_args()


def run_segment(frames, *, start_ms, end_ms, args, parameters, cost_rate):
    simulation = simulate_segment(
        frames,
        start_ms=start_ms,
        end_ms=end_ms,
        repo_root=args.repo_root,
        strategy_source=args.strategy_source,
        parameters=parameters,
        cost_rate_per_side=cost_rate,
    )
    return simulation, summarize_simulation(
        simulation["trades"], simulation["equity"], start_ms=start_ms, end_ms=end_ms
    )


def main():
    args = parse_args()
    if args.train_days + args.validation_days + args.oos_days != args.days:
        raise ResearchDataError("训练、验证和盲测天数之和必须等于总天数")
    as_of_ms = (
        int(time.time() * 1000) - int(args.as_of_lag_hours) * 3_600_000
    ) // FIVE_MINUTES_MS * FIVE_MINUTES_MS
    research_start = as_of_ms - int(args.days) * DAY_MS
    data_start = research_start - 48 * 3_600_000
    files = discover_symbol_files(
        args.data_root,
        start_ms=data_start,
        end_ms=as_of_ms,
        minimum_symbols=args.minimum_symbols,
    )
    frames, coverage = load_complete_frames(
        files,
        start_ms=data_start,
        end_ms=as_of_ms,
        minimum_symbols=args.minimum_symbols,
    )
    train_end = research_start + args.train_days * DAY_MS
    validation_end = train_end + args.validation_days * DAY_MS
    parameters = dict(VWAP_PARAMETERS)
    parameter_metadata = freeze_parameter_metadata(parameters)
    _, train = run_segment(
        frames,
        start_ms=research_start,
        end_ms=train_end,
        args=args,
        parameters=parameters,
        cost_rate=0.001,
    )
    _, validation = run_segment(
        frames,
        start_ms=train_end,
        end_ms=validation_end,
        args=args,
        parameters=parameters,
        cost_rate=0.001,
    )
    oos_sim, oos = run_segment(
        frames,
        start_ms=validation_end,
        end_ms=as_of_ms,
        args=args,
        parameters=parameters,
        cost_rate=0.001,
    )
    _, stress = run_segment(
        frames,
        start_ms=validation_end,
        end_ms=as_of_ms,
        args=args,
        parameters=parameters,
        cost_rate=0.002,
    )
    midpoint = validation_end + args.oos_days * DAY_MS // 2
    oos["first_half_return_pct"] = base._segment_return(
        oos_sim["equity"], validation_end, midpoint
    )
    oos["second_half_return_pct"] = base._segment_return(
        oos_sim["equity"], midpoint, as_of_ms
    )
    rolling = summarize_rolling_fifteen_days(
        oos_sim["equity"], start_ms=validation_end, end_ms=as_of_ms
    )
    gate = evaluate_gate(
        {
            **oos,
            "positive_rolling_15d_share": rolling["positive_window_share"],
            "stress_total_return_pct": stress["total_return_pct"],
            "stress_profit_factor": stress["profit_factor"],
            "data_complete": len(frames) >= args.minimum_symbols
            and min(coverage.values()) >= 0.97,
            "parameter_hash_match": parameter_metadata["validation_parameter_hash"]
            == parameter_metadata["oos_parameter_hash"],
        }
    )
    source = Path(args.strategy_source)
    if not source.is_absolute():
        source = Path(args.repo_root) / source
    result = {
        "data_coverage": {
            "root": args.data_root,
            "start_ms": data_start,
            "research_start_ms": research_start,
            "as_of_ms": as_of_ms,
            "complete_symbol_count": len(frames),
            "minimum_coverage_ratio": min(coverage.values()),
            "symbols": sorted(frames),
        },
        "assumptions": {
            "initial_equity": 100.0,
            "baseline_cost_rate_per_side": 0.001,
            "stress_cost_rate_per_side": 0.002,
            "funding": "not_modeled",
            "universe": "dynamic_trailing_24h_top20_from_complete_symbols",
        },
        "parameters": parameter_metadata,
        "train": train,
        "validation": validation,
        "out_of_sample": oos,
        "rolling_15d": rolling,
        "stress": stress,
        "gate": gate,
        "source_hash": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    output_json = Path(args.output_json)
    output_report = Path(args.output_report)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Top20 高频 VWAP 偏离回归锁利研究结果",
        "",
        f"- 数据截止：`{as_of_ms}`；完整5M标的 `{len(frames)}`。",
        f"- 盲测收益/PF/回撤：`{oos['total_return_pct']:.2f}% / {oos['profit_factor']:.3f} / {oos['max_drawdown_pct']:.2f}%`。",
        f"- 日均闭环与平均持有：`{oos['round_trips_per_day']:.2f} / {oos['avg_holding_minutes']:.1f}分钟`。",
        f"- 滚动15日正收益比例：`{rolling['positive_window_share']:.2%}`。",
        f"- 压力成本收益/PF：`{stress['total_return_pct']:.2f}% / {stress['profit_factor']:.3f}`。",
        f"- Paper门槛：`{'通过' if gate['passed'] else '未通过'}`。",
        f"- 未通过原因：`{'；'.join(gate['reasons']) if gate['reasons'] else '无'}`。",
        "",
        "限制：资金费率未建模；gate通过前不注册或启动Paper。",
    ]
    output_report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if not gate["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except ResearchDataError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(2)
