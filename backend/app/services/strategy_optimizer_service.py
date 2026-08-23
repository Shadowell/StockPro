"""
AI Lab existing-strategy optimizer.

The optimizer is deliberately conservative: it only scans paper strategies,
creates a cloned optimized candidate, and pauses the source strategy only after
the candidate proves itself in a paper trial window.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.db.local_db import db_instance as db
from app.services.agent.code_sandbox import (
    load_base_strategy_class,
    validate_base_strategy_contract,
    validate_strategy_runtime_smoke,
)
from app.services.agent.llm_client import get_qwen_client, has_agent_api_key
from app.services.backtrader_engine import backtrader_engine
from app.services.strategy_engine import strategy_engine

logger = logging.getLogger(__name__)


FINAL_STATUSES = {"replaced", "failed", "cancelled", "skipped"}
ACTIVE_STATUSES = {"running", "trial_running"}
MAX_CANDIDATE_CODE_RETRIES = 3


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if out.tzinfo is None:
        out = out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


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


def _config_bool(config: Dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, str):
        return value.lower() not in {"0", "false", "no", "off"}
    return bool(value)


class StrategyOptimizerService:
    def __init__(
        self,
        *,
        database: Any = db,
        engine: Any = strategy_engine,
        now_fn: Callable[[], datetime] = utcnow,
    ) -> None:
        self.db = database
        self.engine = engine
        self.now_fn = now_fn
        self._run_lock = asyncio.Lock()
        self._stop_requested = False
        self._current_task: Optional[asyncio.Task[Any]] = None

    # -------------------------------------------------------
    # Public API
    # -------------------------------------------------------

    def get_config(self) -> Dict[str, Any]:
        return self.db.get_strategy_optimizer_config()

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        return self.db.update_strategy_optimizer_config(updates)

    def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            return self.db.get_strategy_optimization_runs(limit=limit, lightweight=True)
        except TypeError:
            return self.db.get_strategy_optimization_runs(limit=limit)

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        run = self.db.get_strategy_optimization_run(run_id)
        if run:
            run["events"] = self.db.get_strategy_optimization_events(run_id)
        return run

    @property
    def is_running(self) -> bool:
        return self._run_lock.locked()

    def request_stop(self) -> None:
        self._stop_requested = True

    def recover_interrupted_runs(self) -> Dict[str, Any]:
        """
        Process restarts lose the in-memory optimizer runner. Persisted runs that
        are still in status=running cannot resume safely because they may be in
        LLM generation or Backtrader execution; mark them failed so the source
        strategy can be considered again in a later scan. trial_running is kept:
        candidate trials are intentionally durable across restarts.
        """
        now = iso(self.now_fn())
        failed_runs: List[str] = []
        message = "服务重启，优化任务已中断，可在后续周期重新优化"
        for run in self.db.get_active_strategy_optimization_runs():
            if run.get("status") != "running":
                continue
            run["status"] = "failed"
            run["stage"] = "failed"
            run["error_message"] = message
            run["updated_at"] = now
            self.db.save_strategy_optimization_run(run)
            self._event(str(run.get("id")), "failed", message, {"reason": "service_restart"})
            failed_runs.append(str(run.get("id")))

        cfg = self.get_config()
        if cfg.get("running") or failed_runs:
            self.db.set_strategy_optimizer_runtime(
                running=False,
                last_finished_at=now,
                last_error="服务重启，自动优化扫描已中断",
            )

        return {"failed_runs": failed_runs, "running": False}

    async def stop_current(self) -> Dict[str, Any]:
        self.request_stop()
        current_task = asyncio.current_task()
        run_task = self._current_task
        if run_task is not None and run_task is not current_task and not run_task.done():
            run_task.cancel()

        cancelled: List[str] = []
        for run in self.db.get_active_strategy_optimization_runs():
            result = await self.cancel_run(str(run.get("id")))
            if result.get("cancelled"):
                cancelled.append(str(run.get("id")))

        if run_task is not None and run_task is not current_task and not run_task.done():
            try:
                await asyncio.wait_for(run_task, timeout=2.0)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                logger.warning("AI strategy optimizer stop timed out waiting for active runner")
            except Exception as exc:
                logger.debug("AI strategy optimizer runner finished during stop: %s", exc)

        self.db.set_strategy_optimizer_runtime(
            running=False,
            last_finished_at=iso(self.now_fn()),
            last_error="用户停止",
        )
        return {
            "stopped": True,
            "running": self.is_running,
            "cancelled_runs": cancelled,
            "message": "已请求停止现有策略优化",
        }

    async def run_once(self, *, force: bool = False) -> Dict[str, Any]:
        if self._run_lock.locked():
            return {"started": False, "running": True, "message": "自动优化周期正在运行"}

        async with self._run_lock:
            current_task = asyncio.current_task()
            self._current_task = current_task
            self._stop_requested = False
            try:
                cfg = self.get_config()
                if not force and not bool(cfg.get("enabled")):
                    return {"started": False, "running": False, "skipped": "disabled"}

                now = self.now_fn()
                self.db.set_strategy_optimizer_runtime(running=True, last_started_at=iso(now), last_error=None)
                actions: List[str] = []
                try:
                    self._raise_if_stop_requested()
                    actions.extend(await self.evaluate_trials(cfg, now))
                    self._raise_if_stop_requested()
                    sources = self._eligible_sources(cfg, now)
                    for source, snapshot in sources:
                        self._raise_if_stop_requested()
                        run = self._create_run(source, snapshot, now)
                        actions.append(f"optimize_started:{run['id']}:source={source['id']}")
                        await self._process_source_run(run, source, snapshot, cfg, now)
                    finished = self.now_fn()
                    self.db.set_strategy_optimizer_runtime(
                        running=False,
                        last_finished_at=iso(finished),
                        last_error=None,
                    )
                    return {
                        "started": True,
                        "running": False,
                        "actions": actions,
                        "eligible_count": len(sources),
                    }
                except asyncio.CancelledError:
                    self.db.set_strategy_optimizer_runtime(
                        running=False,
                        last_finished_at=iso(self.now_fn()),
                        last_error="用户停止",
                    )
                    return {"started": True, "running": False, "stopped": True, "actions": actions}
                except Exception as exc:
                    logger.exception("AI strategy optimizer cycle failed")
                    self.db.set_strategy_optimizer_runtime(
                        running=False,
                        last_finished_at=iso(self.now_fn()),
                        last_error=str(exc),
                    )
                    raise
            finally:
                if self._current_task is current_task:
                    self._current_task = None

    async def cancel_run(self, run_id: str) -> Dict[str, Any]:
        run = self.db.get_strategy_optimization_run(run_id)
        if not run:
            raise ValueError(f"优化任务 {run_id} 不存在")
        if run.get("status") in FINAL_STATUSES:
            return {"cancelled": False, "run_id": run_id, "status": run.get("status")}

        candidate_id = as_int(run.get("candidate_strategy_id"))
        if candidate_id > 0 and run.get("status") == "trial_running":
            await self.engine.stop_strategy(candidate_id, clear_metrics=False)

        run["status"] = "cancelled"
        run["stage"] = "cancelled"
        run["error_message"] = "用户取消"
        run["updated_at"] = iso(self.now_fn())
        self.db.save_strategy_optimization_run(run)
        self._event(run_id, "cancelled", "优化任务已取消", {})
        return {"cancelled": True, "run_id": run_id}

    def delete_run(self, run_id: str) -> Dict[str, Any]:
        run = self.db.get_strategy_optimization_run(run_id)
        if not run:
            raise ValueError(f"优化任务 {run_id} 不存在")
        if str(run.get("status") or "") in ACTIVE_STATUSES:
            raise ValueError("优化任务仍在运行中，请先停止后再删除记录")

        deleted = self.db.delete_strategy_optimization_run(run_id)
        if deleted.get("run_deleted", 0) <= 0:
            raise RuntimeError("优化记录删除失败")
        return {
            "deleted": True,
            "run_id": run_id,
            "events_deleted": deleted.get("events_deleted", 0),
        }

    # -------------------------------------------------------
    # Scan and trial evaluation
    # -------------------------------------------------------

    def _eligible_sources(self, cfg: Dict[str, Any], now: datetime) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        interval_hours = max(as_float(cfg.get("interval_hours"), 4.0), 0.0)
        low_return_pct = as_float(cfg.get("low_return_pct"), 0.0)
        out: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

        for source in self.db.get_strategies():
            if str(source.get("status") or "").lower() != "running":
                continue
            source_id = as_int(source.get("id"))
            config = source.get("config") or {}
            if not _config_bool(config, "is_paper_trading", True):
                continue
            started = parse_dt(source.get("run_started_at"))
            if not started or (now - started) < timedelta(hours=interval_hours):
                continue
            if self.db.get_active_strategy_optimization_runs(source_id):
                continue

            snapshot = self._strategy_snapshot(source)
            if as_float(snapshot.get("return_pct")) < low_return_pct:
                out.append((source, snapshot))
        return out

    async def evaluate_trials(self, cfg: Dict[str, Any], now: datetime) -> List[str]:
        actions: List[str] = []
        trial_hours = max(as_float(cfg.get("trial_hours"), 4.0), 0.0)
        success_return = as_float(cfg.get("trial_success_return_pct"), 0.0)

        for run in self.db.get_active_strategy_optimization_runs():
            if run.get("status") != "trial_running":
                continue
            started = parse_dt(run.get("trial_started_at"))
            if not started or (now - started) < timedelta(hours=trial_hours):
                continue

            candidate_id = as_int(run.get("candidate_strategy_id"))
            source_id = as_int(run.get("source_strategy_id"))
            candidate_row = self.db.get_strategy_by_id(candidate_id) if candidate_id > 0 else None
            if not candidate_row:
                self._fail_run(run, "候选策略记录不存在")
                continue

            snapshot = self._strategy_snapshot(candidate_row)
            ret = as_float(snapshot.get("return_pct"))
            run["candidate_return_pct"] = ret
            run["trial_checked_at"] = iso(now)
            run["trial_finished_at"] = iso(now)

            if ret > success_return:
                await self.engine.pause_strategy(source_id)
                run["stage"] = "replace"
                run["status"] = "replaced"
                run["updated_at"] = iso(now)
                self.db.save_strategy_optimization_run(run)
                self._event(
                    run["id"],
                    "replace",
                    "候选试运行转正，已暂停原策略并保留候选运行",
                    {"candidate_return_pct": ret, "source_strategy_id": source_id, "candidate_strategy_id": candidate_id},
                )
                actions.append(f"replaced:{source_id}:candidate={candidate_id}:return={ret:.2f}%")
            else:
                await self.engine.stop_strategy(candidate_id, clear_metrics=False)
                run["stage"] = "trial"
                run["status"] = "failed"
                run["error_message"] = "候选试运行 4 小时后收益未转正"
                run["updated_at"] = iso(now)
                self.db.save_strategy_optimization_run(run)
                self._event(
                    run["id"],
                    "trial",
                    "候选试运行未转正，已停止候选，原策略继续运行",
                    {"candidate_return_pct": ret, "candidate_strategy_id": candidate_id},
                )
                actions.append(f"trial_failed:{candidate_id}:return={ret:.2f}%")
        return actions

    # -------------------------------------------------------
    # Run processing
    # -------------------------------------------------------

    def _create_run(self, source: Dict[str, Any], snapshot: Dict[str, Any], now: datetime) -> Dict[str, Any]:
        run_id = f"opt_{uuid.uuid4().hex[:12]}"
        run = {
            "id": run_id,
            "source_strategy_id": as_int(source.get("id")),
            "source_strategy_name": source.get("name"),
            "stage": "monitor",
            "status": "running",
            "source_return_pct": as_float(snapshot.get("return_pct")),
            "source_snapshot": snapshot,
            "created_at": iso(now),
            "updated_at": iso(now),
        }
        self.db.save_strategy_optimization_run(run)
        self._event(run_id, "monitor", "发现低收益模拟策略，进入自动优化", snapshot)
        return run

    async def _process_source_run(
        self,
        run: Dict[str, Any],
        source: Dict[str, Any],
        snapshot: Dict[str, Any],
        cfg: Dict[str, Any],
        now: datetime,
    ) -> None:
        try:
            self._raise_if_stop_requested(run)
            self._advance(run, "diagnose", "收集绩效、成交和诊断日志")
            candidate = await self._generate_candidate(source, snapshot)
            self._raise_if_stop_requested(run)

            self._advance(run, "optimize", "AI 已生成优化候选")
            run["ai_analysis"] = str(candidate.get("reasoning") or candidate.get("description") or "")
            self.db.save_strategy_optimization_run(run)
            self._raise_if_stop_requested(run)

            self._advance(run, "backtest", "正在校验策略代码并执行回测")
            ok, report = await self._validate_candidate(source, candidate)
            self._raise_if_stop_requested(run)
            run["backtest_result"] = report
            self.db.save_strategy_optimization_run(run)
            if not ok:
                self._fail_run(run, str(report.get("error") or "候选策略未通过回测验证"))
                return

            candidate_id = self._save_candidate_strategy(source, candidate, run, report)
            run["candidate_strategy_id"] = candidate_id
            run["trial_started_at"] = iso(self.now_fn())
            run["stage"] = "trial"
            run["status"] = "trial_running"
            run["updated_at"] = iso(self.now_fn())
            self.db.save_strategy_optimization_run(run)

            started = await self.engine.start_strategy(candidate_id)
            if not started:
                self._fail_run(run, "候选策略启动失败")
                return
            self._event(
                run["id"],
                "trial",
                "优化候选已启动模拟盘试运行",
                {"candidate_strategy_id": candidate_id},
            )
        except Exception as exc:
            logger.exception("Strategy optimization run failed: %s", run.get("id"))
            self._fail_run(run, str(exc))

    def _advance(self, run: Dict[str, Any], stage: str, message: str) -> None:
        run["stage"] = stage
        run["status"] = "running"
        run["updated_at"] = iso(self.now_fn())
        self.db.save_strategy_optimization_run(run)
        self._event(run["id"], stage, message, {})

    def _fail_run(self, run: Dict[str, Any], message: str) -> None:
        run["stage"] = "failed"
        run["status"] = "failed"
        run["error_message"] = message
        run["updated_at"] = iso(self.now_fn())
        self.db.save_strategy_optimization_run(run)
        self._event(run["id"], "failed", message, {})

    def _cancel_run_state(self, run: Dict[str, Any], message: str = "用户停止") -> None:
        if run.get("status") in FINAL_STATUSES:
            return
        run["stage"] = "cancelled"
        run["status"] = "cancelled"
        run["error_message"] = message
        run["updated_at"] = iso(self.now_fn())
        self.db.save_strategy_optimization_run(run)
        self._event(run["id"], "cancelled", "优化任务已停止", {})

    def _raise_if_stop_requested(self, run: Optional[Dict[str, Any]] = None) -> None:
        if not self._stop_requested:
            return
        if run is not None:
            self._cancel_run_state(run)
        raise asyncio.CancelledError("用户停止")

    def _event(self, run_id: str, stage: str, message: str, detail: Dict[str, Any]) -> None:
        self.db.add_strategy_optimization_event(run_id, stage, message, detail, ts=iso(self.now_fn()))

    # -------------------------------------------------------
    # AI, validation and candidate creation
    # -------------------------------------------------------

    async def _generate_candidate(self, source: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
        if not has_agent_api_key():
            raise RuntimeError("DASHSCOPE_API_KEY 未配置，无法自动优化策略")

        llm_model = str(self.get_config().get("llm_model") or "").strip() or None
        client = get_qwen_client(llm_model)
        prompt = self._build_optimizer_prompt(source, snapshot)
        messages = [
            {
                "role": "system",
                "content": "你是 BitPro 量化策略优化工程师，只返回 JSON，不要输出 Markdown。",
            },
            {"role": "user", "content": prompt},
        ]
        last_error = ""
        for attempt in range(MAX_CANDIDATE_CODE_RETRIES):
            if attempt > 0 and last_error:
                messages.append({
                    "role": "user",
                    "content": (
                        "上一次优化候选代码没有通过 BitPro 当前策略合约校验：\n"
                        f"{last_error}\n\n"
                        "请重新输出完整 JSON。必须改写为当前 BaseStrategy 合约；"
                        "禁止 bitpro.strategy、bitpro.data、Strategy/DataFeed 等旧框架导入或 API；"
                        "合约开平仓必须使用 open_contract/close_contract，禁止 open_short/open_long/close_short/close_long。"
                    ),
                })

            result = await client.chat_json(
                messages,
                temperature=0.35,
                max_tokens=8192,
            )
            code = str(result.get("strategy_class_code") or result.get("code") or "").strip()
            if not code:
                last_error = "AI 未返回 strategy_class_code"
                continue

            try:
                await self._validate_candidate_code_contract(source, code)
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "AI optimizer candidate code validation failed (attempt %d): %s",
                    attempt + 1,
                    exc,
                )
                continue

            result["strategy_class_code"] = code
            return result

        raise RuntimeError(
            f"AI 在 {MAX_CANDIDATE_CODE_RETRIES} 次尝试后仍无法生成符合 BitPro 合约的优化候选: {last_error}"
        )

    def _build_optimizer_prompt(self, source: Dict[str, Any], snapshot: Dict[str, Any]) -> str:
        config = source.get("config") or {}
        compact_source = {
            "id": source.get("id"),
            "name": source.get("name"),
            "exchange": source.get("exchange"),
            "symbols": source.get("symbols"),
            "config": config,
            "status": source.get("status"),
            "run_started_at": source.get("run_started_at"),
        }
        return f"""请优化下面这个正在模拟盘运行但 4 小时收益率为负的 BitPro 策略。

