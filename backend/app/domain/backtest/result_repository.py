"""Atomic PostgreSQL persistence for complete A-share backtest evidence."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable
import uuid

import psycopg2
import psycopg2.extras

from app.core.config import settings


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _insert(cursor, sql: str, rows: list[tuple]) -> None:
    if rows:
        psycopg2.extras.execute_values(cursor, sql, rows, page_size=50)


class PostgresBacktestResultRepository:
    def __init__(self, database_url: str | None = None, *, connection_factory: Callable[..., object] = psycopg2.connect) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for backtest result persistence")
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=False, autocommit=False)
        return connection

    def persist(self, request: dict, bundle: dict, replay: dict, result: dict) -> dict:
        strategy = bundle["strategy_version"]
        snapshot = bundle["dataset_snapshot"]
        pool = bundle["pool_snapshot"]
        metrics_map = {item["metric_code"]: item.get("metric_value") for item in result["metrics"]}
        manifest = {
            "calculation_version": "backtest.v1",
            "broker_calculation_version": "ashare-broker.v1",
            "metrics_calculation_version": "backtest-metrics.v1",
            "strategy_input_hash": replay.get("input_hash"),
            "event_hash": replay.get("event_hash"),
            "dataset_manifest_hash": snapshot.get("manifest_hash"),
            "pool_manifest_hash": pool.get("manifest_hash"),
            "quality_warnings": list(result.get("quality_warnings") or []),
            "capacity_warning_count": int(result.get("capacity_warning_count") or 0),
            "record_count": len(replay.get("records") or []),
            "intent_count": len(replay.get("intents") or []),
            "order_count": len(result.get("orders") or []),
            "trade_count": len(result.get("trades") or []),
            "equity_count": len(result.get("daily_equity") or []),
            "attribution_hash": _hash(result.get("attribution") or []),
        }
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO backtest_runs
                    (strategy_version_id,name,universe,parameters,start_date,end_date,status,metrics,
                     started_at,finished_at,dataset_snapshot_id,pool_snapshot_id,universe_manifest,
                     knowledge_cutoff_at,benchmark_code,strategy_api_version,input_hash,run_mode,
                     progress,promotion_status,initial_cash,frequency,calculation_version,result_manifest,sealed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,'running','{}'::jsonb,NOW(),NULL,%s,%s,%s,%s,'000300.SH',
                            'stockpro.v1',%s,'full',80,'not_evaluated',%s,'1d','backtest.v1','{}'::jsonb,NULL)
                    RETURNING id
                    """,
                    (
                        strategy["id"], strategy["name"],
                        psycopg2.extras.Json({"symbols": bundle["symbols"], "pool_snapshot_id": pool["id"]}),
                        psycopg2.extras.Json({"request": request, "cost_model": bundle["cost_model"]}),
                        bundle["start_date"], bundle["end_date"],
                        snapshot["id"], pool["id"], psycopg2.extras.Json({"pool_manifest_hash": pool.get("manifest_hash"), "symbols": bundle["symbols"]}),
                        snapshot.get("knowledge_cutoff_at"), replay.get("input_hash"), bundle["initial_cash"],
                    ),
                )
                run_id = str(cursor.fetchone()["id"])
                _insert(cursor, """
                    INSERT INTO backtest_orders
                    (id,backtest_run_id,replay_intent_id,event_ordinal,symbol,intent_type,side,requested_value,
                     requested_quantity,filled_quantity,status,signal_at,data_available_at,submitted_at,
                     earliest_fill_at,filled_at,execution_price,execution_price_source,rejection_code,
                     rejection_reason,capacity_ratio,intent_payload) VALUES %s
                """, [(
                    row["id"], run_id, row.get("replay_intent_id"), row["event_ordinal"], row["symbol"], row["intent_type"], row.get("side"), row.get("requested_value"),
                    row.get("requested_quantity"), row.get("filled_quantity") or 0, row["status"], row["signal_at"], row["data_available_at"], row.get("submitted_at"),
                    row["earliest_fill_at"], row.get("filled_at"), row.get("execution_price"), row.get("execution_price_source"), row.get("rejection_code"),
                    row.get("rejection_reason"), row.get("capacity_ratio"), psycopg2.extras.Json(row.get("intent_payload") or {}),
                ) for row in result["orders"]])
                _insert(cursor, """
                    INSERT INTO backtest_trades
                    (id,backtest_run_id,backtest_order_id,trade_date,symbol,name,side,price,quantity,amount,
                     commission,tax,transfer_fee,slippage_cost,realized_pnl,holding_days,reason,signal_at,
                     data_available_at,submitted_at,earliest_fill_at,filled_at,execution_price_source) VALUES %s
                """, [(
                    row["id"], run_id, row.get("backtest_order_id"), row["trade_date"], row["symbol"], row.get("name"), row["side"], row["price"], row["quantity"], row["amount"],
                    row.get("commission") or 0, row.get("tax") or 0, row.get("transfer_fee") or 0, row.get("slippage_cost") or 0, row.get("realized_pnl"), row.get("holding_days"),
                    row.get("reason"), row.get("signal_at"), row.get("data_available_at"), row.get("submitted_at"), row.get("earliest_fill_at"), row.get("filled_at"), row.get("execution_price_source"),
                ) for row in result["trades"]])
                _insert(cursor, """
                    INSERT INTO backtest_daily_equity
                    (backtest_run_id,trade_date,strategy_nav,strategy_return,benchmark_nav,benchmark_return,
                     excess_nav,excess_return,equity,cash,market_value,gross_exposure,net_exposure,
                     position_count,drawdown,excess_drawdown) VALUES %s
                """, [(
                    run_id, row["trade_date"], row["strategy_nav"], row.get("strategy_return"), row.get("benchmark_nav"), row.get("benchmark_return"),
                    row.get("excess_nav"), row.get("excess_return"), row["equity"], row["cash"], row["market_value"], row["gross_exposure"], row["net_exposure"],
                    row["position_count"], row["drawdown"], row.get("excess_drawdown"),
                ) for row in result["daily_equity"]])
                _insert(cursor, """
                    INSERT INTO backtest_daily_positions
                    (backtest_run_id,trade_date,symbol,quantity,available_quantity,avg_cost,close_price,
                     market_value,weight,unrealized_pnl,industry_code) VALUES %s
                """, [(
                    run_id, row["trade_date"], row["symbol"], row["quantity"], row["available_quantity"], row["avg_cost"], row["close_price"],
                    row["market_value"], row["weight"], row["unrealized_pnl"], row.get("industry_code"),
                ) for row in result["daily_positions"]])
                _insert(cursor, """
                    INSERT INTO backtest_metrics
                    (backtest_run_id,metric_code,metric_value,unit,calculation_version,input_frequency,null_reason,metric_payload) VALUES %s
                """, [(
                    run_id, row["metric_code"], row.get("metric_value"), row["unit"], row["calculation_version"], row["input_frequency"], row.get("null_reason"), psycopg2.extras.Json(row.get("metric_payload") or {}),
                ) for row in result["metrics"]])
                _insert(cursor, """
                    INSERT INTO backtest_attribution
                    (backtest_run_id,attribution_type,attribution_key,contribution,amount,payload) VALUES %s
                """, [(
                    run_id, row["attribution_type"], row["attribution_key"], row.get("contribution"), row.get("amount"), psycopg2.extras.Json(row.get("payload") or {}),
                ) for row in result["attribution"]])
                event_times = {index: item["simulated_at"] for index, item in enumerate(replay.get("events") or [])}
                combined_logs = [
                    {**row, "source": row.get("source") or "strategy", "simulated_at": row.get("simulated_at") or event_times.get(row.get("event_ordinal"))}
                    for row in [*(replay.get("logs") or []), *(result.get("logs") or [])]
                ]
                _insert(cursor, """
                    INSERT INTO backtest_logs(backtest_run_id,simulated_at,level,source,message,payload) VALUES %s
                """, [(
                    run_id, row.get("simulated_at"), row.get("level") or "info", row.get("source") or "engine", row.get("message") or "", psycopg2.extras.Json(row.get("payload") or {}),
                ) for row in combined_logs])
                _insert(cursor, """
                    INSERT INTO backtest_custom_records
                    (backtest_run_id,event_ordinal,simulated_at,available_at,payload,payload_hash) VALUES %s
                """, [(
                    run_id, row["event_ordinal"], row["simulated_at"], row["available_at"], psycopg2.extras.Json(row.get("payload") or {}), _hash(row.get("payload") or {}),
                ) for row in (replay.get("records") or [])])
                cursor.execute(
                    """
                    UPDATE backtest_runs
                    SET status='success',metrics=%s,progress=100,result_manifest=%s,finished_at=NOW(),sealed_at=NOW()
                    WHERE id=%s AND status='running' AND sealed_at IS NULL
                    RETURNING id
                    """,
                    (psycopg2.extras.Json(metrics_map), psycopg2.extras.Json(manifest), run_id),
                )
                if not cursor.fetchone():
                    raise RuntimeError("回测结果封存状态竞争失败")
        result_id = int(uuid.UUID(run_id).hex[:8], 16) & 2147483647
        return {"run_id": run_id, "result_id": result_id}
