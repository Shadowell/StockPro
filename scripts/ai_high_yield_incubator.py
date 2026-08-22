#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


AI_RESEARCH_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "DOGE/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "PEPE/USDT",
    "TRX/USDT",
    "PENGU/USDT",
    "PI/USDT",
    "SUI/USDT",
    "FIL/USDT",
    "ADA/USDT",
    "APE/USDT",
    "LINK/USDT",
    "LTC/USDT",
]
AI_RESEARCH_SCOPE = ",".join(AI_RESEARCH_SYMBOLS)
DEFAULT_STATE_FILE = "/opt/bitpro/data/ai_high_yield_incubator_state.json"
DEFAULT_API_BASE = "http://127.0.0.1:8889/api/v2"
TIMEFRAME_ROTATION = ("1m", "5m", "15m")
DEFAULT_INITIAL_EQUITY = 100.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        out = datetime.fromisoformat(text)
        if out.tzinfo is None:
            out = out.replace(tzinfo=timezone.utc)
        return out.astimezone(timezone.utc)
    except Exception:
        return None


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class IncubatorConfig:
    target_count: int = 5
    evaluation_hours: float = 4.0
    target_return_pct: float = 10.0
    min_backtest_return_pct: float = 10.0
    min_backtest_trades: int = 20
    max_concurrent_tasks: int = 2
    max_active_candidates: int = 8
    max_iterations: int = 5
    initial_equity: float = DEFAULT_INITIAL_EQUITY
    loop_interval_sec: int = 600
    live_loop_interval_sec: int = 60
    adopt_recent_hours: float = 48.0
    api_timeout_sec: int = 180