要求：
1. 默认优先调整参数和风控；如果收益问题来自逻辑缺陷，可以改策略代码。
2. 必须输出一个完整的 BaseStrategy 子类，保留 async on_init / async on_bar 结构。
3. 必须使用真实 K 线和 BitPro 当前可用数据；禁止 mock、随机信号、外部网络、文件读写、CCXT 直连。
4. 策略必须适配原策略 symbols/feed universe；多币种时使用 bar.symbol 分币种维护状态。
5. 不要覆盖原策略；这是一个独立候选版本，会先进入模拟盘试运行。
6. NumPy/Pandas 数组不能直接用于 if/while/and/or/not；比较数组后必须取标量（如 arr[-1]）或显式使用 np.any()/np.all()。
7. 原策略代码可能来自旧框架，不能照抄旧导入；禁止 `from bitpro.strategy ...`、`from bitpro.data ...`、`Strategy`、`DataFeed`、`ctx`、`strategy(ctx)`、`setup(ctx)`。
8. 合约策略只能通过 `await self.open_contract(symbol, "long"|"short", notional_usdt, leverage=..., price=None)` 与 `await self.close_contract(symbol, "long"|"short", ratio=..., contracts=None, price=None)` 交易；禁止 `self.open_short/open_long/close_short/close_long` 或 `self.broker.open_short/open_long/close_short/close_long`。

