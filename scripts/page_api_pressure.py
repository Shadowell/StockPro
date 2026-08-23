#!/usr/bin/env python3
"""Run low-impact pressure checks against BitPro page APIs."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8889/api/v2"
DEFAULT_AUTH_HEADER = "X-BitPro-MCP-Token"


@dataclass(frozen=True)
class Endpoint:
    page: str
    name: str
    path: str
    params: dict[str, Any] | None = None
    timeout: float | None = None

    @property
    def key(self) -> str:
        query = f"?{urllib.parse.urlencode(self.params or {}, doseq=True)}" if self.params else ""
        return f"{self.page}::{self.name}::{self.path}{query}"


STATIC_ENDPOINTS: list[Endpoint] = [
    Endpoint("首页", "系统健康", "/system/health"),
    Endpoint("首页", "交易所状态", "/system/exchanges"),
    Endpoint("首页", "行情总览", "/market/tickers", {"exchange": "okx", "offset": 0, "limit": 500}),
    Endpoint("首页", "资金费率摘要", "/funding/summary"),
    Endpoint(
        "首页",
        "首页资金费率",
        "/funding/rates",
        {"exchange": "okx", "symbols": "BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT"},
    ),
    Endpoint("行情", "合约标的列表", "/market/symbols", {"exchange": "okx", "quote": "USDT", "market_type": "swap"}),
    Endpoint("行情", "现货标的列表", "/market/symbols", {"exchange": "okx", "quote": "USDT", "market_type": "spot"}),
    Endpoint("行情", "实时行情", "/market/ticker", {"exchange": "okx", "symbol": "BTC/USDT:USDT"}),
    Endpoint("行情", "K线", "/market/klines", {"exchange": "okx", "symbol": "BTC/USDT:USDT", "timeframe": "15m", "limit": 180}),
    Endpoint(
        "行情",
        "技术指标",
        "/market/indicators",
        {"exchange": "okx", "symbol": "BTC/USDT:USDT", "timeframe": "15m", "limit": 180, "ema_periods": "5,10,20,30"},
    ),
    Endpoint("行情", "订单簿", "/market/orderbook", {"exchange": "okx", "symbol": "BTC/USDT:USDT", "limit": 20}),
    Endpoint(
        "行情",
        "预测对比",
        "/market/predictions/compare",
        {
            "exchange": "okx",
            "symbol": "BTC/USDT:USDT",
            "timeframe": "15m",
            "start_time": 0,
            "end_time": 0,
            "predict_steps": 30,
        },
        timeout=45,
    ),
    Endpoint("策略", "策略列表", "/strategies", {"page": 1, "per_page": 60}),
    Endpoint("信号", "信号列表", "/signals", {"limit": 80}),
    Endpoint("信号", "信号通道", "/signal-channels"),
    Endpoint("信号", "策略信号配置", "/signal-strategies"),
    Endpoint("回测", "策略选项", "/backtest/strategies"),
    Endpoint("回测", "回测结果列表", "/backtest/results", {"limit": 21, "offset": 0, "sort_by": "created", "sort_dir": "desc", "include_matrix_summary": "false"}),
    Endpoint("回测", "回测任务列表", "/backtest/jobs", {"limit": 50, "include_result": "false"}),
    Endpoint("模拟盘", "模拟实例列表", "/paper-trading/instances"),
    Endpoint("模拟盘", "运行策略列表", "/strategies", {"page": 1, "per_page": 60}),
    Endpoint("模拟盘", "模拟总览", "/live/dashboard"),
    Endpoint("模拟盘", "模拟事件", "/live/events", {"limit": 30}),
    Endpoint("模拟盘", "模拟权益曲线", "/live/equity_curve"),
    Endpoint("实盘", "实盘账户列表", "/live/accounts"),
    Endpoint("实盘", "实盘策略列表", "/live/strategies"),
    Endpoint("实盘", "账户余额", "/live/accounts/default/balance", timeout=45),
    Endpoint("实盘", "账户余额明细", "/live/accounts/default/balance/detail", timeout=45),
    Endpoint("实盘", "账户持仓", "/live/accounts/default/positions", timeout=45),
    Endpoint("实盘", "账户未成交订单", "/live/accounts/default/orders/open", timeout=45),
    Endpoint("实盘", "账户历史订单", "/live/accounts/default/orders/history", {"limit": 50}, timeout=45),
    Endpoint("盯盘", "盯盘列表", "/live/watchlist", {"account_id": "default", "limit": 100}),
    Endpoint("盯盘", "盯盘账户持仓", "/live/accounts/default/positions", timeout=45),
    Endpoint("盯盘", "盯盘历史订单", "/live/accounts/default/orders/history", {"limit": 100}, timeout=45),
    Endpoint("监控", "监控告警", "/monitor/alerts"),
    Endpoint("监控", "运行策略状态", "/monitor/active_strategies"),
    Endpoint("监控", "运行策略列表", "/monitor/running-strategies"),
    Endpoint("监控", "多空比", "/monitor/long-short-ratio", {"exchange": "okx", "symbol": "BTC/USDT:USDT"}, timeout=45),
    Endpoint("监控", "持仓量", "/monitor/open-interest", {"exchange": "okx", "symbol": "BTC/USDT:USDT"}, timeout=45),
    Endpoint("监控", "BTC行情", "/market/ticker", {"exchange": "okx", "symbol": "BTC/USDT"}),
    Endpoint("监控", "策略收益推送设置", "/settings/strategy-profit-push"),
    Endpoint("监控", "实盘收益推送设置", "/settings/live-profit-push"),
    Endpoint("数据", "数据统计", "/sync/table-stats"),
    Endpoint("数据", "同步配置", "/sync/config"),
    Endpoint("数据", "同步状态", "/sync/status"),
    Endpoint("数据", "定时同步", "/sync/schedule"),
    Endpoint("数据", "同步任务", "/sync/jobs", {"limit": 20, "include_items": "false"}),
    Endpoint("数据", "数据资产", "/sync/assets"),
    Endpoint("数据", "同步数据列表", "/sync/data", {"exchange": "okx"}),
    Endpoint("AI研发", "Agent任务列表", "/agent/tasks"),
    Endpoint("AI研发", "策略优化配置", "/agent/strategy-optimizer/config"),
    Endpoint("AI研发", "策略优化记录", "/agent/strategy-optimizer/runs", {"limit": 20}),
    Endpoint("AI研发", "自主交易实例", "/agent/autonomous-trader/instances", {"limit": 20}),
    Endpoint("AI研发", "自动发帖配置", "/agent/orbit-auto-post/config"),
    Endpoint("AI研发", "自动发帖候选", "/agent/orbit-auto-post/candidates", timeout=45),
    Endpoint("AI研发", "自动发帖登录状态", "/agent/orbit-auto-post/login-status"),
    Endpoint("AI研发", "策略助手调度", "/agent/strategy-assistant/scheduler"),
    Endpoint("复盘", "复盘摘要", "/review/summary", {"window": "24h", "bucket": "1h"}),
    Endpoint("链上", "链上摘要", "/onchain/summary", timeout=45),
    Endpoint("套利", "套利摘要", "/arbitrage/summary", timeout=45),
    Endpoint("设置", "通知配置", "/settings/notify"),
    Endpoint("设置", "飞书 Webhook", "/settings/feishu-webhook"),
    Endpoint("设置", "MCP Token", "/settings/mcp-token"),
    Endpoint("设置", "大模型配置", "/settings/llm-model"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--env-file", default="")
    parser.add_argument("--auth-header", default=os.environ.get("BITPRO_MCP_AUTH_HEADER", DEFAULT_AUTH_HEADER))
    parser.add_argument("--auth-token-env", default="BITPRO_MCP_API_TOKEN")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    return parser.parse_args()


def load_env_file(path: str) -> None:
    if not path:
        return
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def update_relative_prediction_window(endpoints: list[Endpoint]) -> list[Endpoint]:
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - 36 * 60 * 60 * 1000
    updated: list[Endpoint] = []
    for endpoint in endpoints:
        if endpoint.path == "/market/predictions/compare":
            params = dict(endpoint.params or {})
            params["start_time"] = start_ms
            params["end_time"] = now_ms
            updated.append(Endpoint(endpoint.page, endpoint.name, endpoint.path, params, endpoint.timeout))
        else:
            updated.append(endpoint)
    return updated


def make_url(base_url: str, endpoint: Endpoint) -> str:
    base = base_url.rstrip("/")
    path = endpoint.path if endpoint.path.startswith("/") else f"/{endpoint.path}"
    query = urllib.parse.urlencode(endpoint.params or {}, doseq=True)
    return f"{base}{path}{'?' + query if query else ''}"


def request_once(base_url: str, endpoint: Endpoint, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    url = make_url(base_url, endpoint)
    started = time.perf_counter()
    status: int | None = None
    body = b""
    error = ""
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = int(response.status)
            body = response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        body = exc.read(512)
        error = body.decode("utf-8", errors="replace")[:240] or str(exc)
    except Exception as exc:  # noqa: BLE001 - report endpoint failure text.
        error = str(exc)[:240]
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "status": status,
        "elapsed_ms": elapsed_ms,
        "bytes": len(body or b""),
        "ok": status is not None and 200 <= status < 300,
        "error": error,
        "url": url,
        "body_preview": body[:512].decode("utf-8", errors="replace") if body else "",
    }


def request_json_data(base_url: str, endpoint: Endpoint, headers: dict[str, str], timeout: float) -> Any:
    url = make_url(base_url, endpoint)
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
    except Exception:
        return None
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def first_id(value: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        for collection_key in ("items", "jobs", "instances", "tasks", "data", "results"):
            collection = value.get(collection_key)
            if isinstance(collection, list) and collection:
                return first_id(collection[0], keys)
        for key in keys:
            if value.get(key) not in (None, ""):
                return value.get(key)
    if isinstance(value, list) and value:
        return first_id(value[0], keys)
    return None


def discover_dynamic_endpoints(base_url: str, headers: dict[str, str], timeout: float) -> tuple[list[Endpoint], list[str]]:
    skipped: list[str] = []
    discovered: list[Endpoint] = []

    def get(endpoint: Endpoint) -> Any:
        return request_json_data(base_url, endpoint, headers, timeout)

    strategies = get(Endpoint("发现", "策略列表", "/strategies", {"page": 1, "per_page": 1}))
    strategy_id = first_id(strategies, ("id", "strategyId", "strategy_id"))
    if strategy_id:
        discovered.extend(
            [
                Endpoint("策略", "策略详情", f"/strategies/{strategy_id}"),
                Endpoint("策略", "策略状态", f"/strategies/{strategy_id}/status"),
                Endpoint("模拟盘", "策略成交", f"/strategies/{strategy_id}/trades", {"limit": 100}),
            ]
        )
    else:
        skipped.append("策略详情/状态：生产策略列表无可用 id")

    backtest_results = get(Endpoint("发现", "回测结果", "/backtest/results", {"limit": 1, "offset": 0}))
    backtest_id = first_id(backtest_results, ("id", "backtestId", "backtest_id"))
    if backtest_id:
        discovered.append(Endpoint("回测", "回测结果详情", f"/backtest/result/{backtest_id}"))
    else:
        skipped.append("回测结果详情：生产回测结果列表无可用 id")

    jobs = get(Endpoint("发现", "回测任务", "/backtest/jobs", {"limit": 1, "include_result": "false"}))
    job_id = first_id(jobs, ("jobId", "job_id", "id"))
    if job_id:
        discovered.append(Endpoint("回测", "回测任务详情", f"/backtest/job/{job_id}"))
    else:
        skipped.append("回测任务详情：生产回测任务列表无可用 job_id")

    papers = get(Endpoint("发现", "模拟实例", "/paper-trading/instances"))
    paper_id = first_id(papers, ("id", "instanceId", "instance_id"))
    if paper_id:
        discovered.append(Endpoint("模拟盘", "模拟实例详情", f"/paper-trading/instances/{paper_id}"))
    else:
        skipped.append("模拟实例详情：生产模拟实例列表无可用 id")

    tasks = get(Endpoint("发现", "Agent任务", "/agent/tasks"))
    task_id = first_id(tasks, ("id", "taskId", "task_id"))
    if task_id:
        discovered.extend(
            [
                Endpoint("AI研发", "Agent任务详情", f"/agent/tasks/{task_id}"),
                Endpoint("AI研发", "Agent迭代记录", f"/agent/tasks/{task_id}/iterations"),
            ]
        )
    else:
        skipped.append("Agent任务详情/迭代：生产任务列表无可用 id")

    watchlist = get(Endpoint("发现", "盯盘列表", "/live/watchlist", {"account_id": "default", "limit": 1}))
    watch_symbol = first_id(watchlist, ("symbol",))
    if watch_symbol:
        discovered.extend(
            [
                Endpoint("盯盘", "盯盘行情包", "/live/watchlist/market", {"account_id": "default", "symbol": watch_symbol, "timeframe": "15m", "limit": 180}, timeout=45),
                Endpoint("盯盘", "盯盘成交点", "/live/watchlist/markers", {"account_id": "default", "symbol": watch_symbol, "limit": 400}),
                Endpoint("盯盘", "盯盘衍生品数据", "/live/watchlist/derivatives-data", {"account_id": "default", "symbol": watch_symbol, "timeframe": "15m", "limit": 120}, timeout=45),
            ]
        )
    else:
        skipped.append("盯盘行情/成交点/衍生品数据：生产盯盘列表无可用 symbol")

    return discovered, skipped


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return ordered[index]


def summarize(endpoint: Endpoint, samples: list[dict[str, Any]]) -> dict[str, Any]:
    ok_samples = [sample for sample in samples if sample.get("ok")]
    elapsed = [float(sample["elapsed_ms"]) for sample in samples]
    ok_elapsed = [float(sample["elapsed_ms"]) for sample in ok_samples]
    status_counts: dict[str, int] = {}
    for sample in samples:
        status = str(sample.get("status") or "ERR")
        status_counts[status] = status_counts.get(status, 0) + 1
    errors = [sample.get("error") or "" for sample in samples if sample.get("error")]
    return {
        "page": endpoint.page,
        "name": endpoint.name,
        "path": endpoint.path,
        "params": endpoint.params or {},
        "url_path": make_url("", endpoint),
        "samples": len(samples),
        "ok": len(ok_samples),
        "errors": len(samples) - len(ok_samples),
        "status_counts": status_counts,
        "p50_ms": percentile(ok_elapsed or elapsed, 50),
        "p95_ms": percentile(ok_elapsed or elapsed, 95),
        "max_ms": max(elapsed) if elapsed else None,
        "avg_ms": statistics.fmean(elapsed) if elapsed else None,
        "avg_bytes": statistics.fmean([int(sample.get("bytes") or 0) for sample in samples]) if samples else 0,
        "first_error": errors[0] if errors else "",
    }


def run_endpoint(
    base_url: str,
    endpoint: Endpoint,
    headers: dict[str, str],
    samples: int,
    warmups: int,
    concurrency: int,
    default_timeout: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    timeout = endpoint.timeout or default_timeout
    for _ in range(max(0, warmups)):
        request_once(base_url, endpoint, headers, timeout)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [executor.submit(request_once, base_url, endpoint, headers, timeout) for _ in range(max(1, samples))]
        sample_rows = [future.result() for future in concurrent.futures.as_completed(futures)]
    return summarize(endpoint, sample_rows), sample_rows


def format_ms(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):.1f}"


def render_markdown(payload: dict[str, Any]) -> str:
    rows = payload["results"]
    slow = sorted(rows, key=lambda row: (row.get("p95_ms") is None, -(row.get("p95_ms") or 0)))[:12]
    failing = [row for row in rows if row.get("errors")]
    page_summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        page = row["page"]
        bucket = page_summary.setdefault(page, {"count": 0, "errors": 0, "max_p95": 0.0})
        bucket["count"] += 1
        bucket["errors"] += int(row.get("errors") or 0)
        bucket["max_p95"] = max(float(bucket["max_p95"]), float(row.get("p95_ms") or 0))

    lines = [
        f"# BitPro 页面接口压测报告（{payload['label']}）",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 目标：`{payload['base_url']}`",
        f"- 样本：每接口 warmup {payload['warmups']} 次，压测 {payload['samples']} 次，并发 {payload['concurrency']}",
        f"- 接口数：{len(rows)} 个只读页面接口",
        f"- 错误接口数：{len(failing)}",
        "",
        "## 慢接口 Top 12",
        "",
        "| 页面 | 接口 | p50 ms | p95 ms | max ms | 状态 | 平均字节 |",
        "|---|---|---:|---:|---:|---|---:|",
    ]
    for row in slow:
        lines.append(
            f"| {row['page']} | `{row['url_path']}` {row['name']} | {format_ms(row['p50_ms'])} | "
            f"{format_ms(row['p95_ms'])} | {format_ms(row['max_ms'])} | {row['status_counts']} | {row['avg_bytes']:.0f} |"
        )
    lines.extend(["", "## 页面汇总", "", "| 页面 | 接口数 | 样本错误数 | 页面最慢 p95 ms |", "|---|---:|---:|---:|"])
    for page, bucket in sorted(page_summary.items(), key=lambda item: item[0]):
        lines.append(f"| {page} | {bucket['count']} | {bucket['errors']} | {bucket['max_p95']:.1f} |")

    if payload.get("skipped"):
        lines.extend(["", "## 动态详情未覆盖", ""])
        for item in payload["skipped"]:
            lines.append(f"- {item}")

    if failing:
        lines.extend(["", "## 错误接口", "", "| 页面 | 接口 | 状态 | 首个错误 |", "|---|---|---|---|"])
        for row in failing:
            lines.append(
                f"| {row['page']} | `{row['url_path']}` {row['name']} | {row['status_counts']} | "
                f"{str(row.get('first_error') or '')[:180]} |"
            )

    lines.extend(["", "## 全量接口明细", "", "| 页面 | 名称 | 路径 | p50 ms | p95 ms | max ms | 状态 |", "|---|---|---|---:|---:|---:|---|"])
    for row in sorted(rows, key=lambda item: (item["page"], item["name"], item["url_path"])):
        lines.append(
            f"| {row['page']} | {row['name']} | `{row['url_path']}` | {format_ms(row['p50_ms'])} | "
            f"{format_ms(row['p95_ms'])} | {format_ms(row['max_ms'])} | {row['status_counts']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    load_env_file(args.env_file)
    token = os.environ.get(args.auth_token_env, "").strip()
    headers = {"User-Agent": "BitProPageApiPressure/1.0"}
    if token:
        headers[args.auth_header] = token
    endpoints = update_relative_prediction_window(STATIC_ENDPOINTS)
    dynamic, skipped = discover_dynamic_endpoints(args.base_url, headers, args.timeout)
    seen = {endpoint.key for endpoint in endpoints}
    for endpoint in dynamic:
        if endpoint.key not in seen:
            endpoints.append(endpoint)
            seen.add(endpoint.key)

    results: list[dict[str, Any]] = []
    raw: dict[str, list[dict[str, Any]]] = {}
    for index, endpoint in enumerate(endpoints, 1):
        print(f"[{index}/{len(endpoints)}] {endpoint.page} {endpoint.name} {endpoint.path}", file=sys.stderr)
        summary, samples = run_endpoint(
            args.base_url,
            endpoint,
            headers,
            args.samples,
            args.warmups,
            args.concurrency,
            args.timeout,
        )
        results.append(summary)
        raw[endpoint.key] = samples

    payload = {
        "label": args.label,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "samples": args.samples,
        "warmups": args.warmups,
        "concurrency": args.concurrency,
        "timeout": args.timeout,
        "auth_header": args.auth_header,
        "results": results,
        "skipped": skipped,
        "raw": raw,
    }

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(render_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