class ApiClient:
    def __init__(self, api_base: str, timeout_sec: int = 180):
        self.api_base = api_base.rstrip("/")
        self.timeout_sec = timeout_sec

    def _request(
        self,
        base: str,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        timeout: Optional[int] = None,
    ) -> Any:
        body = None
        headers = {"User-Agent": "bitpro-ai-high-yield-incubator/1.0"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(
            f"{base}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(req, timeout=timeout or self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
        except HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"{method} {path} HTTP {e.code}: {detail}") from e
        except URLError as e:
            raise RuntimeError(f"{method} {path} failed: {e}") from e
        if not raw:
            return None
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("success") is False:
            raise RuntimeError(f"{method} {path} failed: {data}")
        if isinstance(data, dict) and data.get("success") is True and "data" in data:
            return data["data"]
        return data

    def api(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Any:
        return self._request(self.api_base, method, path, payload, **kwargs)

    def list_tasks(self) -> List[Dict[str, Any]]:
        return list(self.api("GET", "/agent/tasks") or [])

    def create_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return dict(self.api("POST", "/agent/tasks", payload) or {})

    def resume_task(self, task_id: str) -> Dict[str, Any]:
        return dict(self.api("POST", f"/agent/tasks/{task_id}/resume", {}) or {})

    def get_iterations(self, task_id: str) -> List[Dict[str, Any]]:
        return list(self.api("GET", f"/agent/tasks/{task_id}/iterations") or [])

    def accept_iteration(self, task_id: str, iteration: int) -> Dict[str, Any]:
        return dict(self.api("POST", f"/agent/tasks/{task_id}/iterations/{iteration}/accept", {}) or {})

    def configure_paper_strategy(
        self,
        strategy_id: int,
        *,
        timeframe: str,
        initial_equity: float,
        loop_interval_sec: int,
    ) -> Dict[str, Any]:
        return dict(
            self.api(
                "POST",
                "/live/configure",
                {
                    "exchange": "okx",
                    "strategy_type": str(strategy_id),
                    "timeframe": timeframe,
                    "initial_equity": float(initial_equity),
                    "dry_run": True,
                    "loop_interval": int(loop_interval_sec),
                },
            )
            or {}
        )

    def start_strategy(self, strategy_id: int) -> Dict[str, Any]:
        return dict(self.api("POST", "/live/start", {"instance_id": int(strategy_id)}) or {})

    def stop_strategy(self, strategy_id: int) -> Dict[str, Any]:
        return dict(
            self.api(
                "POST",
                "/live/stop",
                {"instance_id": int(strategy_id), "clear_metrics": False},
            )
            or {}
        )

    def dashboard(self, strategy_id: int) -> Dict[str, Any]:
        query = urlencode({"instance_id": int(strategy_id)})
        return dict(self.api("GET", f"/live/dashboard?{query}", timeout=30) or {})


def empty_state() -> Dict[str, Any]:
    return {
        "version": 1,
        "tasks": {},
        "candidates": {},
        "events": [],
    }


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = empty_state()
    if not isinstance(data, dict):
        data = empty_state()
    data.setdefault("version", 1)
    data.setdefault("tasks", {})
    data.setdefault("candidates", {})
    data.setdefault("events", [])
    return data


def save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def record_event(state: Dict[str, Any], action: str, detail: Dict[str, Any], now: datetime) -> None:
    events = list(state.setdefault("events", []))
    events.append({"ts": iso(now), "action": action, "detail": detail})
    state["events"] = events[-300:]


def task_id_of(task: Dict[str, Any]) -> str:
    return str(task.get("task_id") or task.get("id") or "")


def task_created_at(task: Dict[str, Any]) -> Optional[datetime]:
    return parse_iso(task.get("created_at"))


def is_ai_research_task(task: Dict[str, Any]) -> bool:
    prompt = str(task.get("user_prompt") or "")
    symbol = str(task.get("symbol") or "")
    return "AI 策略猎手" in prompt or "4小时模拟收益" in prompt or symbol.count("/") >= 5


def adopt_recent_tasks(
    state: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    cfg: IncubatorConfig,
    now: datetime,
) -> None:
    cutoff = now - timedelta(hours=cfg.adopt_recent_hours)
    tracked = state.setdefault("tasks", {})
    for task in tasks:
        tid = task_id_of(task)
        if not tid or tid in tracked or not is_ai_research_task(task):
            continue
        created = task_created_at(task)
        if created is not None and created < cutoff:
            continue
        status = str(task.get("status") or "")
        if status not in {"pending", "running", "interrupted", "completed"}:
            continue
        tracked[tid] = {
            "task_id": tid,
            "created_at": task.get("created_at") or iso(now),
            "timeframe": task.get("timeframe") or "1m",
            "status": status,
            "accepted_iterations": [],
            "processed": False,
            "adopted": True,
        }
        record_event(state, "adopt_task", {"task_id": tid, "status": status}, now)


def candidate_return_pct(dashboard: Dict[str, Any]) -> float:
    perf = dashboard.get("performance") or {}
    equity = dashboard.get("equity") or {}
    if perf.get("total_pnl_pct") is not None:
        return as_float(perf.get("total_pnl_pct"))
    return as_float(equity.get("change_pct"))


def dashboard_state(dashboard: Dict[str, Any]) -> str:
    return str((dashboard.get("system") or {}).get("state") or "")


def dashboard_mode_is_paper(dashboard: Dict[str, Any]) -> bool:
    system = dashboard.get("system") or {}
    return bool(system.get("dry_run", True)) and str(system.get("mode") or "paper") == "paper"


def evaluate_candidates(
    client: ApiClient,
    state: Dict[str, Any],
    cfg: IncubatorConfig,
    now: datetime,
) -> List[str]:
    actions: List[str] = []
    for sid, candidate in sorted(state.setdefault("candidates", {}).items()):
        if candidate.get("stopped"):
            continue
        strategy_id = as_int(sid)
        if strategy_id <= 0:
            continue
        try:
            dash = client.dashboard(strategy_id)
        except Exception as e:
            record_event(state, "dashboard_error", {"strategy_id": strategy_id, "error": str(e)}, now)
            continue

        ret = candidate_return_pct(dash)
        state_name = dashboard_state(dash)
        candidate["last_return_pct"] = ret
        candidate["last_dashboard_state"] = state_name
        candidate["last_checked_at"] = iso(now)

        if not dashboard_mode_is_paper(dash):
            candidate["stopped"] = True
            candidate["stop_reason"] = "dashboard_not_paper"
            record_event(state, "skip_non_paper", {"strategy_id": strategy_id}, now)
            continue

        started = parse_iso(candidate.get("started_at")) or now
        age_hours = max(0.0, (now - started).total_seconds() / 3600.0)
        candidate["age_hours"] = round(age_hours, 4)

        if candidate.get("qualified"):
            if state_name != "running":
                try:
                    client.start_strategy(strategy_id)
                    actions.append(f"restart_qualified:{strategy_id}")
                    record_event(state, "restart_qualified", {"strategy_id": strategy_id}, now)
                except Exception as e:
                    record_event(state, "restart_qualified_error", {"strategy_id": strategy_id, "error": str(e)}, now)
            continue

        if age_hours < cfg.evaluation_hours:
            continue

        if ret >= cfg.target_return_pct:
            candidate["qualified"] = True
            candidate["qualified_at"] = iso(now)
            actions.append(f"qualified:{strategy_id}:{ret:.2f}%")
            record_event(
                state,
                "qualified",
                {"strategy_id": strategy_id, "return_pct": ret, "age_hours": age_hours},
                now,
            )
            if state_name != "running":
                try:
                    client.start_strategy(strategy_id)
                except Exception as e:
                    record_event(state, "qualified_restart_error", {"strategy_id": strategy_id, "error": str(e)}, now)
        else:
            try:
                client.stop_strategy(strategy_id)
                candidate["stopped"] = True
                candidate["stopped_at"] = iso(now)
                candidate["stop_reason"] = "four_hour_return_below_target"
                actions.append(f"stopped_underperformer:{strategy_id}:{ret:.2f}%")
                record_event(
                    state,
                    "stopped_underperformer",
                    {
                        "strategy_id": strategy_id,
                        "return_pct": ret,
                        "target_return_pct": cfg.target_return_pct,
                        "age_hours": age_hours,
                    },
                    now,
                )
            except Exception as e:
                record_event(state, "stop_error", {"strategy_id": strategy_id, "error": str(e)}, now)
    return actions


def metric_rank(record: Dict[str, Any]) -> Tuple[float, float, float, float, float]:
    metrics = record.get("backtest_metrics") or {}
    return (
        as_float(metrics.get("total_return_pct")),
        as_float(record.get("score")),
        as_float(metrics.get("profit_factor")),
        as_float(metrics.get("sharpe_ratio")),
        -as_float(metrics.get("max_drawdown_pct"), 100.0),
    )


def acceptance_candidates(
    iterations: List[Dict[str, Any]],
    cfg: IncubatorConfig,
    accepted_iterations: List[int],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    accepted = {int(i) for i in accepted_iterations}
    for record in iterations:
        iteration = as_int(record.get("iteration"), -1)
        if iteration < 0 or iteration in accepted:
            continue
        if str(record.get("error") or "").strip():
            continue
        if not str(record.get("strategy_code") or "").strip():
            continue
        metrics = record.get("backtest_metrics") or {}
        if as_float(metrics.get("total_return_pct")) < cfg.min_backtest_return_pct:
            continue
        if as_int(metrics.get("total_trades")) < cfg.min_backtest_trades:
            continue
        out.append(record)
    return sorted(out, key=metric_rank, reverse=True)


def active_candidate_count(state: Dict[str, Any]) -> int:
    count = 0
    for candidate in state.setdefault("candidates", {}).values():
        if candidate.get("stopped"):
            continue
        count += 1
    return count


def qualified_count(state: Dict[str, Any]) -> int:
    return sum(
        1
        for candidate in state.setdefault("candidates", {}).values()
        if candidate.get("qualified") and not candidate.get("stopped")
    )


def process_completed_tasks(
    client: ApiClient,
    state: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    cfg: IncubatorConfig,
    now: datetime,
) -> List[str]:
    actions: List[str] = []
    by_id = {task_id_of(task): task for task in tasks}
    tracked = state.setdefault("tasks", {})
    for tid, task_state in sorted(tracked.items()):
        task = by_id.get(tid)
        if not task:
            continue
        task_state["status"] = task.get("status")
        task_state["iterations_count"] = task.get("iterations_count")
        if task_state.get("processed"):
            continue
        if str(task.get("status") or "") != "completed":
            continue
        if qualified_count(state) >= cfg.target_count:
            task_state["processed"] = True
            continue

        try:
            iterations = client.get_iterations(tid)
        except Exception as e:
            record_event(state, "iterations_error", {"task_id": tid, "error": str(e)}, now)
            continue

        accepted = list(task_state.setdefault("accepted_iterations", []))
        for record in acceptance_candidates(iterations, cfg, accepted):
            if active_candidate_count(state) >= cfg.max_active_candidates:
                break
            if qualified_count(state) >= cfg.target_count:
                break
            iteration = as_int(record.get("iteration"))
            timeframe = str(task.get("timeframe") or task_state.get("timeframe") or "1m")
            try:
                saved = client.accept_iteration(tid, iteration)
                strategy_id = as_int(saved.get("strategy_id"))
                if strategy_id <= 0:
                    raise RuntimeError(f"accept returned invalid strategy_id: {saved}")
                client.configure_paper_strategy(
                    strategy_id,
                    timeframe=timeframe,
                    initial_equity=cfg.initial_equity,
                    loop_interval_sec=cfg.live_loop_interval_sec,
                )
                client.start_strategy(strategy_id)
            except Exception as e:
                record_event(
                    state,
                    "accept_or_start_error",
                    {"task_id": tid, "iteration": iteration, "error": str(e)},
                    now,
                )
                continue

            accepted.append(iteration)
            metrics = record.get("backtest_metrics") or {}
            state.setdefault("candidates", {})[str(strategy_id)] = {
                "strategy_id": strategy_id,
                "task_id": tid,
                "iteration": iteration,
                "strategy_name": saved.get("strategy_name") or record.get("strategy_name"),
                "timeframe": timeframe,
                "started_at": iso(now),
                "qualified": False,
                "stopped": False,
                "backtest_return_pct": as_float(metrics.get("total_return_pct")),
                "backtest_trades": as_int(metrics.get("total_trades")),
                "backtest_score": as_float(record.get("score")),
            }
            actions.append(f"accepted_started:{strategy_id}:task={tid}:iter={iteration}")
            record_event(
                state,
                "accepted_started",
                {
                    "strategy_id": strategy_id,
                    "task_id": tid,
                    "iteration": iteration,
                    "backtest_return_pct": as_float(metrics.get("total_return_pct")),
                },
                now,
            )
        task_state["accepted_iterations"] = accepted
        task_state["processed"] = True
    return actions


def active_research_task_count(state: Dict[str, Any], tasks: List[Dict[str, Any]]) -> int:
    statuses = {task_id_of(task): str(task.get("status") or "") for task in tasks}
    count = 0
    for tid in state.setdefault("tasks", {}):
        if statuses.get(tid) in {"pending", "running"}:
            count += 1
    return count


def research_prompt(cfg: IncubatorConfig) -> str:
    return f"""你是 AI 策略猎手。目标是持续研发能进入模拟盘孵化的高收益策略。

硬目标：
- 策略必须面向 OKX 高流动性现货币池，不要求用户选择单个交易对。
- 生成的策略必须是 BitPro BaseStrategy，使用 bar.symbol 分币种维护状态。
- 候选策略进入模拟盘后会运行 {cfg.evaluation_hours:.0f} 小时；若收益率未达到 {cfg.target_return_pct:.0f}% 以上会被停止。
- 因此请主动寻找 1m/5m/15m 上有短周期爆发力但仍有风控约束的策略，不要只优化长期低频收益。

研究方向不要局限于 Kairos 或 SuperPnL，可组合主流量化机构常用因子：
1. 时间序列动量、截面动量、趋势突破、回调再入场。
2. 成交量/流动性冲击、波动率收缩后扩张、短期反转。
3. 防御性过滤：低波动、趋势质量、假突破过滤、冷却时间、最短持仓。
4. Kairos、资金费率、多空比、持仓量、盘口等外生因子只有真实可用时才能使用；不可用时必须显式降级为 K 线可验证因子，禁止 mock。

每一轮都要和上一轮明显不同：改变市场假设、信号组合、退出规则或仓位控制。
请优先输出手续费和滑点后仍可能在短窗口保持高收益的策略，同时避免未来函数、过拟合和极端单笔押注。"""


def create_research_task(
    client: ApiClient,
    state: Dict[str, Any],
    cfg: IncubatorConfig,
    now: datetime,
) -> Optional[str]:
    task_index = len(state.setdefault("tasks", {}))
    timeframe = TIMEFRAME_ROTATION[task_index % len(TIMEFRAME_ROTATION)]
    end_date = now.date()
    start_date = end_date - timedelta(days=365)
    payload = {
        "symbol": AI_RESEARCH_SCOPE,
        "timeframe": timeframe,
        "backtest_start": start_date.isoformat(),
        "backtest_end": end_date.isoformat(),
        "max_iterations": cfg.max_iterations,
        "user_prompt": research_prompt(cfg),
        "goal": {
            "min_sharpe_ratio": 1.0,
            "max_drawdown_pct": 20.0,
            "min_win_rate_pct": 45.0,
            "min_total_return_pct": max(30.0, cfg.min_backtest_return_pct),
            "min_total_trades": cfg.min_backtest_trades,
            "min_profit_factor": 1.1,
        },
    }
    try:
        created = client.create_task(payload)
    except Exception as e:
        record_event(state, "create_task_error", {"error": str(e)}, now)
        return None
    tid = str(created.get("task_id") or "")
    if not tid:
        record_event(state, "create_task_error", {"error": f"missing task_id: {created}"}, now)
        return None
    state.setdefault("tasks", {})[tid] = {
        "task_id": tid,
        "created_at": iso(now),
        "timeframe": timeframe,
        "status": "pending",
        "accepted_iterations": [],
        "processed": False,
        "created_by_incubator": True,
    }
    record_event(state, "created_task", {"task_id": tid, "timeframe": timeframe}, now)
    return tid


def resume_interrupted_tasks(
    client: ApiClient,
    state: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    cfg: IncubatorConfig,
    now: datetime,
) -> List[str]:
    actions: List[str] = []
    if active_research_task_count(state, tasks) >= cfg.max_concurrent_tasks:
        return actions
    by_id = {task_id_of(task): task for task in tasks}
    for tid, task_state in sorted(state.setdefault("tasks", {}).items()):
        if active_research_task_count(state, tasks) >= cfg.max_concurrent_tasks:
            break
        task = by_id.get(tid)
        if not task or str(task.get("status") or "") != "interrupted":
            continue
        if as_int(task.get("iterations_count")) >= as_int(task.get("max_iterations"), cfg.max_iterations):
            task_state["processed"] = True
            continue
        try:
            client.resume_task(tid)
            actions.append(f"resumed_task:{tid}")
            task_state["status"] = "pending"
            task["status"] = "pending"
            record_event(state, "resumed_task", {"task_id": tid}, now)
        except Exception as e:
            record_event(state, "resume_task_error", {"task_id": tid, "error": str(e)}, now)
    return actions


def ensure_research_capacity(
    client: ApiClient,
    state: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    cfg: IncubatorConfig,
    now: datetime,
) -> List[str]:
    actions: List[str] = []
    if qualified_count(state) >= cfg.target_count:
        return actions
    actions.extend(resume_interrupted_tasks(client, state, tasks, cfg, now))
    tasks = client.list_tasks()
    while active_research_task_count(state, tasks) < cfg.max_concurrent_tasks:
        if active_candidate_count(state) >= cfg.max_active_candidates:
            break
        tid = create_research_task(client, state, cfg, now)
        if not tid:
            break
        actions.append(f"created_task:{tid}")
        tasks = client.list_tasks()
    return actions


def run_once(
    client: ApiClient,
    state: Dict[str, Any],
    cfg: IncubatorConfig,
    now: Optional[datetime] = None,
) -> List[str]:
    now = now or utcnow()
    actions: List[str] = []
    tasks = client.list_tasks()
    adopt_recent_tasks(state, tasks, cfg, now)
    actions.extend(evaluate_candidates(client, state, cfg, now))
    tasks = client.list_tasks()
    actions.extend(process_completed_tasks(client, state, tasks, cfg, now))
    tasks = client.list_tasks()
    actions.extend(ensure_research_capacity(client, state, tasks, cfg, now))
    state["last_run_at"] = iso(now)
    state["summary"] = {
        "qualified_count": qualified_count(state),
        "active_candidate_count": active_candidate_count(state),
        "tracked_task_count": len(state.get("tasks") or {}),
    }
    return actions


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the BitPro AI high-yield strategy incubator.")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    parser.add_argument("--target-count", type=int, default=5)
    parser.add_argument("--evaluation-hours", type=float, default=4.0)
    parser.add_argument("--target-return-pct", type=float, default=10.0)
    parser.add_argument("--min-backtest-return-pct", type=float, default=10.0)
    parser.add_argument("--min-backtest-trades", type=int, default=20)
    parser.add_argument("--max-concurrent-tasks", type=int, default=2)
    parser.add_argument("--max-active-candidates", type=int, default=8)
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--initial-equity", type=float, default=DEFAULT_INITIAL_EQUITY)
    parser.add_argument("--interval-sec", type=int, default=600)
    parser.add_argument("--live-loop-interval-sec", type=int, default=60)
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--status", action="store_true", help="print persisted state summary and exit")
    return parser


def cfg_from_args(args: argparse.Namespace) -> IncubatorConfig:
    return IncubatorConfig(
        target_count=int(args.target_count),
        evaluation_hours=float(args.evaluation_hours),
        target_return_pct=float(args.target_return_pct),
        min_backtest_return_pct=float(args.min_backtest_return_pct),
        min_backtest_trades=int(args.min_backtest_trades),
        max_concurrent_tasks=int(args.max_concurrent_tasks),
        max_active_candidates=int(args.max_active_candidates),
        max_iterations=int(args.max_iterations),
        initial_equity=float(args.initial_equity),
        loop_interval_sec=int(args.interval_sec),
        live_loop_interval_sec=int(args.live_loop_interval_sec),
    )


def print_status(state: Dict[str, Any]) -> None:
    print(
        json.dumps(
            {
                "last_run_at": state.get("last_run_at"),
                "summary": state.get("summary") or {},
                "tasks": len(state.get("tasks") or {}),
                "candidates": state.get("candidates") or {},
                "last_events": (state.get("events") or [])[-20:],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    state_path = Path(args.state_file)
    state = load_state(state_path)
    if args.status:
        print_status(state)
        return 0

    cfg = cfg_from_args(args)
    client = ApiClient(args.api_base, timeout_sec=cfg.api_timeout_sec)

    while True:
        try:
            state = load_state(state_path)
            actions = run_once(client, state, cfg)
            save_state(state_path, state)
            print(
                json.dumps(
                    {
                        "ts": iso(utcnow()),
                        "actions": actions,
                        "summary": state.get("summary"),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        except Exception as e:
            print(f"[ai-high-yield-incubator] cycle failed: {e}", file=sys.stderr, flush=True)
        if args.once:
            return 0
        time.sleep(max(30, int(cfg.loop_interval_sec)))


if __name__ == "__main__":
    raise SystemExit(main())
