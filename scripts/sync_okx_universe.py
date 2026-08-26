#!/usr/bin/env python3
"""同步 OKX 全市场 USDT 永续合约最近三个月 K 线到 BitPro 数据模块。

特性：
- 自动发现 OKX 全市场当前有效的 USDT 永续合约标的
- 先写入数据模块配置，使这些标的可在 `/data` 页面被查询
- 按固定顺序同步时间粒度：1d -> 12h -> 4h -> 1h -> 30m -> 15m
- 每次只同步一个 K 线粒度，但该粒度内按 5 并行跑全市场标的
- 每个粒度完成后输出一次阶段摘要；全部完成后输出总摘要

示例：
  python3 scripts/sync_okx_universe.py
  DB_PATH=/opt/bitpro/data/crypto_data.db python3 scripts/sync_okx_universe.py --concurrency 5
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


FULL_SYNC_TIMEFRAME_ORDER = ["1d", "12h", "4h", "1h", "30m", "15m"]
DEFAULT_HISTORY_DAYS = 90
DEFAULT_EXCHANGE = "okx"
DEFAULT_CONCURRENCY = 5

_THREAD_STATE = threading.local()
_BACKEND_CACHE: Optional[Dict[str, Any]] = None


def normalize_timeframe_sequence(requested: Iterable[str]) -> List[str]:
    ordered: List[str] = []
    seen = set()
    requested_list = [str(value or "").strip() for value in requested if str(value or "").strip()]

    for timeframe in FULL_SYNC_TIMEFRAME_ORDER:
        if timeframe in requested_list and timeframe not in seen:
            ordered.append(timeframe)
            seen.add(timeframe)

    return ordered


def select_supported_usdt_symbols(markets: Iterable[Dict[str, Any]]) -> List[str]:
    symbols: List[str] = []
    for market in markets:
        symbol = str(market.get("symbol") or "").strip()
        if not symbol or market.get("active") is False:
            continue

        quote = str(market.get("quote") or "").upper()
        if quote != "USDT":
            continue

        settle = str(market.get("settle") or "").upper()
        if market.get("swap") and settle == "USDT":
            symbols.append(symbol)

    return sorted(dict.fromkeys(symbols))


def _backend() -> Dict[str, Any]:
    global _BACKEND_CACHE
    if _BACKEND_CACHE is None:
        from app.db.local_db import db_instance as db
        from app.exchange.okx import OKXExchange
        from app.services.data_sync_service import (
            API_REQUEST_DELAY,
            MAX_CONSECUTIVE_ERRORS,
            MAX_KLINES_PER_REQUEST,
            TIMEFRAME_MS,
            SyncStatus,
            DEFAULT_SYMBOLS,
        )
        from app.services.kline_file_store import kline_store
        from app.domain.sync.service import (
            CUSTOM_SYMBOLS_SETTING_KEY,
            REMOVED_DEFAULT_SYMBOLS_SETTING_KEY,
            SCHEDULE_SETTING_KEY,
        )

        _BACKEND_CACHE = {
            "db": db,
            "OKXExchange": OKXExchange,
            "API_REQUEST_DELAY": API_REQUEST_DELAY,
            "MAX_CONSECUTIVE_ERRORS": MAX_CONSECUTIVE_ERRORS,
            "MAX_KLINES_PER_REQUEST": MAX_KLINES_PER_REQUEST,
            "TIMEFRAME_MS": TIMEFRAME_MS,
            "SyncStatus": SyncStatus,
            "DEFAULT_SYMBOLS": DEFAULT_SYMBOLS,
            "kline_store": kline_store,
            "CUSTOM_SYMBOLS_SETTING_KEY": CUSTOM_SYMBOLS_SETTING_KEY,
            "REMOVED_DEFAULT_SYMBOLS_SETTING_KEY": REMOVED_DEFAULT_SYMBOLS_SETTING_KEY,
            "SCHEDULE_SETTING_KEY": SCHEDULE_SETTING_KEY,
        }
    return _BACKEND_CACHE


def _sync_start_date_ms(date_text: str) -> int:
    return int(datetime.strptime(date_text, "%Y-%m-%d").timestamp() * 1000)


def _sync_end_date_ms(date_text: str) -> int:
    end_date = datetime.strptime(date_text, "%Y-%m-%d") + timedelta(days=1)
    return int(end_date.timestamp() * 1000)


def _dedupe(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _market_listing_timestamp(exchange: Any, symbol: str) -> Optional[int]:
    try:
        market = exchange.exchange.market(symbol)
    except Exception:
        return None
    for value in (market.get("created"), (market.get("info") or {}).get("listTime")):
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            continue
        if timestamp > 0:
            return timestamp
    return None


def _get_thread_exchange() -> Any:
    cached = getattr(_THREAD_STATE, "okx_exchange", None)
    if cached is not None:
        return cached

    modules = _backend()
    # This maintenance job always synchronizes production public market data.
    # Do not inherit Settings.OKX_TESTNET from a cwd-dependent .env lookup.
    exchange = modules["OKXExchange"]({"testnet": False})
    exchange.initialize()
    exchange.load_markets(True)
    _THREAD_STATE.okx_exchange = exchange
    return exchange


def discover_okx_symbols() -> List[str]:
    exchange = _get_thread_exchange()
    markets = list(exchange.exchange.markets.values())
    return select_supported_usdt_symbols(markets)


def sync_symbol_timeframe(
    *,
    exchange_name: str,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: Optional[str],
) -> Dict[str, Any]:
    modules = _backend()
    db = modules["db"]
    kline_store = modules["kline_store"]
    interval_ms = modules["TIMEFRAME_MS"].get(timeframe, 60 * 60 * 1000)
    max_per_request = int(modules["MAX_KLINES_PER_REQUEST"])
    max_consecutive_errors = int(modules["MAX_CONSECUTIVE_ERRORS"])
    request_delay = float(modules["API_REQUEST_DELAY"])
    sync_status = modules["SyncStatus"]

    exchange = _get_thread_exchange()

    now_ms = int(datetime.now().timestamp() * 1000)
    requested_start_ms = _sync_start_date_ms(start_date)
    end_ms = _sync_end_date_ms(end_date) if end_date else now_ms

    listing_ms = _market_listing_timestamp(exchange, symbol)
    start_ms = max(requested_start_ms, listing_ms or requested_start_ms)

    result = {
        "exchange": exchange_name,
        "symbol": symbol,
        "timeframe": timeframe,
        "status": sync_status.COMPLETED.value,
        "fetched": 0,
        "inserted": 0,
        "error": None,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "ended_at": None,
    }

    if start_ms >= end_ms:
        stats = kline_store.get_stats(exchange_name, symbol, timeframe)
        db.update_sync_metadata(
            exchange_name,
            symbol,
            timeframe,
            "kline",
            first_timestamp=stats.get("first_timestamp"),
            last_timestamp=stats.get("last_timestamp"),
            total_records=stats.get("record_count", 0),
            status=sync_status.COMPLETED.value,
            last_sync_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            error_message=None,
        )
        result["ended_at"] = datetime.now().isoformat(timespec="seconds")
        return result

    db.update_sync_metadata(exchange_name, symbol, timeframe, "kline", status="syncing", error_message=None)

    current_ms = start_ms
    consecutive_errors = 0

    while current_ms < end_ms:
        try:
            klines = exchange.fetch_ohlcv(symbol, timeframe, limit=max_per_request, since=current_ms)
            if not klines:
                break

            klines = [kline for kline in klines if int(kline["timestamp"]) < end_ms]
            if not klines:
                break

            last_ts = int(klines[-1]["timestamp"])
            if last_ts < current_ms:
                break

            inserted = kline_store.append_klines(exchange_name, symbol, timeframe, klines)
            result["fetched"] += len(klines)
            result["inserted"] += int(inserted)
            current_ms = last_ts + interval_ms
            consecutive_errors = 0
            result["error"] = None

            db.update_sync_metadata(
                exchange_name,
                symbol,
                timeframe,
                "kline",
                last_timestamp=last_ts,
                status="syncing",
                total_records=result["fetched"],
            )

            time.sleep(request_delay)
        except Exception as exc:  # pragma: no cover - runtime path
            consecutive_errors += 1
            result["error"] = str(exc)
            if consecutive_errors >= max_consecutive_errors:
                result["status"] = sync_status.ERROR.value
                break
            time.sleep(min(2 ** consecutive_errors, 30))

    stats = kline_store.get_stats(exchange_name, symbol, timeframe)
    if result["fetched"] == 0 and int(stats.get("record_count", 0) or 0) == 0 and not result["error"]:
        result["error"] = f"交易所未返回 K 线: {exchange_name} {symbol} {timeframe}"
    final_status = sync_status.ERROR.value if result["error"] else sync_status.COMPLETED.value
    db.update_sync_metadata(
        exchange_name,
        symbol,
        timeframe,
        "kline",
        first_timestamp=stats.get("first_timestamp"),
        last_timestamp=stats.get("last_timestamp"),
        total_records=stats.get("record_count", 0),
        status=final_status,
        last_sync_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        error_message=result["error"],
    )

    result["status"] = final_status
    result["ended_at"] = datetime.now().isoformat(timespec="seconds")
    return result


def ensure_data_manager_symbols(all_symbols: List[str]) -> Dict[str, int]:
    modules = _backend()
    db = modules["db"]
    default_symbols = set(modules["DEFAULT_SYMBOLS"])
    custom_key = modules["CUSTOM_SYMBOLS_SETTING_KEY"]
    removed_key = modules["REMOVED_DEFAULT_SYMBOLS_SETTING_KEY"]

    merged_custom = _dedupe([symbol for symbol in all_symbols if symbol not in default_symbols])

    db.set_app_setting(custom_key, json.dumps(merged_custom, ensure_ascii=False))
    db.set_app_setting(
        removed_key,
        json.dumps(sorted(symbol for symbol in default_symbols if symbol not in all_symbols), ensure_ascii=False),
    )
    schedule_key = modules["SCHEDULE_SETTING_KEY"]
    try:
        schedule = json.loads(db.get_app_setting(schedule_key, "{}") or "{}")
    except (TypeError, json.JSONDecodeError):
        schedule = {}
    if not isinstance(schedule, dict):
        schedule = {}
    schedule.update({
        "history_days": DEFAULT_HISTORY_DAYS,
        "symbols": sorted(_dedupe(all_symbols)),
        "timeframes": ["15m", "30m", "1h", "4h", "12h", "1d"],
        "updated_at": datetime.now().isoformat(),
    })
    db.set_app_setting(schedule_key, json.dumps(schedule, ensure_ascii=False, sort_keys=True))

    return {
        "configured_symbols": len(default_symbols.union(all_symbols)),
        "custom_symbols": len(merged_custom),
    }


def format_timeframe_summary(
    *,
    timeframe: str,
    start_date: str,
    total_symbols: int,
    results: List[Dict[str, Any]],
    elapsed_seconds: float,
) -> str:
    success = sum(1 for item in results if item.get("status") == "completed" and not item.get("error"))
    failed = sum(1 for item in results if item.get("status") == "error" or item.get("error"))
    fetched = sum(int(item.get("fetched") or 0) for item in results)
    inserted = sum(int(item.get("inserted") or 0) for item in results)
    error_lines = [
        f"- {item['symbol']}: {item['error']}"
        for item in results
        if item.get("error")
    ][:10]
    body = [
        f"交易所：{DEFAULT_EXCHANGE.upper()}",
        f"周期：{timeframe}",
        f"起始日期：{start_date}",
        f"标的总数：{total_symbols}",
        f"成功：{success}",
        f"失败：{failed}",
        f"拉取记录：{fetched}",
        f"新增记录：{inserted}",
        f"耗时：{elapsed_seconds:.1f} 秒",
    ]
    if error_lines:
        body.append("")
        body.append("失败样本：")
        body.extend(error_lines)
    return "\n".join(body)


def run_timeframe_batch(
    *,
    exchange_name: str,
    symbols: List[str],
    timeframe: str,
    start_date: str,
    end_date: Optional[str],
    concurrency: int,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_map = {
            executor.submit(
                sync_symbol_timeframe,
                exchange_name=exchange_name,
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
            ): symbol
            for symbol in symbols
        }
        for future in as_completed(future_map):
            symbol = future_map[future]
            try:
                results.append(future.result())
            except Exception as exc:  # pragma: no cover - runtime path
                results.append(
                    {
                        "exchange": exchange_name,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "status": "error",
                        "fetched": 0,
                        "inserted": 0,
                        "error": str(exc),
                        "started_at": None,
                        "ended_at": None,
                    }
                )
    return sorted(results, key=lambda item: item["symbol"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步 OKX 全市场 USDT 标的 K 线到 BitPro 数据模块")
    parser.add_argument("--exchange", default=DEFAULT_EXCHANGE, help="交易所名称，默认 okx")
    parser.add_argument("--start-date", default=None, help="同步起始日期，默认最近90天")
    parser.add_argument("--end-date", default=None, help="同步结束日期，格式 YYYY-MM-DD，默认到当前时间")
    parser.add_argument(
        "--timeframes",
        default=",".join(FULL_SYNC_TIMEFRAME_ORDER),
        help="按逗号分隔的时间粒度列表，固定支持 1d,12h,4h,1h,30m,15m",
    )
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="每个时间粒度的并行度，默认 5")
    parser.add_argument("--limit-symbols", type=int, default=0, help="仅同步前 N 个标的，0 表示全部")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args = parse_args()
    if not args.start_date:
        args.start_date = (datetime.now() - timedelta(days=DEFAULT_HISTORY_DAYS)).strftime("%Y-%m-%d")
    earliest_start = (datetime.now() - timedelta(days=DEFAULT_HISTORY_DAYS)).date()
    requested_start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    if requested_start < earliest_start:
        raise ValueError(f"全量同步只允许最近 90 天，开始日期不得早于 {earliest_start.isoformat()}")

    if args.exchange != DEFAULT_EXCHANGE:
        raise ValueError("当前脚本仅支持 OKX")

    requested_timeframes = normalize_timeframe_sequence(args.timeframes.split(","))
    if not requested_timeframes:
        raise ValueError("至少需要一个时间粒度")

    logging.info("发现 OKX 全市场 USDT 标的...")
    symbols = discover_okx_symbols()
    if args.limit_symbols and args.limit_symbols > 0:
        symbols = symbols[: args.limit_symbols]

    if not symbols:
        raise RuntimeError("未发现可同步的 OKX USDT 标的")

    config_stats = ensure_data_manager_symbols(symbols)
    logging.info(
        "数据模块配置已更新：总标的 %s，自定义标的 %s",
        config_stats["configured_symbols"],
        config_stats["custom_symbols"],
    )

    all_results: Dict[str, List[Dict[str, Any]]] = {}
    total_started_at = time.monotonic()

    for timeframe in requested_timeframes:
        logging.info("开始同步 %s，共 %s 个标的，并行度 %s", timeframe, len(symbols), args.concurrency)
        started_at = time.monotonic()
        timeframe_results = run_timeframe_batch(
            exchange_name=args.exchange,
            symbols=symbols,
            timeframe=timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
            concurrency=max(1, int(args.concurrency)),
        )
        elapsed_seconds = time.monotonic() - started_at
        all_results[timeframe] = timeframe_results

        summary = format_timeframe_summary(
            timeframe=timeframe,
            start_date=args.start_date,
            total_symbols=len(symbols),
            results=timeframe_results,
            elapsed_seconds=elapsed_seconds,
        )
        logging.info("周期 %s 同步完成\n%s", timeframe, summary)

    total_elapsed = time.monotonic() - total_started_at
    final_lines = [
        f"交易所：{args.exchange.upper()}",
        f"标的数量：{len(symbols)}",
        f"起始日期：{args.start_date}",
        f"时间粒度：{' / '.join(requested_timeframes)}",
        f"总耗时：{total_elapsed:.1f} 秒",
    ]
    for timeframe in requested_timeframes:
        timeframe_results = all_results.get(timeframe, [])
        success = sum(1 for item in timeframe_results if item.get("status") == "completed" and not item.get("error"))
        failed = sum(1 for item in timeframe_results if item.get("status") == "error" or item.get("error"))
        inserted = sum(int(item.get("inserted") or 0) for item in timeframe_results)
        final_lines.append(f"{timeframe}: 成功 {success} / 失败 {failed} / 新增 {inserted}")

    final_summary = "\n".join(final_lines)
    logging.info("全部同步完成\n%s", final_summary)

    artifact_path = PROJECT_ROOT / "tmp" / f"okx_universe_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(
            {
                "exchange": args.exchange,
                "start_date": args.start_date,
                "end_date": args.end_date,
                "timeframes": requested_timeframes,
                "symbol_count": len(symbols),
                "concurrency": args.concurrency,
                "summary": final_lines,
                "results": all_results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logging.info("同步结果已写入 %s", artifact_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
