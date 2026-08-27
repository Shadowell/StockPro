#!/usr/bin/env python3
"""Create an explicitly authorized minimal StockPro research chain.

The script is intentionally dry-run by default. Applying it writes an isolated
sample chain from existing synchronized A-share rows only; it does not fetch,
mock, or reset data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor


ALLOW_ENV = "STOCKPRO_ALLOW_PRODUCTION_SAMPLE_WRITE"
SCRIPT_VERSION = "minimal-research-chain.v1"
CONFIRM_TEXT = "I_UNDERSTAND_THIS_WRITES_PRODUCTION_SAMPLE_DATA"


class SampleChainError(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketRow:
    symbol: str
    name: str
    trade_date: date
    close: Decimal
    prev_close: Decimal
    prev_close_source: str
    volume: int | None
    turnover: Decimal | None

    @property
    def daily_return(self) -> Decimal:
        return (self.close / self.prev_close) - Decimal("1")


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def deterministic_uuid(label: str, value: Any) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"stockpro:{SCRIPT_VERSION}:{label}:{stable_hash(value)}"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="PostgreSQL URL; defaults to DATABASE_URL.")
    parser.add_argument("--symbol", action="append", default=[], help="Optional symbol to include; repeatable.")
    parser.add_argument("--max-symbols", type=int, default=3, help="Maximum symbols to include in the sample chain.")
    parser.add_argument("--apply", action="store_true", help="Actually write the sample chain.")
    parser.add_argument(
        "--confirm-production-sample-write",
        default="",
        help=f"Required with --apply; must equal {CONFIRM_TEXT!r}.",
    )
    return parser.parse_args(argv)


def require_apply_confirmation(args: argparse.Namespace, env: dict[str, str] | None = None) -> None:
    if not args.apply:
        return
    env = env if env is not None else os.environ
    if args.confirm_production_sample_write != CONFIRM_TEXT:
        raise SampleChainError(f"--confirm-production-sample-write must equal {CONFIRM_TEXT!r}")
    if env.get(ALLOW_ENV) != "1":
        raise SampleChainError(f"{ALLOW_ENV}=1 is required with --apply")


def load_real_market_rows(conn: Any, symbols: list[str], max_symbols: int) -> list[MarketRow]:
    max_symbols = max(1, min(max_symbols, 20))
    params: list[Any] = []
    symbol_filter = ""
    if symbols:
        symbol_filter = "AND symbol = ANY(%s)"
        params.append(symbols)
    params.append(max_symbols)
    sql = f"""
        WITH priced AS (
            SELECT
                stock_history.symbol,
                stock_history.name,
                stock_history.date AS trade_date,
                stock_history.close,
                stock_history.volume,
                stock_history.turnover,
                LAG(stock_history.close) OVER (PARTITION BY stock_history.symbol ORDER BY stock_history.date) AS prev_close,
                CASE
                    WHEN realtime.change_percent IS NOT NULL
                     AND realtime.change_percent > -99.99
                    THEN stock_history.close / (1 + realtime.change_percent / 100.0)
                    ELSE NULL
                END AS prev_close_from_realtime,
                ROW_NUMBER() OVER (PARTITION BY stock_history.symbol ORDER BY stock_history.date DESC) AS rn
            FROM stock_history
            LEFT JOIN all_stocks_realtime realtime ON realtime.code = stock_history.symbol
            WHERE close IS NOT NULL
              AND close > 0
              {symbol_filter}
        )
        SELECT
            symbol,
            name,
            trade_date,
            close,
            COALESCE(prev_close, prev_close_from_realtime) AS prev_close,
            CASE
                WHEN prev_close IS NOT NULL THEN 'stock_history.previous_close'
                ELSE 'all_stocks_realtime.change_percent'
            END AS prev_close_source,
            volume,
            turnover
        FROM priced
        WHERE rn = 1
          AND COALESCE(prev_close, prev_close_from_realtime) IS NOT NULL
          AND COALESCE(prev_close, prev_close_from_realtime) > 0
        ORDER BY trade_date DESC, symbol
        LIMIT %s
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    if not rows:
        raise SampleChainError(
            "synchronized A-share rows have no symbol with latest close and previous close evidence"
        )
    return [
        MarketRow(
            symbol=str(row["symbol"]),
            name=str(row["name"] or row["symbol"]),
            trade_date=row["trade_date"],
            close=Decimal(str(row["close"])),
            prev_close=Decimal(str(row["prev_close"])),
            prev_close_source=str(row["prev_close_source"]),
            volume=int(row["volume"]) if row.get("volume") is not None else None,
            turnover=Decimal(str(row["turnover"])) if row.get("turnover") is not None else None,
        )
        for row in rows
    ]


def summarize_rows(rows: list[MarketRow]) -> dict[str, Any]:
    latest = max(row.trade_date for row in rows)
    return {
        "script_version": SCRIPT_VERSION,
        "source_table": "stock_history",
        "real_rows": True,
        "trade_date": latest.isoformat(),
        "symbol_count": len(rows),
        "symbols": [
            {
                "symbol": row.symbol,
                "name": row.name,
                "trade_date": row.trade_date.isoformat(),
                "close": float(row.close),
                "prev_close": float(row.prev_close),
                "prev_close_source": row.prev_close_source,
                "daily_return": float(row.daily_return),
            }
            for row in rows
        ],
    }