允许的策略代码骨架只能使用当前 BitPro 合约：
```python
import numpy as np
from collections import deque
from app.core.execution.base_strategy import BaseStrategy, BarData
from app.services.indicators import SMA, EMA, RSI, MACD, BBANDS, ATR, KDJ, OBV

class OptimizedStrategy(BaseStrategy):
    async def on_init(self) -> None:
        self._closes = {{}}

    async def on_bar(self, bar: BarData) -> None:
        symbol = bar.symbol
        ...
```

返回 JSON：
{{
  "strategy_name": "简短中文名",
  "class_name": "OptimizedStrategyClass",
  "description": "优化点摘要",
  "reasoning": "为什么这样优化",
  "config_patch": {{"可选参数": "值"}},
  "strategy_class_code": "完整 Python 代码"
}}

原策略与运行快照：
{json.dumps({"source": compact_source, "snapshot": snapshot}, ensure_ascii=False, indent=2)}

原策略代码：
```python
{source.get("script_content") or ""}
```
"""

    async def _validate_candidate(
        self,
        source: Dict[str, Any],
        candidate: Dict[str, Any],
    ) -> Tuple[bool, Dict[str, Any]]:
        code = str(candidate.get("strategy_class_code") or "")
        try:
            await self._validate_candidate_code_contract(source, code)
            strategy_cls = load_base_strategy_class(code)
        except Exception as exc:
            return False, {"error": f"代码校验失败: {exc}"}

        config = dict(source.get("config") or {})
        patch = candidate.get("config_patch") or {}
        if isinstance(patch, dict):
            config.update(patch)
        end = self.now_fn().date()
        start = end - timedelta(days=365)
        symbols = source.get("symbols") or ["BTC/USDT"]
        if isinstance(symbols, str):
            symbols = [symbols]
        timeframe = str(config.get("timeframe") or "1m")
        initial = as_float(config.get("initial_capital"), 10000.0)
        commission = as_float(config.get("commission_rate"), as_float(config.get("fee_bps"), 10.0) / 10000.0)
        slippage = as_float(config.get("slippage"), as_float(config.get("slippage_bps"), 5.0) / 10000.0)

        def _run_backtest() -> Dict[str, Any]:
            report = backtrader_engine.run_strategy(
                strategy_cls,
                exchange=str(source.get("exchange") or "okx"),
                symbol=symbols[0],
                symbols=symbols,
                timeframe=timeframe,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                initial_capital=initial,
                commission=commission,
                slippage=slippage,
                strategy_config=config,
            )
            return {
                "status": report.status,
                "total_return_pct": report.total_return_pct,
                "max_drawdown_pct": report.max_drawdown_pct,
                "sharpe_ratio": report.sharpe_ratio,
                "profit_factor": report.profit_factor,
                "total_trades": report.total_trades,
            }

        try:
            result = await asyncio.to_thread(_run_backtest)
        except Exception as exc:
            return False, {"error": f"回测失败: {exc}"}

        source_result: Optional[Dict[str, Any]] = None
        try:
            from app.services.strategy_registry import resolve_unified_base_strategy_class

            unified = resolve_unified_base_strategy_class(source)
            if unified:
                source_cls, source_config = unified
            else:
                source_cls = load_base_strategy_class(str(source.get("script_content") or ""))
                source_config = dict(source.get("config") or {})

            def _run_source_backtest() -> Dict[str, Any]:
                report = backtrader_engine.run_strategy(
                    source_cls,
                    exchange=str(source.get("exchange") or "okx"),
                    symbol=symbols[0],
                    symbols=symbols,
                    timeframe=timeframe,
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    initial_capital=initial,
                    commission=commission,
                    slippage=slippage,
                    strategy_config=source_config,
                )
                return {
                    "status": report.status,
                    "total_return_pct": report.total_return_pct,
                    "max_drawdown_pct": report.max_drawdown_pct,
                    "total_trades": report.total_trades,
                }

            source_result = await asyncio.to_thread(_run_source_backtest)
            result["source_backtest"] = source_result
        except Exception as exc:
            result["source_backtest_error"] = str(exc)

        if result.get("status") != "completed":
            return False, {**result, "error": "回测未完成"}
        if as_int(result.get("total_trades")) <= 0:
            return False, {**result, "error": "回测交易数为 0"}

        source_return = (
            as_float(source_result.get("total_return_pct"), None)
            if source_result and source_result.get("status") == "completed"
            else None
        )
        if source_return is not None and as_float(result.get("total_return_pct")) < source_return:
            return False, {**result, "error": "候选回测收益低于源策略同区间表现"}
        if source_return is None and as_float(result.get("total_return_pct")) <= 0:
            return False, {**result, "error": "源策略无法比较时，候选回测收益必须为正"}
        return True, result

    async def _validate_candidate_code_contract(self, source: Dict[str, Any], code: str) -> None:
        validate_base_strategy_contract(code)
        await validate_strategy_runtime_smoke(
            code,
            symbols=source.get("symbols") or ["BTC/USDT"],
            market_type=str((source.get("config") or {}).get("market_type") or "spot"),
            timeframe=str((source.get("config") or {}).get("timeframe") or "1m"),
        )

    def _save_candidate_strategy(
        self,
        source: Dict[str, Any],
        candidate: Dict[str, Any],
        run: Dict[str, Any],
        backtest_result: Dict[str, Any],
    ) -> int:
        code = str(candidate.get("strategy_class_code") or "")
        strategy_cls = load_base_strategy_class(code)
        config = dict(source.get("config") or {})
        patch = candidate.get("config_patch") or {}
        if isinstance(patch, dict):
            config.update(patch)
        config.update({
            "is_paper_trading": True,
            "ai_optimized": True,
            "source_strategy_id": as_int(source.get("id")),
            "optimization_run_id": run["id"],
            "replaces_strategy_id": as_int(source.get("id")),
            "script_content_source": "db",
            "class_name": strategy_cls.__name__,
            "backtest_result": backtest_result,
        })
        name_base = str(candidate.get("strategy_name") or source.get("name") or "策略优化").strip()
        unique_name = f"[AI-OPT] {name_base} {self.now_fn().strftime('%m%d%H%M%S')}"
        return self.db.save_strategy(
            name=unique_name,
            description=str(candidate.get("description") or f"AI 自动优化自 {source.get('name')}"),
            script_content=code,
            config=config,
            exchange=source.get("exchange") or "okx",
            symbols=source.get("symbols") or ["BTC/USDT"],
        )

    # -------------------------------------------------------
    # Snapshot helpers
    # -------------------------------------------------------

    def _strategy_snapshot(self, source: Dict[str, Any]) -> Dict[str, Any]:
        source_id = as_int(source.get("id"))
        config = source.get("config") or {}
        status = self.engine.get_strategy_status(source_id) or {}
        initial = (
            as_float(status.get("initial_capital"), 0.0)
            or as_float(config.get("initial_capital"), 10000.0)
        )
        equity = as_float(status.get("equity"), initial)
        if status.get("return_pct") is not None:
            ret_pct = as_float(status.get("return_pct"))
        else:
            ret_pct = ((equity - initial) / initial * 100.0) if initial > 0 else 0.0

        trades = self.db.get_strategy_trades(source_id, 20)
        events: List[Dict[str, Any]] = []
        try:
            from app.services.strategy_log_store import strategy_log_store

            events = strategy_log_store.get(source_id, limit=20)
        except Exception:
            events = []

        return {
            "strategy_id": source_id,
            "status": status.get("status") or source.get("status"),
            "return_pct": ret_pct,
            "equity": equity,
            "initial_capital": initial,
            "total_trades": as_int(status.get("total_trades"), len(trades)),
            "positions": status.get("positions") or {},
            "recent_trades": trades,
            "recent_events": events,
            "run_started_at": source.get("run_started_at"),
        }


strategy_optimizer_service = StrategyOptimizerService()
