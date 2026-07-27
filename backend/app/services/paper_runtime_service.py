"""Pinned, replayable Paper runtime with append-only risk and operator evidence."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import psycopg2.extras

from app.services.dataset_snapshot_service import DatasetSnapshotService, canonical_hash
from app.services.data_purpose import infer_data_purpose
from app.services.strategy_runtime_service import STRATEGY_API_VERSION, StrategyRuntimeService


PAPER_RUNTIME_VERSION = "paper-runtime.v1"


class PaperRuntimeService:
    def __init__(self, database):
        self.database = database
        self.datasets = DatasetSnapshotService(database)
        self.runtime = StrategyRuntimeService(database)

    def create_instance(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        required = (
            "strategy_version_id", "dataset_snapshot_id", "factor_snapshot_id", "universe_snapshot_id",
            "pool_snapshot_id", "research_protocol_id", "qualifying_backtest_run_id",
        )
        if any(payload.get(item) in (None, "", 0) for item in required):
            raise ValueError("Paper 实例必须绑定策略、数据、因子、Universe、股票池、协议和晋级回测")
        qualifying = self._row(
            """
            SELECT * FROM backtest_runs
            WHERE id=%s AND status='success' AND run_mode='full' AND promotion_status='paper_eligible'
            """,
            (str(payload["qualifying_backtest_run_id"]),),
        )
        if not qualifying:
            raise ValueError("晋级回测不存在或未通过 Paper 门禁")
        expected = {
            "strategy_version_id": str(payload["strategy_version_id"]),
            "dataset_snapshot_id": int(payload["dataset_snapshot_id"]),
            "factor_snapshot_id": int(payload["factor_snapshot_id"]),
            "universe_snapshot_id": int(payload["universe_snapshot_id"]),
            "pool_snapshot_id": int(payload["pool_snapshot_id"]),
            "research_protocol_id": str(payload["research_protocol_id"]),
        }
        for key, value in expected.items():
            actual = qualifying.get(key)
            actual = str(actual) if key.endswith("_version_id") or key == "research_protocol_id" else (int(actual) if actual is not None else None)
            if actual != value:
                raise ValueError(f"晋级回测与 Paper 固定输入不一致: {key}")
        pool = self._row("SELECT * FROM stock_pool_snapshots WHERE id=%s AND status='sealed'", (expected["pool_snapshot_id"],))
        factor = self._row("SELECT * FROM factor_snapshots WHERE id=%s AND status='sealed'", (expected["factor_snapshot_id"],))
        universe = self._row("SELECT * FROM universe_snapshots WHERE id=%s AND status='sealed'", (expected["universe_snapshot_id"],))
        dataset = self._row("SELECT * FROM dataset_snapshots WHERE id=%s AND status='sealed'", (expected["dataset_snapshot_id"],))
        protocol = self._row("SELECT * FROM research_protocols WHERE id=%s AND status='sealed'", (expected["research_protocol_id"],))
        version = self._row(
            "SELECT * FROM strategy_versions WHERE id=%s AND validation_status='valid' AND strategy_api_version=%s",
            (expected["strategy_version_id"], STRATEGY_API_VERSION),
        )
        if not all((pool, factor, universe, dataset, protocol, version)):
            raise ValueError("Paper 固定输入缺失或未封存")
        if (
            int(pool["dataset_snapshot_id"]) != expected["dataset_snapshot_id"]
            or int(pool["factor_snapshot_id"] or 0) != expected["factor_snapshot_id"]
            or int(pool["universe_snapshot_id"]) != expected["universe_snapshot_id"]
        ):
            raise ValueError("股票池快照与数据/因子/Universe 不兼容")
        oos = self._row(
            "SELECT id FROM backtest_protocol_evaluations WHERE backtest_run_id=%s AND sample_label='out_of_sample' AND status='passed'",
            (qualifying["id"],),
        )
        capacity = self._row(
            "SELECT id FROM backtest_promotion_checks WHERE backtest_run_id=%s AND check_code IN ('CAPACITY_PASS','capacity') AND status='passed'",
            (qualifying["id"],),
        )
        if not oos or not capacity:
            raise ValueError("Paper 启动需要通过样本外评估和容量检查")
        initial_cash = float(payload.get("initial_cash") or 1_000_000)
        if initial_cash <= 0:
            raise ValueError("初始资金必须为正数")
        capacity_limits = {
            "cash_floor_ratio": 0.05, "max_single_symbol_weight": 1.0, "max_participation_ratio": 0.10,
            "max_drawdown": 0.20, "max_daily_turnover": 2.0,
            **dict(payload.get("capacity_limits") or {}),
        }
        feed_config = {
            "mode": "recorded_replay", "stale_after_seconds": 900, "provider": "sealed_pg_snapshot",
            "allow_new_entries_when_stale": False, **dict(payload.get("feed_config") or {}),
        }
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "INSERT INTO portfolios(name,mode,initial_cash,cash_balance,status) VALUES (%s,'paper',%s,%s,'paused') RETURNING id",
                    (str(payload.get("name") or f"{version['name']} / Paper {datetime.now().isoformat(timespec='seconds')}"), initial_cash, initial_cash),
                )
                portfolio_id = str(cursor.fetchone()["id"])
                cursor.execute(
                    """
                    INSERT INTO paper_instances
                    (name,strategy_version_id,dataset_snapshot_id,factor_snapshot_id,universe_snapshot_id,pool_snapshot_id,
                     research_protocol_id,qualifying_backtest_run_id,portfolio_id,parameters,capacity_limits,feed_config,
                     status,runtime_version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s) RETURNING id
                    """,
                    (
                        str(payload.get("name") or f"{version['name']} / Paper"), expected["strategy_version_id"],
                        expected["dataset_snapshot_id"], expected["factor_snapshot_id"], expected["universe_snapshot_id"],
                        expected["pool_snapshot_id"], expected["research_protocol_id"], qualifying["id"], portfolio_id,
                        psycopg2.extras.Json(payload.get("parameters") or {}), psycopg2.extras.Json(capacity_limits),
                        psycopg2.extras.Json(feed_config), PAPER_RUNTIME_VERSION,
                    ),
                )
                instance_id = str(cursor.fetchone()["id"])
                cursor.execute(
                    "INSERT INTO cash_ledger(portfolio_id,paper_instance_id,event_type,amount,balance_after,ref_type,note) VALUES (%s,%s,'deposit',%s,%s,'paper_instance','初始模拟资金')",
                    (portfolio_id, instance_id, initial_cash, initial_cash),
                )
                self._event_cursor(cursor, instance_id, None, "lifecycle", "info", "Paper 实例草稿已创建", {"qualifying_backtest_run_id": str(qualifying["id"])})
        return self.get_instance(instance_id)

    def start(self, instance_id: str) -> Dict[str, Any]:
        instance = self._instance(instance_id)
        if instance["status"] == "running":
            return {**self.get_instance(instance_id), "reused": True}
        if instance["status"] not in {"draft", "stopped"}:
            raise ValueError(f"当前状态不能启动: {instance['status']}")
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE paper_instances SET status='starting',updated_at=NOW() WHERE id=%s", (instance_id,))
                self._event_cursor(cursor, instance_id, None, "lifecycle", "info", "启动门禁通过，实例正在启动", {})
                cursor.execute("UPDATE portfolios SET status='active',updated_at=NOW() WHERE id=%s", (instance["portfolio_id"],))
                cursor.execute("UPDATE paper_instances SET status='running',started_at=COALESCE(started_at,NOW()),heartbeat_at=NOW(),updated_at=NOW() WHERE id=%s", (instance_id,))
                self._event_cursor(cursor, instance_id, None, "lifecycle", "info", "Paper 实例已运行", {})
        return self.get_instance(instance_id)

    def pause(self, instance_id: str) -> Dict[str, Any]:
        instance = self._instance(instance_id)
        if instance["status"] == "paused":
            return {**self.get_instance(instance_id), "reused": True}
        if instance["status"] != "running":
            raise ValueError("只有运行中实例可以暂停")
        self._state(instance, "paused", "operator", "Paper 实例已暂停")
        return self.get_instance(instance_id)

    def resume(self, instance_id: str) -> Dict[str, Any]:
        instance = self._instance(instance_id)
        if instance["status"] == "running":
            return {**self.get_instance(instance_id), "reused": True}
        if instance["status"] != "paused":
            raise ValueError("只有暂停实例可以恢复")
        self._state(instance, "running", "operator", "Paper 实例从持久化游标恢复")
        return self.get_instance(instance_id)

    def stop(self, instance_id: str) -> Dict[str, Any]:
        instance = self._instance(instance_id)
        if instance["status"] == "stopped":
            return {**self.get_instance(instance_id), "reused": True}
        if instance["status"] not in {"running", "paused", "failed"}:
            raise ValueError("当前状态不能停止")
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE paper_instances SET status='stopping',updated_at=NOW() WHERE id=%s", (instance_id,))
                self._event_cursor(cursor, instance_id, None, "lifecycle", "warning", "Paper 实例正在停止", {})
                cursor.execute("UPDATE portfolios SET status='archived',updated_at=NOW() WHERE id=%s", (instance["portfolio_id"],))
                cursor.execute("UPDATE paper_instances SET status='stopped',stopped_at=NOW(),updated_at=NOW() WHERE id=%s", (instance_id,))
                self._event_cursor(cursor, instance_id, None, "lifecycle", "warning", "Paper 实例已停止，持仓与现金保留审计", {})
        return self.get_instance(instance_id)

    def process_cycle(self, instance_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        instance = self._instance(instance_id)
        if instance["status"] != "running":
            raise ValueError("只有运行中实例可以处理行情周期")
        trade_date = str(payload.get("trade_date") or "")[:10]
        if not trade_date:
            raise ValueError("行情周期缺少 trade_date")
        data_available_at = self._timestamp(payload.get("data_available_at") or f"{trade_date}T15:00:00+08:00")
        observed_at = self._timestamp(payload.get("observed_at") or data_available_at)
        cycle_key = str(payload.get("cycle_key") or f"{trade_date}:close")
        input_manifest = {
            "paper_instance_id": instance_id, "cycle_key": cycle_key, "trade_date": trade_date,
            "data_available_at": data_available_at.isoformat(), "observed_at": observed_at.isoformat(),
            "dataset_snapshot_id": int(instance["dataset_snapshot_id"]), "runtime_version": PAPER_RUNTIME_VERSION,
        }
        input_hash = canonical_hash(input_manifest)
        cycle_id, reused = self._open_cycle(instance_id, cycle_key, trade_date, data_available_at, observed_at, input_hash)
        if reused:
            return {**self.get_cycle(cycle_id), "reused": True}
        try:
            symbols = [
                str(item["symbol"]) for item in self._rows(
                    "SELECT symbol FROM stock_pool_snapshot_members WHERE snapshot_id=%s ORDER BY ordinal",
                    (int(instance["pool_snapshot_id"]),),
                )
            ]
            all_bars = self.datasets.load_daily_bars(int(instance["dataset_snapshot_id"]), symbols=symbols, limit=1_000_000)
            bars = {str(item["symbol"]): item for item in all_bars if str(item.get("trade_date"))[:10] == trade_date}
            if not bars:
                raise ValueError("固定数据快照在该交易日没有股票池行情")
            stale_seconds = max(0, (observed_at - data_available_at).total_seconds())
            stale_after = int((instance.get("feed_config") or {}).get("stale_after_seconds") or 900)
            if stale_seconds > stale_after:
                self._record_event(instance_id, cycle_id, "feed", "critical", "行情超过 SLA，禁止新开仓", {"stale_seconds": stale_seconds, "sla_seconds": stale_after})
                self._alert("stale_feed", instance_id, "data", "critical", "Paper 行情已过期", "新开仓已阻断，退出和估值仍保留", "paper_runtime_cycle", cycle_id, {"trade_date": trade_date, "stale_seconds": stale_seconds}, f"stale:{instance_id}:{trade_date}")
                order_count, trade_count = self._execute_pending_signals(
                    instance, cycle_id, trade_date, bars, data_available_at, allow_new_entries=False
                )
                equity = self._persist_equity(instance, cycle_id, trade_date, bars)
                self._finish_cycle(cycle_id, "blocked", 0, order_count, trade_count, equity["ledger_difference"])
                self._execute(
                    "UPDATE paper_instances SET last_processed_trade_date=%s,last_cycle_key=%s,heartbeat_at=%s,updated_at=NOW() WHERE id=%s",
                    (trade_date, cycle_key, observed_at, instance_id),
                )
                self._health("paper_feed", "critical", observed_at, "STALE_FEED", "行情超过 SLA", {"instance_id": instance_id, "trade_date": trade_date})
                return self.get_cycle(cycle_id)
            order_count, trade_count = self._execute_pending_signals(instance, cycle_id, trade_date, bars, data_available_at)
            start_date = (date.fromisoformat(trade_date) - timedelta(days=120)).isoformat()
            replay = self.runtime.replay(str(instance["strategy_version_id"]), {
                "dataset_snapshot_id": int(instance["dataset_snapshot_id"]), "factor_snapshot_id": int(instance["factor_snapshot_id"]),
                "mode": "paper_replay", "start_date": start_date, "end_date": trade_date, "symbols": symbols,
                "parameters": dict(instance.get("parameters") or {}), "event_limit": 500,
            })
            if replay["status"] != "success":
                raise ValueError(f"Paper 策略回放失败: {replay.get('error_code') or replay.get('error_message')}")
            intents = [
                item for item in self.runtime.list_intents(replay["run_id"])
                if str(item["simulated_at"])[:10] == trade_date
            ]
            signal_count = self._persist_signals(instance, cycle_id, intents)
            equity = self._persist_equity(instance, cycle_id, trade_date, bars)
            self._finish_cycle(cycle_id, "success", signal_count, order_count, trade_count, equity["ledger_difference"])
            self._execute(
                "UPDATE paper_instances SET last_processed_trade_date=%s,last_cycle_key=%s,heartbeat_at=%s,updated_at=NOW() WHERE id=%s",
                (trade_date, cycle_key, observed_at, instance_id),
            )
            self._record_event(instance_id, cycle_id, "cycle", "info", "行情周期处理完成", {"trade_date": trade_date, "signals": signal_count, "orders": order_count, "trades": trade_count, "ledger_difference": equity["ledger_difference"]})
            self._health("paper_runtime", "healthy", observed_at, None, "周期处理成功", {"instance_id": instance_id, "trade_date": trade_date})
            return self.get_cycle(cycle_id)
        except Exception as exc:
            self._execute("UPDATE paper_runtime_cycles SET status='failed',error_message=%s,finished_at=NOW() WHERE id=%s", (str(exc)[:1000], cycle_id))
            self._record_event(instance_id, cycle_id, "runtime", "error", "行情周期失败", {"error": str(exc)})
            self._health("paper_runtime", "critical", observed_at, "CYCLE_FAILED", str(exc)[:500], {"instance_id": instance_id, "trade_date": trade_date})
            raise

    def list_instances(self) -> List[Dict[str, Any]]:
        rows = self._rows(
            """
            SELECT i.*,p.cash_balance,p.initial_cash,p.status AS portfolio_status,
                   (SELECT COUNT(*) FROM strategy_signals s WHERE s.paper_instance_id=i.id)::INTEGER AS signal_count,
                   (SELECT COUNT(*) FROM orders o WHERE o.paper_instance_id=i.id)::INTEGER AS order_count,
                   (SELECT COUNT(*) FROM trades t WHERE t.paper_instance_id=i.id)::INTEGER AS trade_count,
                   (SELECT equity FROM paper_equity_snapshots e WHERE e.paper_instance_id=i.id ORDER BY trade_date DESC LIMIT 1) AS equity
            FROM paper_instances i JOIN portfolios p ON p.id=i.portfolio_id ORDER BY i.created_at DESC
            """
        )
        for row in rows:
            row["data_purpose"] = infer_data_purpose(row.get("name"))
        return rows

    def get_instance(self, instance_id: str) -> Dict[str, Any]:
        instance = self._instance(instance_id)
        instance["data_purpose"] = infer_data_purpose(instance.get("name"))
        instance["signals"] = self._rows("SELECT * FROM strategy_signals WHERE paper_instance_id=%s ORDER BY signal_time DESC,id DESC", (instance_id,))
        instance["orders"] = self._rows("SELECT * FROM orders WHERE paper_instance_id=%s ORDER BY created_at DESC", (instance_id,))
        instance["trades"] = self._rows("SELECT * FROM trades WHERE paper_instance_id=%s ORDER BY traded_at DESC", (instance_id,))
        instance["positions"] = self._rows("SELECT * FROM positions WHERE portfolio_id=%s ORDER BY market_value DESC", (instance["portfolio_id"],))
        instance["cash_ledger"] = self._rows("SELECT * FROM cash_ledger WHERE paper_instance_id=%s ORDER BY created_at DESC", (instance_id,))
        instance["equity_snapshots"] = self._rows("SELECT * FROM paper_equity_snapshots WHERE paper_instance_id=%s ORDER BY trade_date", (instance_id,))
        instance["events"] = self.events(instance_id)
        instance["cycles"] = self._rows("SELECT * FROM paper_runtime_cycles WHERE paper_instance_id=%s ORDER BY trade_date,id", (instance_id,))
        return instance

    def events(self, instance_id: str) -> List[Dict[str, Any]]:
        self._instance(instance_id)
        return self._rows("SELECT * FROM paper_instance_events WHERE paper_instance_id=%s ORDER BY occurred_at DESC,id DESC", (instance_id,))

    def get_cycle(self, cycle_id: str) -> Dict[str, Any]:
        row = self._row("SELECT * FROM paper_runtime_cycles WHERE id=%s", (cycle_id,))
        if not row:
            raise ValueError("Paper 周期不存在")
        return row

    def list_alerts(self, status: Optional[str] = "active", limit: int = 200) -> List[Dict[str, Any]]:
        if status:
            return self._rows("SELECT * FROM alerts WHERE status=%s ORDER BY triggered_at DESC LIMIT %s", (status, max(1, min(limit, 500))))
        return self._rows("SELECT * FROM alerts ORDER BY triggered_at DESC LIMIT %s", (max(1, min(limit, 500)),))

    def acknowledge_alert(self, alert_id: str, actor: str = "admin") -> Dict[str, Any]:
        row = self._row("SELECT * FROM alerts WHERE id=%s", (alert_id,))
        if not row:
            raise ValueError("告警不存在")
        if row["status"] == "acknowledged":
            return {**row, "reused": True}
        self._execute("UPDATE alerts SET status='acknowledged',acknowledged_at=NOW(),acknowledged_by=%s WHERE id=%s", (actor, alert_id))
        self._execute("UPDATE notification_deliveries SET status='acknowledged',acknowledged_at=NOW() WHERE alert_id=%s AND status='delivered'", (alert_id,))
        return self._row("SELECT * FROM alerts WHERE id=%s", (alert_id,)) or {}

    def watch_context(self) -> Dict[str, Any]:
        alerts = self.list_alerts(None)
        signals = self._rows("SELECT * FROM strategy_signals WHERE paper_instance_id IS NOT NULL ORDER BY signal_time DESC LIMIT 200")
        orders = self._rows(
            """
            SELECT o.*,i.name AS instance_name
            FROM orders o JOIN paper_instances i ON i.id=o.paper_instance_id
            WHERE o.paper_instance_id IS NOT NULL
            ORDER BY o.created_at DESC,o.id DESC LIMIT 200
            """
        )
        trades = self._rows(
            """
            SELECT t.*,i.name AS instance_name
            FROM trades t JOIN paper_instances i ON i.id=t.paper_instance_id
            WHERE t.paper_instance_id IS NOT NULL
            ORDER BY t.traded_at DESC,t.id DESC LIMIT 200
            """
        )
        positions = self._rows(
            """
            SELECT p.*,i.id AS paper_instance_id,i.name AS instance_name
            FROM positions p JOIN paper_instances i ON i.portfolio_id=p.portfolio_id
            ORDER BY ABS(p.market_value) DESC,p.updated_at DESC,p.id DESC LIMIT 200
            """
        )
        risk_events = self._rows(
            """
            SELECT e.*,r.name AS rule_name,r.rule_type,i.name AS instance_name
            FROM risk_events e
            JOIN paper_instances i ON i.id=e.paper_instance_id
            LEFT JOIN risk_rules r ON r.id=e.rule_id
            WHERE e.paper_instance_id IS NOT NULL
            ORDER BY e.created_at DESC,e.id DESC LIMIT 200
            """
        )
        runtime_events = self._rows(
            """
            SELECT e.*,i.name AS instance_name
            FROM paper_instance_events e JOIN paper_instances i ON i.id=e.paper_instance_id
            ORDER BY e.occurred_at DESC,e.id DESC LIMIT 200
            """
        )
        pool_moves = self._rows(
                """
                SELECT s.id AS snapshot_id,s.pool_id,p.name AS pool_name,s.trade_date,s.member_count,s.manifest_hash
                FROM stock_pool_snapshots s JOIN stock_pools p ON p.id=s.pool_id
                WHERE s.status='sealed' ORDER BY s.trade_date DESC,s.id DESC LIMIT 100
                """
            )
        instances = self.list_instances()
        candidates = [
            *(item.get("triggered_at") for item in alerts),
            *(item.get("signal_time") for item in signals),
            *(item.get("updated_at") or item.get("created_at") for item in orders),
            *(item.get("traded_at") for item in trades),
            *(item.get("updated_at") for item in positions),
            *(item.get("created_at") for item in risk_events),
            *(item.get("occurred_at") for item in runtime_events),
            *(item.get("trade_date") for item in pool_moves),
            *(item.get("heartbeat_at") or item.get("updated_at") for item in instances),
        ]
        timestamps = [self._timestamp(value) for value in candidates if value]
        source_updated_at = max(timestamps) if timestamps else None
        now = datetime.now(timezone.utc)
        if source_updated_at is None:
            data_status = "empty"
        elif (now - source_updated_at).total_seconds() > 36 * 60 * 60:
            data_status = "stale"
        else:
            data_status = "fresh"
        return {
            "alerts": alerts,
            "signals": signals,
            "orders": orders,
            "trades": trades,
            "positions": positions,
            "risk_events": risk_events,
            "runtime_events": runtime_events,
            "pool_moves": pool_moves,
            "instances": instances,
            "coverage": {
                "instances": len(instances),
                "signals": len(signals),
                "orders": len(orders),
                "trades": len(trades),
                "positions": len(positions),
                "risk_events": len(risk_events),
                "runtime_events": len(runtime_events),
            },
            "data_status": data_status,
            "source_label": "PostgreSQL Paper audit evidence",
            "source_updated_at": source_updated_at,
            "response_generated_at": now,
        }

    def health(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        services = self._rows(
            """
            SELECT DISTINCT ON(service_code) * FROM service_health_snapshots
            ORDER BY service_code,observed_at DESC,id DESC
            """
        )
        for item in services:
            observed_at = self._timestamp(item["observed_at"]) if item.get("observed_at") else None
            item["freshness"] = (
                "missing"
                if observed_at is None
                else "stale"
                if (now - observed_at).total_seconds() > 36 * 60 * 60
                else "fresh"
            )
        active_alerts = self._rows("SELECT severity,COUNT(*)::INTEGER AS count FROM alerts WHERE status='active' GROUP BY severity ORDER BY severity")
        active_alert_details = self._rows(
            """
            SELECT a.*,i.name AS instance_name
            FROM alerts a LEFT JOIN paper_instances i ON i.id=a.paper_instance_id
            WHERE a.status='active'
            ORDER BY CASE a.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                     a.triggered_at DESC LIMIT 200
            """
        )
        data = self._row("SELECT id,status,knowledge_cutoff_at,manifest_hash FROM dataset_snapshots WHERE status='sealed' ORDER BY id DESC LIMIT 1")
        market = self._row("SELECT id,status,trade_date,available_at,content_hash FROM market_evidence_snapshots ORDER BY trade_date DESC,id DESC LIMIT 1")
        instances = self._rows("SELECT status,COUNT(*)::INTEGER AS count FROM paper_instances GROUP BY status ORDER BY status")
        strategy_health = self._rows(
            """
            SELECT i.id,i.name,i.status,i.runtime_version,i.heartbeat_at,i.last_processed_trade_date,
                   i.error_message,i.updated_at,i.feed_config,p.cash_balance,p.initial_cash,
                   c.id AS latest_cycle_id,c.status AS latest_cycle_status,c.trade_date AS latest_cycle_trade_date,
                   c.finished_at AS latest_cycle_finished_at,c.error_message AS latest_cycle_error,
                   c.ledger_difference AS latest_cycle_ledger_difference,
                   e.equity AS latest_equity,e.nav AS latest_nav,e.drawdown AS latest_drawdown,
                   e.trade_date AS latest_equity_trade_date,e.created_at AS latest_equity_at,
                   (SELECT COUNT(*) FROM orders o WHERE o.paper_instance_id=i.id)::INTEGER AS order_count,
                   (SELECT COUNT(*) FROM trades t WHERE t.paper_instance_id=i.id)::INTEGER AS trade_count,
                   (SELECT COUNT(*) FROM risk_events r WHERE r.paper_instance_id=i.id)::INTEGER AS risk_event_count,
                   (SELECT COUNT(*) FROM risk_events r WHERE r.paper_instance_id=i.id AND r.decision='rejected')::INTEGER AS rejected_count
            FROM paper_instances i
            JOIN portfolios p ON p.id=i.portfolio_id
            LEFT JOIN LATERAL (
                SELECT * FROM paper_runtime_cycles pc
                WHERE pc.paper_instance_id=i.id
                ORDER BY pc.created_at DESC,pc.id DESC LIMIT 1
            ) c ON TRUE
            LEFT JOIN LATERAL (
                SELECT * FROM paper_equity_snapshots pe
                WHERE pe.paper_instance_id=i.id
                ORDER BY pe.trade_date DESC,pe.id DESC LIMIT 1
            ) e ON TRUE
            ORDER BY CASE i.status WHEN 'running' THEN 0 WHEN 'failed' THEN 1 WHEN 'paused' THEN 2 ELSE 3 END,
                     i.updated_at DESC
            """
        )
        for item in strategy_health:
            item["data_purpose"] = infer_data_purpose(item.get("name"))
            heartbeat = self._timestamp(item["heartbeat_at"]) if item.get("heartbeat_at") else None
            item["heartbeat_age_seconds"] = int((now - heartbeat).total_seconds()) if heartbeat else None
            if item["status"] in {"stopped", "draft"}:
                item["health_state"] = item["status"]
            elif item["status"] == "failed" or item.get("latest_cycle_status") == "failed":
                item["health_state"] = "failed"
            elif heartbeat is None:
                item["health_state"] = "missing"
            elif (now - heartbeat).total_seconds() > 36 * 60 * 60:
                item["health_state"] = "stale"
            else:
                item["health_state"] = "fresh"
        notification = self._rows("SELECT status,COUNT(*)::INTEGER AS count FROM notification_deliveries GROUP BY status ORDER BY status")
        source_candidates = [
            *(item.get("observed_at") for item in services),
            *(item.get("triggered_at") for item in active_alert_details),
            *(item.get("heartbeat_at") or item.get("latest_cycle_finished_at") or item.get("updated_at") for item in strategy_health),
            data.get("knowledge_cutoff_at") if data else None,
            market.get("available_at") if market else None,
        ]
        source_timestamps = [self._timestamp(value) for value in source_candidates if value]
        source_updated_at = max(source_timestamps) if source_timestamps else None
        running_health_failure = any(
            item["status"] in {"running", "starting"} and item["health_state"] in {"missing", "stale", "failed"}
            for item in strategy_health
        )
        current_critical_service = any(
            item["status"] == "critical" and item["freshness"] == "fresh" for item in services
        )
        stale_service_evidence = any(item["freshness"] != "fresh" for item in services)
        overall = (
            "unavailable"
            if not services and not strategy_health
            else "critical"
            if current_critical_service or running_health_failure
            else "warning"
            if active_alerts or stale_service_evidence
            else "healthy"
        )
        return {
            "status": overall,
            "services": services,
            "data": {"dataset": data, "market": market},
            "strategy_instances": instances,
            "strategy_health": strategy_health,
            "risk_alerts": active_alerts,
            "active_alerts": active_alert_details,
            "notifications": notification,
            "source_label": "PostgreSQL runtime and health evidence",
            "source_updated_at": source_updated_at,
            "response_generated_at": now,
        }

    def recover_instances(self) -> Dict[str, Any]:
        running = self._rows("SELECT id,status,last_processed_trade_date,last_cycle_key FROM paper_instances WHERE status IN ('running','paused') ORDER BY created_at")
        interrupted: List[Dict[str, Any]] = []
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE paper_runtime_cycles
                    SET status='failed',error_message='recovered_after_restart',finished_at=NOW()
                    WHERE status='running'
                    RETURNING id,paper_instance_id
                    """
                )
                interrupted = [dict(item) for item in cursor.fetchall()]
                by_instance = {str(item["id"]): item for item in running}
                for instance_id in sorted({str(item["paper_instance_id"]) for item in interrupted}):
                    item = by_instance.get(instance_id) or {}
                    self._event_cursor(
                        cursor,
                        instance_id,
                        None,
                        "recovery",
                        "warning",
                        "检测到中断周期，已标记失败；已完成周期不会重放",
                        {
                            "last_processed_trade_date": str(item.get("last_processed_trade_date") or ""),
                            "last_cycle_key": item.get("last_cycle_key"),
                            "interrupted_cycle_ids": [str(cycle["id"]) for cycle in interrupted if str(cycle["paper_instance_id"]) == instance_id],
                        },
                    )
        return {"restored": len(running), "interrupted_cycles": len(interrupted), "instances": running}

    def _execute_pending_signals(
        self,
        instance: Mapping[str, Any],
        cycle_id: str,
        trade_date: str,
        bars: Mapping[str, Mapping[str, Any]],
        available_at: datetime,
        *,
        allow_new_entries: bool = True,
    ) -> Tuple[int, int]:
        self._execute(
            """
            UPDATE positions p SET available_quantity=GREATEST(0,p.quantity-COALESCE((
                SELECT SUM(t.quantity) FROM trades t
                WHERE t.portfolio_id=p.portfolio_id AND t.symbol=p.symbol AND t.side='buy'
                  AND t.traded_at::date >= %s
            ),0)),updated_at=NOW()
            WHERE p.portfolio_id=%s
            """,
            (trade_date, instance["portfolio_id"]),
        )
        signals = self._rows(
            "SELECT * FROM strategy_signals WHERE paper_instance_id=%s AND status='new' AND signal_time::date<%s ORDER BY signal_time,id",
            (instance["id"], trade_date),
        )
        orders = trades = 0
        for signal in signals:
            bar = bars.get(str(signal["symbol"]))
            if not bar:
                continue
            created, filled = self._execute_signal(
                instance, cycle_id, signal, bar, trade_date, available_at, allow_new_entries=allow_new_entries
            )
            orders += int(created)
            trades += int(filled)
        return orders, trades

    def _execute_signal(
        self,
        instance: Mapping[str, Any],
        cycle_id: str,
        signal: Mapping[str, Any],
        bar: Mapping[str, Any],
        trade_date: str,
        available_at: datetime,
        *,
        allow_new_entries: bool = True,
    ) -> Tuple[bool, bool]:
        existing = self._row("SELECT id,status FROM orders WHERE paper_instance_id=%s AND signal_id=%s", (instance["id"], signal["id"]))
        if existing:
            return False, existing["status"] == "filled"
        position = self._row("SELECT * FROM positions WHERE portfolio_id=%s AND symbol=%s", (instance["portfolio_id"], signal["symbol"])) or {"quantity": 0, "available_quantity": 0, "avg_cost": 0}
        portfolio = self._row("SELECT * FROM portfolios WHERE id=%s", (instance["portfolio_id"],)) or {}
        latest_equity = self._row("SELECT equity,drawdown FROM paper_equity_snapshots WHERE paper_instance_id=%s ORDER BY trade_date DESC LIMIT 1", (instance["id"],))
        equity = float((latest_equity or {}).get("equity") or portfolio.get("initial_cash") or 0)
        price = float(bar.get("open") or bar.get("close") or 0)
        target_pct = max(0.0, min(float((signal.get("payload") or {}).get("value") or 0), 1.0))
        target_quantity = int((equity * target_pct / price) // 100 * 100) if price > 0 else 0
        current_quantity = int(position.get("quantity") or 0)
        delta = target_quantity - current_quantity
        if delta == 0:
            self._execute("UPDATE strategy_signals SET status='closed',updated_at=NOW() WHERE id=%s", (signal["id"],))
            return False, False
        side = "buy" if delta > 0 else "sell"
        if side == "buy" and not allow_new_entries:
            return False, False
        quantity = abs(delta) if side == "buy" else min(abs(delta), int(position.get("available_quantity") or 0))
        quantity = int(quantity // 100 * 100)
        if quantity <= 0:
            self._execute("UPDATE strategy_signals SET status='invalidated',updated_at=NOW() WHERE id=%s", (signal["id"],))
            return False, False
        earliest_fill_at = datetime.fromisoformat(f"{trade_date}T09:30:00+08:00")
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO orders(portfolio_id,paper_instance_id,signal_id,symbol,side,order_type,price,quantity,status,
                                       signal_time,data_available_at,earliest_fill_at,message)
                    VALUES (%s,%s,%s,%s,%s,'market',%s,%s,'pending',%s,%s,%s,'等待风险决策')
                    ON CONFLICT DO NOTHING RETURNING id
                    """,
                    (instance["portfolio_id"], instance["id"], signal["id"], signal["symbol"], side, price, quantity, signal["signal_time"], signal.get("data_available_at") or signal["signal_time"], earliest_fill_at),
                )
                row = cursor.fetchone()
                if not row:
                    return False, False
                order_id = str(row["id"])
        accepted, risk_event_id, reason = self._risk_decision(instance, order_id, signal, side, quantity, price, bar, portfolio, latest_equity)
        if not accepted:
            self._execute("UPDATE orders SET status='rejected',risk_event_id=%s,message=%s,updated_at=NOW() WHERE id=%s", (risk_event_id, reason, order_id))
            self._execute("UPDATE strategy_signals SET status='invalidated',updated_at=NOW() WHERE id=%s", (signal["id"],))
            self._alert("risk_rejection", str(instance["id"]), "risk", "warning", "Paper 风控拒单", reason, "order", order_id, {"signal_id": str(signal["id"]), "cycle_id": cycle_id}, f"risk:{order_id}")
            return True, False
        amount = price * quantity
        commission = max(amount * 0.0003, 5.0)
        cash = float(portfolio.get("cash_balance") or 0)
        if side == "buy":
            new_cash = cash - amount - commission
            new_quantity = current_quantity + quantity
            avg_cost = ((current_quantity * float(position.get("avg_cost") or 0)) + amount + commission) / new_quantity
            available_quantity = int(position.get("available_quantity") or 0)
            ledger_amount = -(amount + commission)
        else:
            new_cash = cash + amount - commission
            new_quantity = current_quantity - quantity
            avg_cost = float(position.get("avg_cost") or 0) if new_quantity else 0
            available_quantity = max(0, int(position.get("available_quantity") or 0) - quantity)
            ledger_amount = amount - commission
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("UPDATE portfolios SET cash_balance=%s,updated_at=NOW() WHERE id=%s", (new_cash, instance["portfolio_id"]))
                cursor.execute(
                    """
                    INSERT INTO positions(portfolio_id,symbol,quantity,available_quantity,avg_cost,last_price,market_value)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(portfolio_id,symbol) DO UPDATE SET quantity=EXCLUDED.quantity,available_quantity=EXCLUDED.available_quantity,
                        avg_cost=EXCLUDED.avg_cost,last_price=EXCLUDED.last_price,market_value=EXCLUDED.market_value,updated_at=NOW()
                    """,
                    (instance["portfolio_id"], signal["symbol"], new_quantity, available_quantity, avg_cost, price, new_quantity * price),
                )
                cursor.execute(
                    """
                    INSERT INTO trades(portfolio_id,paper_instance_id,order_id,symbol,side,price,quantity,amount,commission,
                                       signal_time,data_available_at,earliest_fill_at,traded_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING RETURNING id
                    """,
                    (instance["portfolio_id"], instance["id"], order_id, signal["symbol"], side, price, quantity, amount, commission, signal["signal_time"], signal.get("data_available_at") or signal["signal_time"], earliest_fill_at, earliest_fill_at),
                )
                trade = cursor.fetchone()
                if not trade:
                    return True, False
                trade_id = str(trade["id"])
                cursor.execute(
                    "INSERT INTO cash_ledger(portfolio_id,paper_instance_id,event_type,amount,balance_after,ref_type,ref_id,note) VALUES (%s,%s,%s,%s,%s,'order',%s,%s) ON CONFLICT DO NOTHING",
                    (instance["portfolio_id"], instance["id"], side, ledger_amount, new_cash, order_id, f"Paper {side} 含费用 {commission:.2f}"),
                )
                cursor.execute("UPDATE orders SET status='filled',filled_quantity=%s,risk_event_id=%s,filled_at=%s,message='模拟成交',updated_at=NOW() WHERE id=%s", (quantity, risk_event_id, earliest_fill_at, order_id))
                cursor.execute("UPDATE strategy_signals SET status='ordered',updated_at=NOW() WHERE id=%s", (signal["id"],))
                self._event_cursor(cursor, str(instance["id"]), cycle_id, "broker", "info", "Paper 订单已模拟成交", {"order_id": order_id, "trade_id": trade_id, "symbol": signal["symbol"], "side": side, "quantity": quantity, "price": price})
        return True, True

    def _risk_decision(self, instance: Mapping[str, Any], order_id: str, signal: Mapping[str, Any], side: str, quantity: int, price: float, bar: Mapping[str, Any], portfolio: Mapping[str, Any], latest_equity: Optional[Mapping[str, Any]]) -> Tuple[bool, str, str]:
        limits = dict(instance.get("capacity_limits") or {})
        cash = float(portfolio.get("cash_balance") or 0)
        initial = float(portfolio.get("initial_cash") or 1)
        equity = float((latest_equity or {}).get("equity") or initial)
        amount = quantity * price
        volume = float(bar.get("volume") or 0)
        checks = self.risk_checks(limits, side, quantity, price, volume, cash, initial, equity, float((latest_equity or {}).get("drawdown") or 0))
        last_event_id = ""
        for rule_type, passed, message in checks:
            rule = self._row("SELECT * FROM risk_rules WHERE rule_type=%s AND enabled=TRUE ORDER BY rule_version DESC LIMIT 1", (rule_type,))
            if not rule:
                continue
            decision = "accepted" if passed else "rejected"
            with self.database.get_connection() as connection:
                with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO risk_events(portfolio_id,paper_instance_id,order_id,signal_id,rule_id,rule_version,severity,
                                                decision,message,payload,input_payload)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT DO NOTHING RETURNING id
                        """,
                        (instance["portfolio_id"], instance["id"], order_id, signal["id"], rule["id"], rule["rule_version"], "info" if passed else "block", decision, "通过" if passed else message, psycopg2.extras.Json({"rule_type": rule_type, "content_hash": rule.get("content_hash")}), psycopg2.extras.Json({"side": side, "quantity": quantity, "price": price, "bar_volume": volume, "limits": limits})),
                    )
                    row = cursor.fetchone()
                    if row:
                        last_event_id = str(row["id"])
                    else:
                        cursor.execute(
                            "SELECT id FROM risk_events WHERE paper_instance_id=%s AND order_id=%s AND rule_id=%s",
                            (instance["id"], order_id, rule["id"]),
                        )
                        existing = cursor.fetchone()
                        if existing:
                            last_event_id = str(existing["id"])
            if not passed:
                return False, last_event_id, message
        return True, last_event_id, "全部风险规则通过"

    @staticmethod
    def risk_checks(
        limits: Mapping[str, Any],
        side: str,
        quantity: int,
        price: float,
        volume: float,
        cash: float,
        initial: float,
        equity: float,
        drawdown: float,
    ) -> List[Tuple[str, bool, str]]:
        def limit(name: str, default: float) -> float:
            value = limits.get(name)
            return default if value is None else float(value)

        amount = quantity * price
        return [
            ("single_symbol_weight", side != "buy" or amount / max(equity, 1) <= limit("max_single_symbol_weight", 1), "目标单票权重超过上限"),
            ("participation", side != "buy" or (volume > 0 and quantity / volume <= limit("max_participation_ratio", 0.1)), "参与率超过上限"),
            ("cash_floor", side != "buy" or cash - amount >= initial * limit("cash_floor_ratio", 0.05), "成交后现金低于安全底线"),
            ("drawdown", drawdown <= limit("max_drawdown", 0.2), "账户回撤超过上限"),
            ("daily_turnover", amount / max(equity, 1) <= limit("max_daily_turnover", 2), "单周期换手预算超限"),
        ]

    def _persist_signals(self, instance: Mapping[str, Any], cycle_id: str, intents: Sequence[Mapping[str, Any]]) -> int:
        inserted = 0
        for intent in intents:
            payload = dict(intent.get("payload") or {})
            value = float(payload.get("value") or 0)
            signal_type = "buy" if value > 0 else "sell"
            signal_key = canonical_hash({"instance_id": str(instance["id"]), "simulated_at": str(intent["simulated_at"]), "symbol": intent["symbol"], "intent_type": intent["intent_type"], "payload_hash": intent["payload_hash"]})
            with self.database.get_connection() as connection:
                with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO strategy_signals(strategy_version_id,paper_instance_id,signal_key,symbol,signal_type,status,
                                                     signal_time,data_available_at,strength,reason,payload)
                        VALUES (%s,%s,%s,%s,%s,'new',%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id
                        """,
                        (instance["strategy_version_id"], instance["id"], signal_key, intent["symbol"], signal_type, intent["simulated_at"], intent["available_at"], abs(value), f"{intent['intent_type']}={value}", psycopg2.extras.Json(payload)),
                    )
                    row = cursor.fetchone()
                    if row:
                        inserted += 1
                        signal_id = str(row["id"])
                        self._event_cursor(cursor, str(instance["id"]), cycle_id, "strategy", "info", "策略信号已持久化，最早下一交易日执行", {"signal_id": signal_id, "symbol": intent["symbol"], "signal_time": str(intent["simulated_at"])})
                        self._alert_cursor(cursor, "strategy_signal", str(instance["id"]), "signal", "info", "新的 Paper 策略信号", f"{intent['symbol']} {intent['intent_type']}={value}", "strategy_signal", signal_id, {"cycle_id": cycle_id}, f"signal:{signal_id}")
        return inserted

    def _persist_equity(self, instance: Mapping[str, Any], cycle_id: str, trade_date: str, bars: Mapping[str, Mapping[str, Any]]) -> Dict[str, float]:
        positions = self._rows("SELECT * FROM positions WHERE portfolio_id=%s", (instance["portfolio_id"],))
        market_value = 0.0
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                for position in positions:
                    price = float((bars.get(str(position["symbol"])) or {}).get("close") or position.get("last_price") or 0)
                    value = int(position["quantity"]) * price
                    market_value += value
                    cursor.execute("UPDATE positions SET last_price=%s,market_value=%s,updated_at=NOW() WHERE id=%s", (price, value, position["id"]))
        portfolio = self._row("SELECT * FROM portfolios WHERE id=%s", (instance["portfolio_id"],)) or {}
        cash = float(portfolio.get("cash_balance") or 0)
        equity = cash + market_value
        initial = float(portfolio.get("initial_cash") or 1)
        peak = self._row("SELECT MAX(equity) AS peak FROM paper_equity_snapshots WHERE paper_instance_id=%s", (instance["id"],))
        peak_equity = max(equity, float((peak or {}).get("peak") or initial))
        drawdown = 1 - equity / peak_equity if peak_equity else 0
        ledger = self._row("SELECT COALESCE(SUM(amount),0) AS total FROM cash_ledger WHERE paper_instance_id=%s", (instance["id"],))
        expected_cash = float((ledger or {}).get("total") or 0)
        ledger_difference = cash - expected_cash
        self._execute(
            """
            INSERT INTO paper_equity_snapshots(paper_instance_id,cycle_id,trade_date,cash,market_value,equity,gross_exposure,nav,drawdown,ledger_difference)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(paper_instance_id,trade_date) DO UPDATE SET cash=EXCLUDED.cash,market_value=EXCLUDED.market_value,
                equity=EXCLUDED.equity,gross_exposure=EXCLUDED.gross_exposure,nav=EXCLUDED.nav,drawdown=EXCLUDED.drawdown,
                ledger_difference=EXCLUDED.ledger_difference
            """,
            (instance["id"], cycle_id, trade_date, cash, market_value, equity, market_value / equity if equity else 0, equity / initial, drawdown, ledger_difference),
        )
        return {"cash": cash, "market_value": market_value, "equity": equity, "ledger_difference": ledger_difference}

    def _open_cycle(self, instance_id: str, cycle_key: str, trade_date: str, data_at: datetime, observed_at: datetime, input_hash: str) -> Tuple[str, bool]:
        existing = self._row("SELECT * FROM paper_runtime_cycles WHERE paper_instance_id=%s AND cycle_key=%s", (instance_id, cycle_key))
        if existing and str(existing["input_hash"]) != input_hash:
            raise ValueError("相同 cycle_key 的输入清单发生变化，拒绝覆盖已记录周期")
        if existing and existing["status"] in {"success", "blocked"}:
            return str(existing["id"]), True
        if existing:
            self._execute("UPDATE paper_runtime_cycles SET status='running',error_message=NULL,finished_at=NULL WHERE id=%s", (existing["id"],))
            return str(existing["id"]), False
        row = self._row(
            """
            INSERT INTO paper_runtime_cycles(paper_instance_id,cycle_key,trade_date,data_available_at,observed_at,input_hash,status)
            VALUES (%s,%s,%s,%s,%s,%s,'running') RETURNING id
            """,
            (instance_id, cycle_key, trade_date, data_at, observed_at, input_hash),
        )
        return str(row["id"]), False

    def _finish_cycle(self, cycle_id: str, status: str, signals: int, orders: int, trades: int, difference: float) -> None:
        self._execute("UPDATE paper_runtime_cycles SET status=%s,signal_count=%s,order_count=%s,trade_count=%s,ledger_difference=%s,finished_at=NOW() WHERE id=%s", (status, signals, orders, trades, difference, cycle_id))

    def _state(self, instance: Mapping[str, Any], status: str, event_type: str, message: str) -> None:
        portfolio_status = "active" if status == "running" else "paused"
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE paper_instances SET status=%s,heartbeat_at=NOW(),updated_at=NOW() WHERE id=%s", (status, instance["id"]))
                cursor.execute("UPDATE portfolios SET status=%s,updated_at=NOW() WHERE id=%s", (portfolio_status, instance["portfolio_id"]))
                self._event_cursor(cursor, str(instance["id"]), None, event_type, "info", message, {})

    def _instance(self, instance_id: str) -> Dict[str, Any]:
        row = self._row("SELECT i.*,p.cash_balance,p.initial_cash,p.status AS portfolio_status FROM paper_instances i JOIN portfolios p ON p.id=i.portfolio_id WHERE i.id=%s", (str(instance_id),))
        if not row:
            raise ValueError("Paper 实例不存在")
        return row

    def _record_event(self, instance_id: str, cycle_id: Optional[str], event_type: str, level: str, message: str, payload: Mapping[str, Any]) -> None:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                self._event_cursor(cursor, instance_id, cycle_id, event_type, level, message, payload)

    @staticmethod
    def _event_cursor(cursor, instance_id: str, cycle_id: Optional[str], event_type: str, level: str, message: str, payload: Mapping[str, Any]) -> None:
        cursor.execute("INSERT INTO paper_instance_events(paper_instance_id,cycle_id,event_type,level,message,payload) VALUES (%s,%s,%s,%s,%s,%s)", (instance_id, cycle_id, event_type, level, message, psycopg2.extras.Json(dict(payload))))

    def _alert(self, code: str, instance_id: str, category: str, severity: str, title: str, message: str, source_type: str, source_id: str, evidence: Mapping[str, Any], dedupe_key: str) -> None:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                self._alert_cursor(cursor, code, instance_id, category, severity, title, message, source_type, source_id, evidence, dedupe_key)

    @staticmethod
    def _alert_cursor(cursor, code: str, instance_id: str, category: str, severity: str, title: str, message: str, source_type: str, source_id: str, evidence: Mapping[str, Any], dedupe_key: str) -> None:
        cursor.execute("SELECT id FROM alert_rules WHERE code=%s AND enabled=TRUE ORDER BY rule_version DESC LIMIT 1", (code,))
        rule = cursor.fetchone()
        cursor.execute(
            """
            INSERT INTO alerts(alert_rule_id,paper_instance_id,category,severity,title,message,source_object_type,source_object_id,evidence,dedupe_key)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(dedupe_key) DO NOTHING RETURNING id
            """,
            ((rule.get("id") if isinstance(rule, Mapping) else rule[0]) if rule else None, instance_id, category, severity, title, message, source_type, source_id, psycopg2.extras.Json(dict(evidence)), dedupe_key),
        )
        created = cursor.fetchone()
        if created:
            alert_id = created.get("id") if isinstance(created, Mapping) else created[0]
            cursor.execute("INSERT INTO notification_deliveries(alert_id,channel,status,delivered_at) VALUES (%s,'in_app','delivered',NOW())", (alert_id,))

    def _health(self, service_code: str, status: str, observed_at: datetime, error_code: Optional[str], message: str, payload: Mapping[str, Any]) -> None:
        self._execute("INSERT INTO service_health_snapshots(service_code,status,last_success_at,error_code,message,payload,observed_at) VALUES (%s,%s,%s,%s,%s,%s,%s)", (service_code, status, observed_at if status == "healthy" else None, error_code, message, psycopg2.extras.Json(dict(payload)), observed_at))

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _row(self, query: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
                return dict(row) if row else None

    def _rows(self, query: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    def _execute(self, query: str, params: Sequence[Any] = ()) -> None:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
