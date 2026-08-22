#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import sleep
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_to_ms(value: str) -> Optional[int]:
    s = (value or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def _safe_json_loads(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8", errors="ignore")
        except Exception:
            return {}
    if not isinstance(value, str):
        return {}
    s = value.strip()
    if not s:
        return {}
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out:  # NaN
        return default
    if out in (float("inf"), float("-inf")):
        return default
    return out


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _configured_initial_capital(cfg: Dict[str, Any]) -> float:
    for key in ("initial_capital", "initialCapital", "initial_equity", "initialEquity"):
        val = _float(cfg.get(key), 0.0)
        if val > 0:
            return val
    return 10000.0


def _configured_paper_flag(cfg: Dict[str, Any]) -> Optional[bool]:
    def _to_bool(v: Any) -> Optional[bool]:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            if v in (0, 1):
                return bool(v)
            return None
        if isinstance(v, str):
            s = v.strip().lower()
            if s in ("true", "1", "yes", "y", "paper", "dry_run"):
                return True
            if s in ("false", "0", "no", "n", "live"):
                return False
        return None

    for key in ("is_paper_trading", "isPaperTrading"):
        b = _to_bool(cfg.get(key))
        if b is not None:
            return b
    for key in ("dry_run", "dryRun"):
        b = _to_bool(cfg.get(key))
        if b is not None:
            return b
    return None


def _ms_to_iso(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _fmt_money(x: float) -> str:
    return f"{x:.4f}"


def _fmt_pct(x: float) -> str:
    return f"{x:.4f}%"


def _almost_zero(x: float, eps: float = 1e-12) -> bool:
    return abs(x) <= eps


@dataclass(frozen=True)
class StrategyRow:
    id: int
    name: str
    status: str
    exchange: str
    run_started_at: Optional[str]
    config_raw: Any

    @property
    def config(self) -> Dict[str, Any]:
        return _safe_json_loads(self.config_raw)

    @property
    def initial_capital(self) -> float:
        return _configured_initial_capital(self.config)

    @property
    def paper_trading(self) -> Optional[bool]:
        return _configured_paper_flag(self.config)

    @property
    def run_started_ms(self) -> Optional[int]:
        if not self.run_started_at:
            return None
        return _parse_iso_to_ms(self.run_started_at)


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1;",
        (table,),
    )
    return cur.fetchone() is not None


def _fetch_strategies(
    conn: sqlite3.Connection,
    from_id: int,
    to_id: int,
) -> List[StrategyRow]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, status, exchange, run_started_at, config
        FROM strategies
        WHERE id BETWEEN ? AND ?
        ORDER BY id ASC;
        """,
        (from_id, to_id),
    )
    rows = []
    for r in cur.fetchall():
        rows.append(
            StrategyRow(
                id=_int(r["id"]),
                name=str(r["name"] or ""),
                status=str(r["status"] or ""),
                exchange=str(r["exchange"] or ""),
                run_started_at=str(r["run_started_at"] or "") or None,
                config_raw=r["config"],
            )
        )
    return rows


def _trade_window_since_ms(
    strategy: StrategyRow,
    *,
    since_hours: float,
    prefer_run_start: bool,
) -> int:
    now_ms = int(_utcnow().timestamp() * 1000)
    fallback = now_ms - int(since_hours * 3600 * 1000)
    if prefer_run_start:
        run_ms = strategy.run_started_ms
        if run_ms is not None and run_ms > 0 and run_ms <= now_ms:
            return run_ms
    return fallback


def _aggregate_trades(
    conn: sqlite3.Connection,
    strategy_id: int,
    since_ms: int,
    *,
    limit_recent: int,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            COUNT(1) AS total_trades,
            SUM(CASE WHEN side='SELL' THEN 1 ELSE 0 END) AS sell_trades,
            SUM(CASE WHEN side='SELL' AND COALESCE(pnl, 0) > 0 THEN 1 ELSE 0 END) AS winning_sells,
            SUM(COALESCE(pnl, 0)) AS realized_pnl,
            MAX(timestamp) AS last_trade_ts
        FROM strategy_trades
        WHERE strategy_id = ? AND timestamp >= ?;
        """,
        (strategy_id, since_ms),
    )
    agg_row = cur.fetchone() or {}
    total_trades = _int(agg_row["total_trades"], 0)
    sell_trades = _int(agg_row["sell_trades"], 0)
    winning_sells = _int(agg_row["winning_sells"], 0)
    realized_pnl = _float(agg_row["realized_pnl"], 0.0)
    last_trade_ts = agg_row["last_trade_ts"]
    last_trade_ts_int = _int(last_trade_ts, 0) if last_trade_ts is not None else 0

    win_rate = (winning_sells / sell_trades * 100.0) if sell_trades > 0 else 0.0

    cur.execute(
        """
        SELECT timestamp, side, symbol, price, quantity, fee, fee_asset, pnl
        FROM strategy_trades
        WHERE strategy_id = ? AND timestamp >= ?
        ORDER BY timestamp DESC
        LIMIT ?;
        """,
        (strategy_id, since_ms, int(max(1, limit_recent))),
    )
    recent: List[Dict[str, Any]] = []
    for r in cur.fetchall():
        ts = _int(r["timestamp"], 0)
        recent.append(
            {
                "timestamp": ts,
                "time": _ms_to_iso(ts) if ts else None,
                "side": str(r["side"] or ""),
                "symbol": str(r["symbol"] or ""),
                "price": _float(r["price"], 0.0),
                "quantity": _float(r["quantity"], 0.0),
                "fee": _float(r["fee"], 0.0) if r["fee"] is not None else None,
                "fee_asset": str(r["fee_asset"] or "") if r["fee_asset"] is not None else None,
                "pnl": _float(r["pnl"], 0.0) if r["pnl"] is not None else None,
            }
        )

    agg = {
        "total_trades": total_trades,
        "sell_trades": sell_trades,
        "winning_sells": winning_sells,
        "win_rate": round(win_rate, 6),
        "realized_pnl": round(realized_pnl, 8),
        "last_trade_ts": last_trade_ts_int or None,
        "last_trade_time": _ms_to_iso(last_trade_ts_int) if last_trade_ts_int else None,
    }
    return agg, recent


def _fee_in_quote_usdt(fee: Optional[float], fee_asset: Optional[str]) -> float:
    if fee is None:
        return 0.0
    asset = (fee_asset or "").strip().upper()
    if not asset:
        return 0.0
    # paper broker currently records fee in quote most of the time; keep this conservative
    if asset in ("USDT", "USD"):
        return float(fee)
    return 0.0


def _fetch_mark_price(
    conn: sqlite3.Connection,
    *,
    exchange: str,
    symbol: str,
    prefer_table: str = "kline_1m",
) -> Tuple[Optional[float], Optional[int], str]:
    """
    Returns (price, ts_ms, source).
    - source: kline_1m | none
    """
    ex = (exchange or "").strip()
    sym = (symbol or "").strip()
    if not ex or not sym:
        return None, None, "none"

    if _table_exists(conn, prefer_table):
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT close, timestamp
            FROM {prefer_table}
            WHERE exchange = ? AND symbol = ?
            ORDER BY timestamp DESC
            LIMIT 1;
            """,
            (ex, sym),
        )
        row = cur.fetchone()
        if row:
            px = _float(row["close"], 0.0)
            ts = _int(row["timestamp"], 0)
            if px > 0 and ts > 0:
                return px, ts, prefer_table

    return None, None, "none"


def _estimate_paper_state(
    conn: sqlite3.Connection,
    strategy: StrategyRow,
    *,
    since_ms: int,
) -> Dict[str, Any]:
    """
    Best-effort estimation for paper trading strategies using sqlite-only data:
    - Rebuilds cash/positions from strategy_trades.
    - Marks positions to market using latest close from kline_1m when available.
    """
    if not _table_exists(conn, "strategy_trades"):
        return {"positions": [], "account": {}, "diagnostics": {"reason": "missing_table:strategy_trades"}}

    cur = conn.cursor()
    cur.execute(
        """
        SELECT timestamp, side, symbol, price, quantity, fee, fee_asset, pnl
        FROM strategy_trades
        WHERE strategy_id = ? AND timestamp >= ?
        ORDER BY timestamp ASC;
        """,
        (int(strategy.id), int(since_ms)),
    )
    rows = cur.fetchall()

    initial_capital = float(strategy.initial_capital)
    cash = initial_capital
    # per symbol: size, avg_entry
    positions: Dict[str, Dict[str, float]] = {}
    last_trade_price: Dict[str, float] = {}

    realized_pnl_sum = 0.0
    realized_pnl_fallback = 0.0
    used_fallback = 0

    for r in rows:
        side = (str(r["side"] or "")).upper()
        sym = str(r["symbol"] or "")
        price = _float(r["price"], 0.0)
        qty = _float(r["quantity"], 0.0)
        fee_q = _fee_in_quote_usdt(r["fee"], r["fee_asset"])
        pnl = r["pnl"]

        if not sym or price <= 0 or qty <= 0:
            continue
        last_trade_price[sym] = price
        pos = positions.setdefault(sym, {"size": 0.0, "avg_entry": 0.0})
        size = float(pos["size"])
        avg_entry = float(pos["avg_entry"])

        if side == "BUY":
            notional = price * qty
            cash -= (notional + fee_q)
            new_size = size + qty
            if new_size > 0:
                pos["avg_entry"] = (avg_entry * size + price * qty) / new_size
            pos["size"] = new_size
        elif side == "SELL":
            notional = price * qty
            cash += (notional - fee_q)

            if pnl is not None:
                realized_pnl_sum += _float(pnl, 0.0)
            else:
                # fallback estimation only when broker didn't provide pnl
                if size > 0 and avg_entry > 0:
                    realized_pnl_fallback += (price - avg_entry) * min(qty, size)
                    used_fallback += 1

            new_size = size - qty
            if new_size <= 0:
                pos["size"] = 0.0
                pos["avg_entry"] = 0.0
            else:
                pos["size"] = new_size
        else:
            continue

    out_positions: List[Dict[str, Any]] = []
    total_unrealized = 0.0
    total_notional = 0.0
    price_missing = 0

    exchange = strategy.exchange or (strategy.config.get("exchange") if isinstance(strategy.config, dict) else "") or ""

    for sym, p in sorted(positions.items(), key=lambda kv: kv[0]):
        size = float(p.get("size", 0.0))
        if _almost_zero(size):
            continue
        avg_entry = float(p.get("avg_entry", 0.0))
        px, ts, src = _fetch_mark_price(conn, exchange=str(exchange), symbol=sym)
        if px is None:
            px = last_trade_price.get(sym)
            ts = None
            src = "last_trade"
        if px is None or px <= 0:
            price_missing += 1
            continue
        notional = size * float(px)
        unreal = (float(px) - avg_entry) * size if avg_entry > 0 else 0.0
        total_unrealized += unreal
        total_notional += notional
        out_positions.append(
            {
                "symbol": sym,
                "size": round(size, 12),
                "avg_entry": round(avg_entry, 12),
                "mark_price": float(px),
                "mark_time": _ms_to_iso(int(ts)) if ts else None,
                "price_source": src,
                "notional": round(notional, 8),
                "unrealized_pnl_est": round(unreal, 8),
            }
        )

    equity = cash + total_notional
    total_pnl = equity - initial_capital
    total_pnl_pct = (total_pnl / initial_capital * 100.0) if initial_capital > 0 else 0.0

    return {
        "positions": out_positions,
        "account": {
            "cash_est": round(cash, 8),
            "equity_est": round(equity, 8),
            "total_pnl_est": round(total_pnl, 8),
            "total_pnl_pct_est": round(total_pnl_pct, 8),
            "unrealized_pnl_est": round(total_unrealized, 8),
            "realized_pnl_sum": round(realized_pnl_sum, 8),
            "realized_pnl_fallback": round(realized_pnl_fallback, 8),
        },
        "diagnostics": {
            "trade_rows_used": len(rows),
            "fallback_pnl_count": used_fallback,
            "mark_price_missing_positions": price_missing,
        },
    }


def _config_slice(cfg: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        # universal
        "strategy_key",
        "timeframe",
        "symbols",
        "trade_symbols",
        "initial_capital",
        "is_paper_trading",
        "dry_run",
        # superpnl-15m low turnover knobs
        "threshold_bps",
        "top_k",
        "rebalance_interval_bars",
        "min_holding_bars",
        "cooldown_bars",
        "max_position_per_symbol",
        "max_total_position",
        "min_order_notional_usdt",
        # cost-aware / extra knobs (keep best-effort)
        "estimated_cost_bps",
    ]
    out: Dict[str, Any] = {}
    for k in keys:
        if k in cfg:
            out[k] = cfg.get(k)
    # keep it human-friendly
    if isinstance(out.get("symbols"), list):
        out["symbols_count"] = len(out["symbols"])
    if isinstance(out.get("trade_symbols"), list):
        out["trade_symbols_count"] = len(out["trade_symbols"])
    return out


def _http_get_json(url: str, *, timeout_sec: float) -> Tuple[Optional[Any], Optional[str]]:
    try:
        req = Request(url, headers={"User-Agent": "bitpro-superpnl-hourly-report/1.0"})
        with urlopen(req, timeout=max(0.5, float(timeout_sec))) as resp:
            raw = resp.read()
        text = raw.decode("utf-8", errors="ignore")
        return json.loads(text), None
    except HTTPError as e:
        return None, f"http_error:{getattr(e, 'code', '')}"
    except URLError:
        return None, "url_error"
    except Exception:
        return None, "unknown_error"


def _fetch_local_dashboard(
    *,
    base_url: str,
    instance_id: int,
    timeout_sec: float,
    max_recent_events: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    base = (base_url or "").rstrip("/")
    if not base:
        return None, "missing_api_base"
    qs = urlencode({"instance_id": int(instance_id)})
    url = f"{base}/api/v2/live/dashboard?{qs}"
    payload, err = _http_get_json(url, timeout_sec=timeout_sec)
    if err:
        return None, err
    if not isinstance(payload, dict):
        return None, "bad_payload"
    if payload.get("success") is not True:
        return None, "api_fail"
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, "bad_data"
    if isinstance(data.get("recent_events"), list) and max_recent_events > 0:
        data["recent_events"] = list(data.get("recent_events") or [])[: int(max_recent_events)]
    return data, None


def _summarize_recent_events(events: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(events, list) or not events:
        return None
    counts: Dict[str, int] = {}
    latest_time = None
    latest_ts = 0
    for e in events:
        if not isinstance(e, dict):
            continue
        decision = str(e.get("decision") or e.get("type") or "").strip()
        if decision:
            counts[decision] = counts.get(decision, 0) + 1
        ts = _int(e.get("timestamp") or e.get("bar_ts_ms") or e.get("signal_ts_ms"), 0)
        if ts > latest_ts:
            latest_ts = ts
            latest_time = e.get("time") or (_ms_to_iso(ts) if ts else None)
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
    return {
        "latest_event_time": latest_time,
        "top_decisions": [{"decision": k, "count": v} for k, v in top],
    }


def _render_text(
    items: List[Dict[str, Any]],
    *,
    title: str,
    now_iso: str,
    lang: str = "en",
    min_trades_for_judge: int = 0,
) -> str:
    lines: List[str] = []
    is_cn = (lang or "").lower() in ("cn", "zh", "zh-cn", "zh_cn")
    lines.append(title if not is_cn else "SuperPnL 小币策略小时监控")
    lines.append(f"generated_at(UTC): {now_iso}" if not is_cn else f"生成时间(UTC): {now_iso}")
    lines.append("")
    if not items:
        lines.append("no strategies matched." if not is_cn else "未匹配到策略。")
        return "\n".join(lines)

    def _pnl_metric(it: Dict[str, Any]) -> float:
        # prefer total pnl estimate when paper-state is available
        account = it.get("account")
        if isinstance(account, dict) and account.get("total_pnl_est") is not None:
            return _float(account.get("total_pnl_est"), 0.0)
        return _float(it.get("realized_pnl"), 0.0)

    winners = [it for it in items if _pnl_metric(it) > 0]
    losers = [it for it in items if _pnl_metric(it) < 0]
    flat = [it for it in items if _pnl_metric(it) == 0]

    def _one_line(it: Dict[str, Any]) -> str:
        sid = it.get("strategy_id")
        name = it.get("name") or "-"
        status = it.get("status") or "-"
        paper = it.get("paper_trading")
        paper_tag = "paper" if paper is True else ("live" if paper is False else "?mode")
        rpnl = _float(it.get("realized_pnl"), 0.0)
        cap = _float(it.get("initial_capital"), 0.0)
        pct = (rpnl / cap * 100.0) if cap > 0 else 0.0
        account = it.get("account")
        eq = account.get("equity_est") if isinstance(account, dict) else None
        tpnl = account.get("total_pnl_est") if isinstance(account, dict) else None
        tpnl_str = f" total≈{_fmt_money(_float(tpnl, 0.0))}" if tpnl is not None else ""
        eq_str = f" equity≈{_fmt_money(_float(eq, 0.0))}" if eq is not None else ""
        trades = _int(it.get("total_trades"), 0)
        win_rate = _float(it.get("win_rate"), 0.0)
        last = it.get("last_trade_time") or "-"
        run_age_min = it.get("run_age_min")
        age_str = ""
        if run_age_min is not None:
            age_str = f" age={_int(run_age_min, 0)}m" if not is_cn else f" 运行≈{_int(run_age_min, 0)}m"
        low_sample = ""
        if min_trades_for_judge and trades < int(min_trades_for_judge):
            low_sample = " sample=low" if not is_cn else " 样本偏少"
        return (
            f"#{sid} {name} [{status}|{paper_tag}] pnl={_fmt_money(rpnl)} ({_fmt_pct(pct)}) "
            f"trades={trades} win_rate={win_rate:.2f}% last={last}{age_str}{eq_str}{tpnl_str}{low_sample}"
        )

    lines.append(f"winners: {len(winners)}" if not is_cn else f"正收益: {len(winners)}")
    for it in sorted(winners, key=_pnl_metric, reverse=True):
        lines.append("  " + _one_line(it))
    lines.append("")

    lines.append(f"losers: {len(losers)}" if not is_cn else f"负收益: {len(losers)}")
    for it in sorted(losers, key=_pnl_metric):
        lines.append("  " + _one_line(it))
    lines.append("")

    lines.append(f"flat/unknown: {len(flat)}" if not is_cn else f"待观察/无成交: {len(flat)}")
    for it in sorted(flat, key=lambda x: _int(x.get('strategy_id'), 0)):
        lines.append("  " + _one_line(it))

    return "\n".join(lines)


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(
        description="SuperPnL hourly report (sqlite-only by default).",
    )
    ap.add_argument("--db", default="data/crypto_data.db", help="SQLite db path")
    ap.add_argument("--from-id", type=int, default=10, help="start strategy id (inclusive)")
    ap.add_argument("--to-id", type=int, default=19, help="end strategy id (inclusive)")
    ap.add_argument(
        "--since-hours",
        type=float,
        default=24.0,
        help="trade lookback window when run_started_at missing",
    )
    ap.add_argument(
        "--prefer-run-start",
        action="store_true",
        help="use strategies.run_started_at as window start when available",
    )
    ap.add_argument("--limit-trades", type=int, default=20, help="recent trades per strategy")
    ap.add_argument("--json", action="store_true", help="print JSON only")
    ap.add_argument(
        "--text-lang",
        default="en",
        help="text output language when not using --json (en|cn). JSON unaffected.",
    )
    ap.add_argument(
        "--min-trades-for-judge",
        type=int,
        default=0,
        help="mark strategies with low trade samples in text output",
    )
    ap.add_argument(
        "--include-paper-state",
        action="store_true",
        help="estimate paper positions/equity from strategy_trades + kline tables (sqlite-only)",
    )
    ap.add_argument(
        "--include-config-slice",
        action="store_true",
        help="include selected config fields for tuning (sqlite-only)",
    )
    ap.add_argument(
        "--include-local-dashboard",
        action="store_true",
        help="optionally sample local backend dashboard via 127.0.0.1 to include equity/perf/positions (off by default)",
    )
    ap.add_argument("--api-base", default="http://127.0.0.1:8889", help="local backend base url")
    ap.add_argument("--api-timeout-sec", type=float, default=2.0, help="local api timeout seconds")
    ap.add_argument(
        "--api-min-interval-sec",
        type=float,
        default=0.6,
        help="min interval between local api calls to reduce 429",
    )
    ap.add_argument(
        "--dashboard-for-statuses",
        default="running,paused",
        help="when --include-local-dashboard is set, only call dashboard for these statuses (comma-separated)",
    )
    ap.add_argument(
        "--dashboard-max",
        type=int,
        default=8,
        help="when --include-local-dashboard is set, cap dashboard calls to reduce pressure",
    )
    ap.add_argument(
        "--api-retry-429",
        action="store_true",
        help="retry once after a short backoff when dashboard returns 429",
    )
    ap.add_argument(
        "--api-max-recent-events",
        type=int,
        default=8,
        help="max dashboard recent_events to keep",
    )
    args = ap.parse_args(argv)

    conn = _connect(args.db)
    try:
        if not _table_exists(conn, "strategies"):
            raise SystemExit(f"missing table: strategies (db={args.db})")
        if not _table_exists(conn, "strategy_trades"):
            raise SystemExit(f"missing table: strategy_trades (db={args.db})")

        strategies = _fetch_strategies(conn, int(args.from_id), int(args.to_id))
        now_iso = _utcnow().isoformat().replace("+00:00", "Z")

        out_items: List[Dict[str, Any]] = []
        last_api_call_at = 0.0
        dashboard_statuses = {
            s.strip().lower()
            for s in str(args.dashboard_for_statuses).split(",")
            if s.strip()
        }
        dashboard_calls_left = int(max(0, args.dashboard_max))

        for st in strategies:
            now_ms = int(_utcnow().timestamp() * 1000)
            run_age_min = None
            if st.run_started_ms is not None and st.run_started_ms > 0 and st.run_started_ms <= now_ms:
                run_age_min = int((now_ms - st.run_started_ms) / 60000)

            since_ms = _trade_window_since_ms(
                st,
                since_hours=float(args.since_hours),
                prefer_run_start=bool(args.prefer_run_start),
            )
            agg, recent = _aggregate_trades(
                conn,
                int(st.id),
                since_ms,
                limit_recent=int(args.limit_trades),
            )
            paper_state: Optional[Dict[str, Any]] = None
            if bool(args.include_paper_state) and st.paper_trading is True:
                paper_state = _estimate_paper_state(conn, st, since_ms=since_ms)
            cfg_slice = _config_slice(st.config) if bool(args.include_config_slice) else None

            dashboard: Optional[Dict[str, Any]] = None
            dashboard_err: Optional[str] = None
            dashboard_summary: Optional[Dict[str, Any]] = None
            paper_warning = None
            if bool(args.include_local_dashboard):
                st_status = (st.status or "").strip().lower()
                if dashboard_calls_left <= 0:
                    dashboard_err = "skipped:max_calls"
                elif dashboard_statuses and st_status not in dashboard_statuses:
                    dashboard_err = f"skipped:status:{st_status or 'unknown'}"
                else:
                # low-pressure throttling to avoid backend 429
                    now = datetime.now().timestamp()
                    min_interval = max(0.0, float(args.api_min_interval_sec))
                    if last_api_call_at > 0 and now - last_api_call_at < min_interval:
                        sleep(min_interval - (now - last_api_call_at))
                    dashboard, dashboard_err = _fetch_local_dashboard(
                        base_url=str(args.api_base),
                        instance_id=int(st.id),
                        timeout_sec=float(args.api_timeout_sec),
                        max_recent_events=int(args.api_max_recent_events),
                    )
                    last_api_call_at = datetime.now().timestamp()
                    dashboard_calls_left -= 1
                    if (dashboard is None) and bool(args.api_retry_429) and dashboard_err == "http_error:429":
                        sleep(2.0)
                        dashboard, dashboard_err = _fetch_local_dashboard(
                            base_url=str(args.api_base),
                            instance_id=int(st.id),
                            timeout_sec=float(args.api_timeout_sec),
                            max_recent_events=int(args.api_max_recent_events),
                        )
                        last_api_call_at = datetime.now().timestamp()

                    if dashboard:
                        dashboard_summary = _summarize_recent_events(dashboard.get("recent_events"))
                        sys_state = (dashboard.get("system") or {}).get("state")
                        dry_run = (dashboard.get("system") or {}).get("dry_run")
                        mode = (dashboard.get("system") or {}).get("mode")
                        if dry_run is False or str(mode).lower() in ("live", "real", "trading"):
                            paper_warning = {
                                "reason": "dashboard_indicates_live_mode",
                                "system_state": sys_state,
                                "dry_run": dry_run,
                                "mode": mode,
                            }
            realized_pnl = _float(agg.get("realized_pnl"), 0.0)
            cap = st.initial_capital
            realized_pnl_pct = (realized_pnl / cap * 100.0) if cap > 0 else 0.0

            out_items.append(
                {
                    "strategy_id": int(st.id),
                    "name": st.name,
                    "status": st.status,
                    "exchange": st.exchange,
                    "run_started_at": st.run_started_at,
                    "run_age_min": run_age_min,
                    "paper_trading": st.paper_trading,
                    "initial_capital": cap,
                    "window_since_ms": since_ms,
                    "window_since_time": _ms_to_iso(since_ms),
                    "total_trades": agg.get("total_trades"),
                    "sell_trades": agg.get("sell_trades"),
                    "win_rate": agg.get("win_rate"),
                    "realized_pnl": realized_pnl,
                    "realized_pnl_pct": round(realized_pnl_pct, 8),
                    "last_trade_time": agg.get("last_trade_time"),
                    "recent_trades": recent,
                    "config_slice": cfg_slice,
                    "positions": (paper_state or {}).get("positions") if paper_state else None,
                    "account": (paper_state or {}).get("account") if paper_state else None,
                    "diagnostics": (paper_state or {}).get("diagnostics") if paper_state else None,
                    "dashboard": dashboard,
                    "dashboard_error": dashboard_err,
                    "dashboard_summary": dashboard_summary,
                    "paper_mode_warning": paper_warning,
                }
            )

        payload = {
            "generated_at": now_iso,
            "db": args.db,
            "strategy_id_range": [int(args.from_id), int(args.to_id)],
            "items": out_items,
        }

        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(
                _render_text(
                    out_items,
                    title="SuperPnL hourly report",
                    now_iso=now_iso,
                    lang=str(args.text_lang),
                    min_trades_for_judge=int(args.min_trades_for_judge),
                )
            )
            print("")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