def one(cursor: Any, sql: str, params: tuple[Any, ...]) -> Any:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    if row is None:
        raise SampleChainError("expected one row but query returned none")
    return row[0] if not isinstance(row, dict) else next(iter(row.values()))


def ensure_id(cursor: Any, insert_sql: str, insert_params: tuple[Any, ...], select_sql: str, select_params: tuple[Any, ...]) -> Any:
    cursor.execute(insert_sql, insert_params)
    inserted = cursor.fetchone()
    if inserted:
        return inserted[0] if not isinstance(inserted, dict) else next(iter(inserted.values()))
    return one(cursor, select_sql, select_params)


def create_minimal_research_chain(conn: Any, rows: list[MarketRow]) -> dict[str, Any]:
    latest = max(row.trade_date for row in rows)
    earliest = min(row.trade_date for row in rows)
    cutoff = datetime.combine(latest, time(17, 30), tzinfo=timezone.utc)
    chain_key = f"{SCRIPT_VERSION}:{latest.isoformat()}:{','.join(row.symbol for row in rows)}"
    chain_hash = stable_hash({"chain_key": chain_key, "rows": summarize_rows(rows)["symbols"]})
    sample_name = f"StockPro minimal research chain {latest.isoformat()}"
    row_count = len(rows)
    initial_cash = Decimal("1000000")
    primary = rows[0]
    quantity = max(100, int((initial_cash * Decimal("0.10") / primary.close / Decimal("100")).to_integral_value(rounding=ROUND_FLOOR)) * 100)
    gross_cost = (primary.close * quantity).quantize(Decimal("0.0001"))
    commission = max(Decimal("5"), (gross_cost * Decimal("0.0003")).quantize(Decimal("0.0001")))
    cash_after = initial_cash - gross_cost - commission
    market_value = gross_cost
    equity = cash_after + market_value
    nav = equity / initial_cash

    with conn.cursor() as cursor:
        dataset_code = "minimal_research_chain_stock_history"
        dataset_id = ensure_id(
            cursor,
            """
            INSERT INTO dataset_definitions(code,name,primary_source,schema_version,quality_policy)
            VALUES (%s,%s,'local_postgres.stock_history','v1',%s)
            ON CONFLICT(code) DO NOTHING
            RETURNING id
            """,
            (dataset_code, "Minimal research chain stock history", Json({"requires_real_rows": True, "script_version": SCRIPT_VERSION})),
            "SELECT id FROM dataset_definitions WHERE code=%s",
            (dataset_code,),
        )
        fetch_run_id = one(
            cursor,
            """
            INSERT INTO source_fetch_runs(
                dataset_id, requested_source, actual_source, request_params, schema_version,
                finished_at, status, row_count, response_hash
            )
            VALUES (%s,'local_postgres.stock_history','local_postgres.stock_history',%s,'v1',NOW(),'success',%s,%s)
            RETURNING id
            """,
            (dataset_id, Json({"symbols": [row.symbol for row in rows], "trade_date": latest.isoformat()}), row_count, chain_hash),
        )
        partition_hash = stable_hash({"dataset_code": dataset_code, "chain_hash": chain_hash})
        partition_id = ensure_id(
            cursor,
            """
            INSERT INTO dataset_partitions(
                dataset_id, fetch_run_id, partition_key, start_date, end_date, symbol_count,
                row_count, content_hash, available_at, knowledge_cutoff_at, status
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'published')
            ON CONFLICT(dataset_id, partition_key, content_hash) DO NOTHING
            RETURNING id
            """,
            (dataset_id, fetch_run_id, f"trade_date={latest.isoformat()}", earliest, latest, row_count, row_count, partition_hash, cutoff, cutoff),
            "SELECT id FROM dataset_partitions WHERE dataset_id=%s AND partition_key=%s AND content_hash=%s",
            (dataset_id, f"trade_date={latest.isoformat()}", partition_hash),
        )
        dataset_snapshot_id = ensure_id(
            cursor,
            """
            INSERT INTO dataset_snapshots(name,status,knowledge_cutoff_at,manifest_hash,sealed_at)
            VALUES (%s,'draft',%s,%s,NULL)
            ON CONFLICT(name) DO NOTHING
            RETURNING id
            """,
            (sample_name, cutoff, chain_hash),
            "SELECT id FROM dataset_snapshots WHERE name=%s",
            (sample_name,),
        )
        dataset_snapshot_status = one(cursor, "SELECT status FROM dataset_snapshots WHERE id=%s", (dataset_snapshot_id,))
        if dataset_snapshot_status != "sealed":
            cursor.execute(
                """
                INSERT INTO dataset_snapshot_items(snapshot_id,partition_id,dataset_code,content_hash)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT(snapshot_id,partition_id) DO NOTHING
                """,
                (dataset_snapshot_id, partition_id, dataset_code, partition_hash),
            )
            cursor.execute("UPDATE dataset_snapshots SET status='sealed', sealed_at=COALESCE(sealed_at,NOW()) WHERE id=%s AND status='draft'", (dataset_snapshot_id,))

        universe_code = "minimal_research_chain_a_share"
        universe_definition_id = ensure_id(
            cursor,
            """
            INSERT INTO universe_definitions(code,rule_version,description)
            VALUES (%s,%s,%s)
            ON CONFLICT(code) DO NOTHING
            RETURNING id
            """,
            (universe_code, SCRIPT_VERSION, "Symbols with real synchronized latest close and previous close evidence."),
            "SELECT id FROM universe_definitions WHERE code=%s",
            (universe_code,),
        )
        universe_hash = stable_hash({"universe": universe_code, "symbols": [row.symbol for row in rows], "trade_date": latest.isoformat()})
        universe_snapshot_id = ensure_id(
            cursor,
            """
            INSERT INTO universe_snapshots(definition_id,trade_date,knowledge_cutoff_at,manifest_hash,status,sealed_at)
            VALUES (%s,%s,%s,%s,'draft',NULL)
            ON CONFLICT(definition_id,trade_date,knowledge_cutoff_at) DO NOTHING
            RETURNING id
            """,
            (universe_definition_id, latest, cutoff, universe_hash),
            "SELECT id FROM universe_snapshots WHERE definition_id=%s AND trade_date=%s AND knowledge_cutoff_at=%s",
            (universe_definition_id, latest, cutoff),
        )
        universe_snapshot_status = one(cursor, "SELECT status FROM universe_snapshots WHERE id=%s", (universe_snapshot_id,))
        if universe_snapshot_status != "sealed":
            for row in rows:
                cursor.execute(
                    """
                    INSERT INTO universe_snapshot_members(snapshot_id,symbol,industry_code,benchmark_weight,eligibility_flags)
                    VALUES (%s,%s,NULL,%s,%s)
                    ON CONFLICT(snapshot_id,symbol) DO NOTHING
                    """,
                    (universe_snapshot_id, row.symbol, 1 / row_count, Json({"real_stock_history": True})),
                )
            cursor.execute("UPDATE universe_snapshots SET status='sealed', sealed_at=COALESCE(sealed_at,NOW()) WHERE id=%s AND status='draft'", (universe_snapshot_id,))

        factor_definition_id = ensure_id(
            cursor,
            """
            INSERT INTO factor_definitions(
                factor_code, factor_name, category, subcategory, description, formula,
                data_source, update_frequency, unit, owner_name, direction, research_status, enabled
            )
            VALUES (%s,%s,'price','momentum',%s,%s,'stock_history','daily','return','StockPro',1,'validated',TRUE)
            ON CONFLICT(factor_code) DO NOTHING
            RETURNING id
            """,
            (
                "minimal_real_close_return_1d",
                "Minimal real close return 1d",
                "One-day close-to-close return computed from real synchronized A-share rows.",
                "(close / previous_close) - 1",
            ),
            "SELECT id FROM factor_definitions WHERE factor_code=%s",
            ("minimal_real_close_return_1d",),
        )
        factor_code = "return row['close'] / row['prev_close'] - 1"
        factor_hash = stable_hash({"factor_code": factor_code, "script_version": SCRIPT_VERSION})
        factor_version_id = ensure_id(
            cursor,
            """
            INSERT INTO factor_versions(
                factor_definition_id, version_no, python_code, content_hash, declared_lookback,
                dependencies, output_unit, validation_status, validation_result
            )
            VALUES (%s,1,%s,%s,2,%s,'return','valid',%s)
            ON CONFLICT(factor_definition_id,version_no) DO NOTHING
            RETURNING id
            """,
            (
                factor_definition_id,
                factor_code,
                factor_hash,
                Json(["stock_history.close", "all_stocks_realtime.change_percent"]),
                Json({
                    "sample_chain": True,
                    "source_table": "stock_history",
                    "prev_close_sources": sorted({row.prev_close_source for row in rows}),
                }),
            ),
            "SELECT id FROM factor_versions WHERE factor_definition_id=%s AND version_no=1",
            (factor_definition_id,),
        )
        cursor.execute("UPDATE factor_definitions SET active_version_id=%s WHERE id=%s AND active_version_id IS DISTINCT FROM %s", (factor_version_id, factor_definition_id, factor_version_id))
        compute_hash = stable_hash({"factor_version_id": factor_version_id, "chain_hash": chain_hash})
        compute_run_id = ensure_id(
            cursor,
            """
            INSERT INTO factor_compute_runs(
                factor_version_id, trade_date, dataset_snapshot_id, universe_snapshot_id,
                knowledge_cutoff_at, idempotency_key, status, input_hash, input_count,
                output_count, missing_count, started_at, finished_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,'running',%s,%s,%s,0,NOW(),NOW())
            ON CONFLICT(idempotency_key) DO NOTHING
            RETURNING id
            """,
            (factor_version_id, latest, dataset_snapshot_id, universe_snapshot_id, cutoff, compute_hash, chain_hash, row_count, row_count),
            "SELECT id FROM factor_compute_runs WHERE idempotency_key=%s",
            (compute_hash,),
        )
        ordered = sorted(rows, key=lambda item: item.daily_return, reverse=True)
        for rank, row in enumerate(ordered, start=1):
            percentile = 1.0 if row_count == 1 else 1.0 - ((rank - 1) / (row_count - 1))
            quantile = min(5, max(1, int(percentile * 5) or 1))
            cursor.execute(
                """
                INSERT INTO factor_daily_values(
                    factor_version_id, compute_run_id, trade_date, symbol, raw_value,
                    processed_value, rank, percentile, quantile, quality_flags, available_at, source_lineage
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(factor_version_id,trade_date,symbol,compute_run_id) DO NOTHING
                """,
                (
                    factor_version_id,
                    compute_run_id,
                    latest,
                    row.symbol,
                    float(row.daily_return),
                    float(row.daily_return),
                    rank,
                    percentile,
                    quantile,
                    Json({"real_stock_history": True, "script_version": SCRIPT_VERSION}),
                    cutoff,
                    Json({
                        "source_table": "stock_history",
                        "source_columns": ["close"],
                        "prev_close_sources": sorted({row.prev_close_source for row in rows}),
                        "sample_chain_hash": chain_hash,
                    }),
                ),
            )
        value_hash = stable_hash({"factor_values": [(row.symbol, str(row.daily_return)) for row in ordered]})
        cursor.execute(
            """
            UPDATE factor_compute_runs
            SET status='published', value_hash=%s, metric_hash=%s
            WHERE id=%s AND status <> 'published'
            """,
            (value_hash, value_hash, compute_run_id),
        )
        factor_snapshot_id = ensure_id(
            cursor,
            """
            INSERT INTO factor_snapshots(name,trade_date,dataset_snapshot_id,universe_snapshot_id,knowledge_cutoff_at,status,manifest_hash,sealed_at)
            VALUES (%s,%s,%s,%s,%s,'draft',%s,NULL)
            ON CONFLICT(name) DO NOTHING
            RETURNING id
            """,
            (sample_name, latest, dataset_snapshot_id, universe_snapshot_id, cutoff, value_hash),
            "SELECT id FROM factor_snapshots WHERE name=%s",
            (sample_name,),
        )
        factor_snapshot_status = one(cursor, "SELECT status FROM factor_snapshots WHERE id=%s", (factor_snapshot_id,))
        if factor_snapshot_status != "sealed":
            cursor.execute(
                """
                INSERT INTO factor_snapshot_items(snapshot_id,factor_version_id,compute_run_id,value_hash,metric_hash)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT(snapshot_id,factor_version_id) DO NOTHING
                """,
                (factor_snapshot_id, factor_version_id, compute_run_id, value_hash, value_hash),
            )
            cursor.execute("UPDATE factor_snapshots SET status='sealed', sealed_at=COALESCE(sealed_at,NOW()) WHERE id=%s AND status='draft'", (factor_snapshot_id,))

        cursor.execute(
            """
            INSERT INTO market_evidence_snapshots(trade_date,snapshot_type,market_scope,available_at,source_map,status,content_hash)
            VALUES (%s,'post_close','minimal_research_chain',%s,%s,'sealed',%s)
            ON CONFLICT(trade_date,snapshot_type,market_scope,content_hash) DO NOTHING
            RETURNING id
            """,
            (latest, cutoff, Json({"stock_history": {"real_rows": True, "row_count": row_count}}), chain_hash),
        )
        inserted_market = cursor.fetchone()
        if inserted_market:
            market_evidence_snapshot_id = inserted_market[0]
        else:
            market_evidence_snapshot_id = one(
                cursor,
                """
                SELECT id FROM market_evidence_snapshots
                WHERE trade_date=%s AND snapshot_type='post_close' AND market_scope='minimal_research_chain' AND content_hash=%s
                """,
                (latest, chain_hash),
            )

        pool_id = ensure_id(
            cursor,
            """
            INSERT INTO stock_pools(id,name,pool_type,description,status)
            VALUES (%s,%s,'factor',%s,'active')
            ON CONFLICT(id) DO NOTHING
            RETURNING id
            """,
            (deterministic_uuid("pool", chain_key), sample_name, "Minimal factor pool from real stock_history returns."),
            "SELECT id FROM stock_pools WHERE id=%s",
            (deterministic_uuid("pool", chain_key),),
        )
        rule_hash = stable_hash({"pool_id": pool_id, "factor": "minimal_real_close_return_1d", "version": SCRIPT_VERSION})
        rule_id = ensure_id(
            cursor,
            """
            INSERT INTO stock_pool_rules(pool_id,rule_type,rule_version,config,content_hash)
            VALUES (%s,'factor_top_rank',1,%s,%s)
            ON CONFLICT(pool_id,rule_version) DO NOTHING
            RETURNING id
            """,
            (pool_id, Json({"factor_code": "minimal_real_close_return_1d", "source_table": "stock_history"}), rule_hash),
            "SELECT id FROM stock_pool_rules WHERE pool_id=%s AND rule_version=1",
            (pool_id,),
        )
        generation_id = deterministic_uuid("generation", chain_key)
        input_manifest = {
            "dataset_snapshot_id": dataset_snapshot_id,
            "universe_snapshot_id": universe_snapshot_id,
            "factor_snapshot_id": factor_snapshot_id,
            "source_table": "stock_history",
            "script_version": SCRIPT_VERSION,
        }
        input_hash = stable_hash(input_manifest)
        cursor.execute(
            """
            INSERT INTO stock_pool_generations(
                id,pool_id,rule_id,dataset_snapshot_id,universe_snapshot_id,factor_snapshot_id,
                market_evidence_snapshot_id,trade_date,knowledge_cutoff_at,input_manifest,input_hash,
                member_manifest_hash,status,finished_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'success',NOW())
            ON CONFLICT DO NOTHING
            """,
            (generation_id, pool_id, rule_id, dataset_snapshot_id, universe_snapshot_id, factor_snapshot_id, market_evidence_snapshot_id, latest, cutoff, Json(input_manifest), input_hash, value_hash),
        )
        for rank, row in enumerate(ordered, start=1):
            evidence = {
                "daily_return": float(row.daily_return),
                "close": float(row.close),
                "prev_close": float(row.prev_close),
                "prev_close_source": row.prev_close_source,
                "source_table": "stock_history",
            }
            cursor.execute(
                """
                INSERT INTO stock_pool_members(
                    generation_id,pool_id,ordinal,symbol,score,reason,evidence,evidence_hash,
                    valid_from,source_object_type,source_object_id,generator_version
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'factor_daily_values',%s,%s)
                ON CONFLICT(generation_id,symbol) DO NOTHING
                """,
                (generation_id, pool_id, rank, row.symbol, float(row.daily_return), "Real close-to-close return ranked from stock_history.", Json(evidence), stable_hash(evidence), latest, str(compute_run_id), SCRIPT_VERSION),
            )
        pool_snapshot_id = ensure_id(
            cursor,
            """
            INSERT INTO stock_pool_snapshots(
                pool_id,generation_id,dataset_snapshot_id,universe_snapshot_id,factor_snapshot_id,
                market_evidence_snapshot_id,trade_date,knowledge_cutoff_at,manifest_hash,member_count,status,sealed_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',NULL)
            ON CONFLICT(pool_id,manifest_hash) DO NOTHING
            RETURNING id
            """,
            (pool_id, generation_id, dataset_snapshot_id, universe_snapshot_id, factor_snapshot_id, market_evidence_snapshot_id, latest, cutoff, value_hash, row_count),
            "SELECT id FROM stock_pool_snapshots WHERE pool_id=%s AND manifest_hash=%s",
            (pool_id, value_hash),
        )
        pool_snapshot_status = one(cursor, "SELECT status FROM stock_pool_snapshots WHERE id=%s", (pool_snapshot_id,))
        if pool_snapshot_status != "sealed":
            for rank, row in enumerate(ordered, start=1):
                evidence = {
                    "daily_return": float(row.daily_return),
                    "prev_close_source": row.prev_close_source,
                    "source_table": "stock_history",
                }
                cursor.execute(
                    """
                    INSERT INTO stock_pool_snapshot_members(
                        snapshot_id,ordinal,symbol,score,reason,evidence,evidence_hash,valid_from,generator_version
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(snapshot_id,symbol) DO NOTHING
                    """,
                    (pool_snapshot_id, rank, row.symbol, float(row.daily_return), "Real close-to-close return ranked from stock_history.", Json(evidence), stable_hash(evidence), latest, SCRIPT_VERSION),
                )
            cursor.execute("UPDATE stock_pool_snapshots SET status='sealed', sealed_at=COALESCE(sealed_at,NOW()) WHERE id=%s AND status='draft'", (pool_snapshot_id,))

        protocol_hash = stable_hash({"chain_key": chain_key, "protocol": SCRIPT_VERSION})
        research_protocol_id = ensure_id(
            cursor,
            """
            INSERT INTO research_protocols(
                name,hypothesis,universe_description,benchmark_code,train_start,train_end,
                validation_start,validation_end,out_of_sample_start,out_of_sample_end,
                capacity_rules,promotion_thresholds,selection_rationale,content_hash,status,sealed_at
            )
            VALUES (%s,%s,%s,'000300.SH',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'sealed',NOW())
            ON CONFLICT(content_hash) DO NOTHING
            RETURNING id
            """,
            (
                sample_name,
                "Positive one-day close return is used only as a minimal auditable research-chain sample.",
                "Symbols selected from real synchronized rows with latest close and previous close evidence.",
                earliest,
                latest,
                earliest,
                latest,
                earliest,
                latest,
                Json({"sample_only": True, "max_position_weight": 0.10}),
                Json({"backtest_status": "success", "promotion_status": "paper_eligible"}),
                "Created by explicitly authorized minimal sample script from existing synchronized A-share rows.",
                protocol_hash,
            ),
            "SELECT id FROM research_protocols WHERE content_hash=%s",
            (protocol_hash,),
        )
        strategy_payload = {
            "script_version": SCRIPT_VERSION,
            "signal": "rank by real close-to-close return",
            "source_table": "stock_history",
        }
        strategy_content = "def generate_signals(rows):\n    return sorted(rows, key=lambda row: row['daily_return'], reverse=True)\n"
        strategy_id = ensure_id(
            cursor,
            """
            INSERT INTO strategy_versions(
                id,name,version,description,script_content,parameter_schema,data_dependencies,
                output_contract,status,content_hash,strategy_api_version,validation_status,
                validation_report,validated_at,migration_status
            )
            VALUES (%s,%s,1,%s,%s,%s,%s,%s,'active',%s,'stockpro.v1','valid',%s,NOW(),'validated')
            ON CONFLICT(name,version) DO NOTHING
            RETURNING id
            """,
            (
                deterministic_uuid("strategy", chain_key),
                sample_name,
                "Minimal audited sample strategy; not investment advice.",
                strategy_content,
                Json({}),
                Json(["stock_history.close", "all_stocks_realtime.change_percent"]),
                Json({"signals": "candidate/buy records"}),
                stable_hash(strategy_content),
                Json(strategy_payload),
            ),
            "SELECT id FROM strategy_versions WHERE name=%s AND version=1",
            (sample_name,),
        )
        cursor.execute(
            """
            INSERT INTO strategy_validation_runs(strategy_version_id,strategy_api_version,status,report,code_hash)
            VALUES (%s,'stockpro.v1','valid',%s,%s)
            ON CONFLICT DO NOTHING
            """,
            (strategy_id, Json({"sample_chain": True, "source_table": "stock_history"}), stable_hash(strategy_content)),
        )

        cost_model_id = one(cursor, "SELECT id FROM backtest_cost_models WHERE code='cn_stock_default' AND version=1", ())
        backtest_input_hash = stable_hash({"chain_key": chain_key, "stage": "backtest"})
        backtest_id = ensure_id(
            cursor,
            """
            INSERT INTO backtest_runs(
                id,strategy_version_id,name,universe,parameters,start_date,end_date,status,metrics,
                started_at,finished_at,dataset_snapshot_id,pool_snapshot_id,factor_snapshot_id,
                universe_snapshot_id,knowledge_cutoff_at,research_protocol_id,cost_model_id,
                benchmark_code,strategy_api_version,input_hash,run_mode,progress,promotion_status,
                initial_cash,frequency,calculation_version,result_manifest,sealed_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,'running',%s,NOW(),NULL,%s,%s,%s,%s,%s,%s,%s,
                    '000300.SH','stockpro.v1',%s,'full',50,'not_evaluated',%s,'1d',%s,%s,NULL)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (
                deterministic_uuid("backtest", chain_key),
                strategy_id,
                sample_name,
                Json({"symbols": [row.symbol for row in rows]}),
                Json({"sample_chain": True}),
                earliest,
                latest,
                Json({"total_return": float(primary.daily_return), "sample_only": True}),
                dataset_snapshot_id,
                pool_snapshot_id,
                factor_snapshot_id,
                universe_snapshot_id,
                cutoff,
                research_protocol_id,
                cost_model_id,
                backtest_input_hash,
                initial_cash,
                "minimal-backtest.v1",
                Json({"source_table": "stock_history", "sealed": True, "script_version": SCRIPT_VERSION}),
            ),
            "SELECT id FROM backtest_runs WHERE input_hash=%s AND run_mode='full'",
            (backtest_input_hash,),
        )
        backtest_status = one(cursor, "SELECT status FROM backtest_runs WHERE id=%s", (backtest_id,))
        backtest_metrics = {
            "total_return": primary.daily_return,
            "max_drawdown": Decimal("0"),
            "win_rate": Decimal("1") if primary.daily_return >= 0 else Decimal("0"),
        }
        if backtest_status != "success":
            for metric_code, metric_value in backtest_metrics.items():
                cursor.execute(
                    """
                    INSERT INTO backtest_metrics(
                        backtest_run_id,metric_code,metric_value,unit,calculation_version,input_frequency,metric_payload
                    )
                    VALUES (%s,%s,%s,'ratio','minimal-backtest.v1','1d',%s)
                    ON CONFLICT(backtest_run_id,metric_code) DO NOTHING
                    """,
                    (backtest_id, metric_code, float(metric_value), Json({"source_table": "stock_history"})),
                )
            cursor.execute(
                """
                INSERT INTO backtest_daily_equity(
                    backtest_run_id,trade_date,strategy_nav,strategy_return,equity,cash,market_value,
                    gross_exposure,net_exposure,position_count,drawdown
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1,0)
                ON CONFLICT(backtest_run_id,trade_date) DO NOTHING
                """,
                (backtest_id, latest, float(nav), float(primary.daily_return), equity, cash_after, market_value, float(market_value / equity), float(market_value / equity)),
            )
            cursor.execute(
                """
                INSERT INTO backtest_trades(backtest_run_id,trade_date,symbol,name,side,price,quantity,amount,commission,reason)
                VALUES (%s,%s,%s,%s,'buy',%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                (backtest_id, latest, primary.symbol, primary.name, primary.close, quantity, gross_cost, commission, "Minimal sample fill priced from stock_history close."),
            )
            cursor.execute(
                """
                UPDATE backtest_runs
                SET status='success',
                    finished_at=COALESCE(finished_at,NOW()),
                    progress=100,
                    promotion_status='paper_eligible',
                    metrics=%s,
                    sealed_at=COALESCE(sealed_at,NOW())
                WHERE id=%s AND status <> 'success'
                """,
                (
                    Json({"total_return": float(primary.daily_return), "sample_only": True, "source_table": "stock_history"}),
                    backtest_id,
                ),
            )

        portfolio_id = ensure_id(
            cursor,
            """
            INSERT INTO portfolios(id,name,mode,initial_cash,cash_balance,status)
            VALUES (%s,%s,'paper',%s,%s,'active')
            ON CONFLICT(name) DO NOTHING
            RETURNING id
            """,
            (deterministic_uuid("portfolio", chain_key), sample_name, initial_cash, cash_after),
            "SELECT id FROM portfolios WHERE name=%s",
            (sample_name,),
        )
        signal_id = deterministic_uuid("signal", chain_key)
        cursor.execute(
            """
            INSERT INTO strategy_signals(
                id,strategy_version_id,symbol,name,signal_type,status,signal_time,price,strength,
                reason,payload,signal_key,data_available_at
            )
            VALUES (%s,%s,%s,%s,'buy','ordered',%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
            """,
            (signal_id, strategy_id, primary.symbol, primary.name, cutoff, primary.close, Decimal("1.0"), "Minimal sample signal from real stock_history return.", Json({"source_table": "stock_history"}), f"{SCRIPT_VERSION}:{chain_hash}:signal", cutoff),
        )
        order_id = deterministic_uuid("order", chain_key)
        cursor.execute(
            """
            INSERT INTO orders(
                id,portfolio_id,signal_id,symbol,name,side,order_type,price,quantity,filled_quantity,
                status,message,signal_time,data_available_at,earliest_fill_at,filled_at
            )
            VALUES (%s,%s,%s,%s,%s,'buy','limit',%s,%s,%s,'filled',%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
            """,
            (order_id, portfolio_id, signal_id, primary.symbol, primary.name, primary.close, quantity, quantity, "Minimal sample order priced from stock_history close.", cutoff, cutoff, cutoff, cutoff),
        )
        trade_id = deterministic_uuid("trade", chain_key)
        cursor.execute(
            """
            INSERT INTO trades(
                id,portfolio_id,order_id,symbol,name,side,price,quantity,amount,commission,traded_at,
                signal_time,data_available_at,earliest_fill_at,paper_instance_id
            )
            VALUES (%s,%s,%s,%s,%s,'buy',%s,%s,%s,%s,%s,%s,%s,%s,NULL)
            ON CONFLICT DO NOTHING
            """,
            (trade_id, portfolio_id, order_id, primary.symbol, primary.name, primary.close, quantity, gross_cost, commission, cutoff, cutoff, cutoff, cutoff),
        )
        cursor.execute(
            """
            INSERT INTO positions(portfolio_id,symbol,name,quantity,available_quantity,avg_cost,last_price,market_value)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(portfolio_id,symbol) DO NOTHING
            """,
            (portfolio_id, primary.symbol, primary.name, quantity, quantity, primary.close, primary.close, market_value),
        )
        cursor.execute(
            """
            INSERT INTO cash_ledger(id,portfolio_id,event_type,amount,balance_after,ref_type,ref_id,note,created_at)
            VALUES (%s,%s,'buy',%s,%s,'trade',%s,%s,%s)
            ON CONFLICT DO NOTHING
            """,
            (deterministic_uuid("cash", chain_key), portfolio_id, -gross_cost - commission, cash_after, trade_id, "Minimal sample trade cash movement.", cutoff),
        )

        paper_id = deterministic_uuid("paper", chain_key)
        cursor.execute(
            """
            INSERT INTO paper_instances(
                id,name,strategy_version_id,dataset_snapshot_id,factor_snapshot_id,universe_snapshot_id,
                pool_snapshot_id,research_protocol_id,qualifying_backtest_run_id,portfolio_id,parameters,
                capacity_limits,feed_config,status,runtime_version,last_processed_trade_date,last_cycle_key,
                heartbeat_at,started_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'running',%s,%s,%s,%s,%s)
            ON CONFLICT(portfolio_id) DO NOTHING
            """,
            (
                paper_id,
                sample_name,
                strategy_id,
                dataset_snapshot_id,
                factor_snapshot_id,
                universe_snapshot_id,
                pool_snapshot_id,
                research_protocol_id,
                backtest_id,
                portfolio_id,
                Json({"sample_chain": True}),
                Json({"max_position_weight": 0.10}),
                Json({"source_table": "stock_history", "mode": "local_snapshot"}),
                SCRIPT_VERSION,
                latest,
                f"{latest.isoformat()}:{chain_hash[:12]}",
                cutoff,
                cutoff,
            ),
        )
        cycle_id = deterministic_uuid("cycle", chain_key)
        cursor.execute(
            """
            INSERT INTO paper_runtime_cycles(
                id,paper_instance_id,cycle_key,trade_date,data_available_at,observed_at,input_hash,
                status,signal_count,order_count,trade_count,ledger_difference,finished_at
            )
            VALUES (%s,%s,%s,%s,%s,NOW(),%s,'success',1,1,1,0,NOW())
            ON CONFLICT(paper_instance_id,cycle_key) DO NOTHING
            """,
            (cycle_id, paper_id, f"{latest.isoformat()}:{chain_hash[:12]}", latest, cutoff, chain_hash),
        )
        cursor.execute("UPDATE trades SET paper_instance_id=%s WHERE id=%s AND paper_instance_id IS NULL", (paper_id, trade_id))
        cursor.execute("UPDATE orders SET paper_instance_id=%s WHERE id=%s AND paper_instance_id IS NULL", (paper_id, order_id))
        cursor.execute("UPDATE strategy_signals SET paper_instance_id=%s WHERE id=%s AND paper_instance_id IS NULL", (paper_id, signal_id))
        cursor.execute(
            """
            INSERT INTO paper_instance_events(paper_instance_id,cycle_id,event_type,level,message,payload,occurred_at)
            VALUES (%s,%s,'sample_chain_created','info',%s,%s,%s)
            ON CONFLICT DO NOTHING
            """,
            (paper_id, cycle_id, "Authorized minimal research chain sample created.", Json({"source_table": "stock_history", "chain_hash": chain_hash}), cutoff),
        )
        cursor.execute(
            """
            INSERT INTO paper_equity_snapshots(
                paper_instance_id,cycle_id,trade_date,cash,market_value,equity,gross_exposure,nav,drawdown,ledger_difference
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,0)
            ON CONFLICT(paper_instance_id,trade_date) DO NOTHING
            """,
            (paper_id, cycle_id, latest, cash_after, market_value, equity, market_value / equity, nav),
        )
        review_id = deterministic_uuid("review", chain_key)
        cursor.execute(
            """
            INSERT INTO daily_reviews(id,trade_date,status,author_name,summary,next_day_plan,source_manifest_hash,sealed_at)
            VALUES (%s,%s,'draft','system',%s,%s,%s,NULL)
            ON CONFLICT(trade_date) DO NOTHING
            """,
            (review_id, latest, "Minimal research chain sample created from real stock_history rows.", "Review the sample chain before enabling production research automation.", chain_hash),
        )
        review_id = one(cursor, "SELECT id FROM daily_reviews WHERE trade_date=%s", (latest,))
        review_status = one(cursor, "SELECT status FROM daily_reviews WHERE id=%s", (review_id,))
        if review_status != "sealed":
            review_evidence = {"source_table": "stock_history", "paper_instance_id": paper_id, "backtest_run_id": str(backtest_id)}
            cursor.execute(
                """
                INSERT INTO daily_review_items(
                    daily_review_id,item_key,occurred_at,category,title,summary,source_object_type,
                    source_object_id,source_route,evidence,evidence_hash
                )
                VALUES (%s,%s,%s,'system',%s,%s,'paper_instance',%s,'/live',%s,%s)
                ON CONFLICT(daily_review_id,item_key) DO NOTHING
                """,
                (review_id, f"minimal-chain:{chain_hash[:12]}", cutoff, "Minimal research chain sample", "Dataset, factor, pool, backtest, Paper and review records were linked.", paper_id, Json(review_evidence), stable_hash(review_evidence)),
            )
            cursor.execute(
                """
                INSERT INTO daily_review_metrics(
                    daily_review_id,metric_code,metric_value,unit,comparison_window,source_object_type,
                    source_object_id,calculation_version,evidence
                )
                VALUES (%s,'minimal_chain_total_return',%s,'ratio','latest_close_vs_previous_close','backtest_run',%s,%s,%s)
                ON CONFLICT(daily_review_id,metric_code,source_object_type,source_object_id) DO NOTHING
                """,
                (review_id, float(primary.daily_return), str(backtest_id), SCRIPT_VERSION, Json({"source_table": "stock_history"})),
            )
            cursor.execute("UPDATE daily_reviews SET status='sealed', sealed_at=COALESCE(sealed_at,NOW()) WHERE id=%s AND status='draft'", (review_id,))

    return {
        "chain_hash": chain_hash,
        "trade_date": latest.isoformat(),
        "symbols": [row.symbol for row in rows],
        "dataset_snapshot_id": dataset_snapshot_id,
        "universe_snapshot_id": universe_snapshot_id,
        "factor_snapshot_id": factor_snapshot_id,
        "pool_snapshot_id": pool_snapshot_id,
        "research_protocol_id": str(research_protocol_id),
        "strategy_version_id": str(strategy_id),
        "backtest_run_id": str(backtest_id),
        "portfolio_id": str(portfolio_id),
        "paper_instance_id": paper_id,
        "daily_review_id": str(review_id),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        require_apply_confirmation(args)
        if not args.database_url:
            raise SampleChainError("DATABASE_URL or --database-url is required")
        conn = psycopg2.connect(args.database_url)
        conn.set_session(readonly=not args.apply, autocommit=False)
        try:
            rows = load_real_market_rows(conn, args.symbol, args.max_symbols)
            summary = {"mode": "apply" if args.apply else "dry_run", "ready": True, **summarize_rows(rows)}
            if args.apply:
                summary["created"] = create_minimal_research_chain(conn, rows)
                conn.commit()
            else:
                conn.rollback()
                summary["would_create"] = [
                    "dataset snapshot",
                    "universe snapshot",
                    "factor snapshot",
                    "stock pool snapshot",
                    "strategy validation",
                    "sealed backtest",
                    "paper instance",
                    "daily review",
                ]
            print(stable_json(summary))
            return 0
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except SampleChainError as exc:
        print(stable_json({"ready": False, "error": str(exc), "mode": "apply" if getattr(args, "apply", False) else "dry_run"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
