"""Deterministic factor/sector/event stock pools backed by sealed PG evidence."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence

import psycopg2.extras

from app.services.dataset_snapshot_service import DatasetSnapshotService, canonical_hash
from app.services.data_purpose import resolve_data_purpose
from app.services.factor_research_service import FactorResearchService
from app.services.reference_dataset_sync_service import ReferenceDatasetSyncService


GENERATOR_VERSION = "stock-pool-generator.v1"


class StockPoolService:
    def __init__(self, database):
        self.database = database
        self.datasets = DatasetSnapshotService(database)
        self.factors = FactorResearchService(database)
        self.references = ReferenceDatasetSyncService(database, snapshot_service=self.datasets)

    def create_pool(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        pool_type = str(payload.get("pool_type") or "").strip()
        if not name or pool_type not in {"screener", "factor", "sector", "event", "manual"}:
            raise ValueError("股票池名称和合法 pool_type 必填")
        config = dict(payload.get("config") or {})
        rule_type = str(payload.get("rule_type") or pool_type)
        content_hash = canonical_hash({"rule_type": rule_type, "rule_version": 1, "config": config})
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO stock_pools(name,pool_type,description,status,data_purpose)
                    VALUES (%s,%s,%s,'active',%s) RETURNING *
                    """,
                    (
                        name,
                        pool_type,
                        str(payload.get("description") or ""),
                        str(payload.get("data_purpose") or "user"),
                    ),
                )
                pool = dict(cursor.fetchone())
                cursor.execute(
                    """
                    INSERT INTO stock_pool_rules(pool_id,rule_type,rule_version,config,content_hash)
                    VALUES (%s,%s,1,%s,%s) RETURNING *
                    """,
                    (pool["id"], rule_type, psycopg2.extras.Json(config), content_hash),
                )
                rule = dict(cursor.fetchone())
        return {**pool, "rule": rule}

    def list_pools(self) -> List[Dict[str, Any]]:
        rows = self._rows(
            """
            SELECT p.*,r.id AS rule_id,r.rule_type,r.rule_version,r.config,r.content_hash AS rule_hash,
                   (SELECT COUNT(*) FROM stock_pool_snapshots s WHERE s.pool_id=p.id AND s.status='sealed')::INTEGER AS snapshot_count,
                   (SELECT COUNT(*) FROM stock_pool_members m WHERE m.generation_id=g.id)::INTEGER AS current_member_count,
                   g.id AS latest_generation_id,
                   g.dataset_snapshot_id AS latest_dataset_snapshot_id,
                   g.universe_snapshot_id AS latest_universe_snapshot_id,
                   g.factor_snapshot_id AS latest_factor_snapshot_id,
                   g.market_evidence_snapshot_id AS latest_market_evidence_snapshot_id,
                   g.trade_date AS latest_trade_date,
                   g.knowledge_cutoff_at AS latest_knowledge_cutoff_at,
                   g.input_hash AS latest_input_hash
            FROM stock_pools p
            JOIN LATERAL (SELECT * FROM stock_pool_rules WHERE pool_id=p.id ORDER BY rule_version DESC LIMIT 1) r ON TRUE
            LEFT JOIN LATERAL (
                SELECT id,dataset_snapshot_id,universe_snapshot_id,factor_snapshot_id,
                       market_evidence_snapshot_id,trade_date,knowledge_cutoff_at,input_hash
                FROM stock_pool_generations
                WHERE pool_id=p.id AND status='success'
                ORDER BY created_at DESC
                LIMIT 1
            ) g ON TRUE
            ORDER BY p.updated_at DESC,p.created_at DESC
            """
        )
        for row in rows:
            row["data_purpose"] = resolve_data_purpose(
                row.get("data_purpose"),
                row.get("name"),
                row.get("description"),
            )
        return rows

    def get_pool(self, pool_id: str) -> Dict[str, Any]:
        row = self._row(
            """
            SELECT p.*,r.id AS rule_id,r.rule_type,r.rule_version,r.config,r.content_hash AS rule_hash
            FROM stock_pools p JOIN LATERAL(
                SELECT * FROM stock_pool_rules WHERE pool_id=p.id ORDER BY rule_version DESC LIMIT 1
            ) r ON TRUE WHERE p.id=%s
            """,
            (str(pool_id),),
        )
        if not row:
            raise ValueError("股票池不存在")
        row["data_purpose"] = resolve_data_purpose(
            row.get("data_purpose"),
            row.get("name"),
            row.get("description"),
        )
        return row

    def generate(self, pool_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        pool = self.get_pool(pool_id)
        dataset = self.datasets.get_snapshot(int(payload.get("dataset_snapshot_id") or 0))
        universe = self.references.get_universe_snapshot(int(payload.get("universe_snapshot_id") or 0))
        if not dataset or dataset.get("status") != "sealed":
            raise ValueError("生成器必须绑定封存数据快照")
        if not universe or universe.get("status") != "sealed":
            raise ValueError("生成器必须绑定封存 Universe Snapshot")
        trade_date = str(payload.get("trade_date") or universe["trade_date"])[:10]
        if trade_date > str(universe["trade_date"])[:10]:
            raise ValueError("股票池交易日不能晚于 Universe Snapshot")
        factor_snapshot = None
        factor_snapshot_id = payload.get("factor_snapshot_id")
        if factor_snapshot_id:
            factor_snapshot = self.factors.get_factor_snapshot(int(factor_snapshot_id))
            if not factor_snapshot or factor_snapshot.get("status") != "sealed":
                raise ValueError("因子股票池必须绑定封存因子快照")
            if int(factor_snapshot["dataset_snapshot_id"]) != int(dataset["id"]) or int(factor_snapshot["universe_snapshot_id"]) != int(universe["id"]):
                raise ValueError("因子快照与数据/Universe Snapshot 不兼容")
            if str(factor_snapshot["trade_date"])[:10] != trade_date:
                raise ValueError("因子快照日期必须与股票池交易日一致")
        evidence_snapshot = None
        evidence_snapshot_id = payload.get("market_evidence_snapshot_id")
        if evidence_snapshot_id:
            evidence_snapshot = self._row("SELECT * FROM market_evidence_snapshots WHERE id=%s", (int(evidence_snapshot_id),))
            if not evidence_snapshot:
                raise ValueError("市场证据快照不存在")
            if str(evidence_snapshot["trade_date"]) != trade_date:
                raise ValueError("市场证据日期必须与股票池交易日一致")

        input_manifest = {
            "pool_id": str(pool["id"]), "pool_type": pool["pool_type"], "rule_id": str(pool["rule_id"]),
            "rule_version": pool["rule_version"], "rule_hash": pool["rule_hash"], "config": pool["config"],
            "dataset_snapshot_id": int(dataset["id"]), "dataset_manifest_hash": dataset["manifest_hash"],
            "universe_snapshot_id": int(universe["id"]), "universe_manifest_hash": universe["manifest_hash"],
            "factor_snapshot_id": int(factor_snapshot["id"]) if factor_snapshot else None,
            "factor_manifest_hash": factor_snapshot.get("manifest_hash") if factor_snapshot else None,
            "market_evidence_snapshot_id": int(evidence_snapshot["id"]) if evidence_snapshot else None,
            "market_evidence_hash": evidence_snapshot.get("content_hash") if evidence_snapshot else None,
            "trade_date": trade_date, "generator_version": GENERATOR_VERSION,
        }
        input_hash = canonical_hash(input_manifest)
        existing = self._row("SELECT id FROM stock_pool_generations WHERE input_hash=%s AND status='success'", (input_hash,))
        if existing:
            return {**self.get_generation(str(existing["id"])), "reused": True}
        cutoff_values = [dataset.get("knowledge_cutoff_at"), universe.get("knowledge_cutoff_at")]
        if factor_snapshot:
            cutoff_values.append(factor_snapshot.get("knowledge_cutoff_at"))
        if evidence_snapshot:
            cutoff_values.append(evidence_snapshot.get("available_at"))
        cutoff = max(value for value in cutoff_values if value is not None)
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO stock_pool_generations
                    (pool_id,rule_id,dataset_snapshot_id,universe_snapshot_id,factor_snapshot_id,
                     market_evidence_snapshot_id,trade_date,knowledge_cutoff_at,input_manifest,input_hash,status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'running') RETURNING id
                    """,
                    (
                        pool["id"], pool["rule_id"], dataset["id"], universe["id"],
                        factor_snapshot.get("id") if factor_snapshot else None,
                        evidence_snapshot.get("id") if evidence_snapshot else None,
                        trade_date, cutoff, psycopg2.extras.Json(input_manifest), input_hash,
                    ),
                )
                generation_id = str(cursor.fetchone()["id"])
        try:
            candidates = self._generate_candidates(pool, input_manifest)
            filtered = self._apply_universe_filters(candidates, universe, dataset, trade_date, dict(pool["config"] or {}))
            validity_days = max(1, min(int((pool["config"] or {}).get("validity_days") or 5), 365))
            valid_until = (date.fromisoformat(trade_date) + timedelta(days=validity_days)).isoformat()
            members = []
            for ordinal, candidate in enumerate(filtered, start=1):
                evidence = dict(candidate["evidence"])
                evidence["input_manifest_hash"] = input_hash
                evidence_hash = canonical_hash(evidence)
                members.append({
                    "ordinal": ordinal, "symbol": candidate["symbol"], "score": candidate.get("score"),
                    "reason": candidate["reason"], "evidence": evidence, "evidence_hash": evidence_hash,
                    "valid_from": trade_date, "valid_until": valid_until,
                    "source_object_type": candidate["source_object_type"],
                    "source_object_id": str(candidate["source_object_id"]), "generator_version": GENERATOR_VERSION,
                })
            member_manifest_hash = canonical_hash(members)
            with self.database.get_connection() as connection:
                with connection.cursor() as cursor:
                    if members:
                        psycopg2.extras.execute_values(
                            cursor,
                            """
                            INSERT INTO stock_pool_members
                            (generation_id,pool_id,ordinal,symbol,score,reason,evidence,evidence_hash,valid_from,
                             valid_until,source_object_type,source_object_id,generator_version) VALUES %s
                            """,
                            [
                                (
                                    generation_id, pool["id"], item["ordinal"], item["symbol"], item["score"], item["reason"],
                                    psycopg2.extras.Json(item["evidence"], dumps=self._json_dumps), item["evidence_hash"], item["valid_from"],
                                    item["valid_until"], item["source_object_type"], item["source_object_id"], item["generator_version"],
                                )
                                for item in members
                            ],
                        )
                    cursor.execute(
                        "UPDATE stock_pool_generations SET status='success',member_manifest_hash=%s,finished_at=NOW() WHERE id=%s",
                        (member_manifest_hash, generation_id),
                    )
            return self.get_generation(generation_id)
        except Exception as exc:
            self._execute(
                "UPDATE stock_pool_generations SET status='failed',error_message=%s,finished_at=NOW() WHERE id=%s",
                (str(exc)[:1000], generation_id),
            )
            raise

    def members(self, pool_id: str, generation_id: Optional[str] = None) -> List[Dict[str, Any]]:
        self.get_pool(pool_id)
        if not generation_id:
            row = self._row(
                "SELECT id FROM stock_pool_generations WHERE pool_id=%s AND status='success' ORDER BY created_at DESC LIMIT 1",
                (str(pool_id),),
            )
            if not row:
                return []
            generation_id = str(row["id"])
        return self._attach_member_names(
            self._rows(
                "SELECT * FROM stock_pool_members WHERE pool_id=%s AND generation_id=%s ORDER BY ordinal",
                (str(pool_id), str(generation_id)),
            )
        )

    def get_generation(self, generation_id: str) -> Dict[str, Any]:
        row = self._row("SELECT * FROM stock_pool_generations WHERE id=%s", (str(generation_id),))
        if not row:
            raise ValueError("股票池生成批次不存在")
        row["members"] = self._attach_member_names(
            self._rows(
                "SELECT * FROM stock_pool_members WHERE generation_id=%s ORDER BY ordinal",
                (str(generation_id),),
            )
        )
        row["member_count"] = len(row["members"])
        return row

    def _attach_member_names(self, members: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        symbols = [str(item.get("symbol") or "").strip() for item in members if item.get("symbol")]
        names = self.database.lookup_symbol_names(symbols) if symbols else {}
        for item in members:
            symbol = str(item.get("symbol") or "").strip()
            resolved = str(names.get(symbol) or item.get("name") or "").strip()
            if resolved and resolved != symbol:
                item["name"] = resolved
            else:
                item["name"] = item.get("name") or ""
        return members

    def seal_snapshot(self, pool_id: str, generation_id: Optional[str] = None) -> Dict[str, Any]:
        pool = self.get_pool(pool_id)
        if not generation_id:
            latest = self._row(
                "SELECT id FROM stock_pool_generations WHERE pool_id=%s AND status='success' ORDER BY created_at DESC LIMIT 1",
                (str(pool_id),),
            )
            if not latest:
                raise ValueError("股票池还没有成功生成批次")
            generation_id = str(latest["id"])
        generation = self.get_generation(generation_id)
        if str(generation["pool_id"]) != str(pool["id"]) or generation["status"] != "success":
            raise ValueError("生成批次不属于股票池或尚未成功")
        members = generation["members"]
        if not members:
            raise ValueError("空股票池不能封存快照")
        manifest_members = [
            {
                "ordinal": item["ordinal"], "symbol": item["symbol"], "score": item["score"], "reason": item["reason"],
                "evidence_hash": item["evidence_hash"], "valid_from": str(item["valid_from"]),
                "valid_until": str(item["valid_until"]) if item.get("valid_until") else None,
                "generator_version": item["generator_version"],
            }
            for item in members
        ]
        manifest_hash = canonical_hash({
            "pool_id": str(pool["id"]), "generation_input_hash": generation["input_hash"], "members": manifest_members,
        })
        existing = self._row(
            "SELECT id FROM stock_pool_snapshots WHERE pool_id=%s AND manifest_hash=%s AND status='sealed'",
            (pool["id"], manifest_hash),
        )
        if existing:
            return {**self.get_snapshot(int(existing["id"])), "reused": True}
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO stock_pool_snapshots
                    (pool_id,generation_id,dataset_snapshot_id,universe_snapshot_id,factor_snapshot_id,
                     market_evidence_snapshot_id,trade_date,knowledge_cutoff_at,manifest_hash,member_count,status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft') RETURNING id
                    """,
                    (
                        pool["id"], generation["id"], generation["dataset_snapshot_id"], generation["universe_snapshot_id"],
                        generation.get("factor_snapshot_id"), generation.get("market_evidence_snapshot_id"), generation["trade_date"],
                        generation["knowledge_cutoff_at"], manifest_hash, len(members),
                    ),
                )
                snapshot_id = int(cursor.fetchone()["id"])
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO stock_pool_snapshot_members
                    (snapshot_id,ordinal,symbol,score,reason,evidence,evidence_hash,valid_from,valid_until,generator_version)
                    VALUES %s
                    """,
                    [
                        (
                            snapshot_id, item["ordinal"], item["symbol"], item["score"], item["reason"],
                            psycopg2.extras.Json(item["evidence"], dumps=self._json_dumps), item["evidence_hash"], item["valid_from"],
                            item.get("valid_until"), item["generator_version"],
                        )
                        for item in members
                    ],
                )
                cursor.execute(
                    "UPDATE stock_pool_snapshots SET status='sealed',sealed_at=NOW() WHERE id=%s", (snapshot_id,)
                )
        return self.get_snapshot(snapshot_id)

    def list_snapshots(self, pool_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if pool_id:
            return self._rows(
                "SELECT s.*,p.name AS pool_name,p.pool_type FROM stock_pool_snapshots s JOIN stock_pools p ON p.id=s.pool_id WHERE s.pool_id=%s ORDER BY s.id DESC",
                (str(pool_id),),
            )
        return self._rows(
            "SELECT s.*,p.name AS pool_name,p.pool_type FROM stock_pool_snapshots s JOIN stock_pools p ON p.id=s.pool_id ORDER BY s.id DESC LIMIT 200"
        )

    def get_snapshot(self, snapshot_id: int) -> Dict[str, Any]:
        snapshot = self._row(
            """
            SELECT s.*,p.name AS pool_name,p.pool_type,g.input_hash,g.input_manifest,g.member_manifest_hash
            FROM stock_pool_snapshots s JOIN stock_pools p ON p.id=s.pool_id
            JOIN stock_pool_generations g ON g.id=s.generation_id WHERE s.id=%s
            """,
            (int(snapshot_id),),
        )
        if not snapshot:
            raise ValueError("股票池快照不存在")
        snapshot["members"] = self._attach_member_names(
            self._rows(
                "SELECT * FROM stock_pool_snapshot_members WHERE snapshot_id=%s ORDER BY ordinal",
                (int(snapshot_id),),
            )
        )
        return snapshot

    def create_backtest_draft(self, snapshot_id: int, payload: Mapping[str, Any]) -> Dict[str, Any]:
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot["status"] != "sealed":
            raise ValueError("只有封存股票池快照可以进入回测")
        from app.services.backtest_workbench_service import BacktestWorkbenchService

        symbols = [str(item["symbol"]) for item in snapshot["members"]]
        request = {
            **dict(payload), "pool_snapshot_id": int(snapshot["id"]), "dataset_snapshot_id": int(snapshot["dataset_snapshot_id"]),
            "universe_snapshot_id": int(snapshot["universe_snapshot_id"]), "factor_snapshot_id": snapshot.get("factor_snapshot_id"),
            "symbols": symbols, "name": payload.get("name") or f"{snapshot['pool_name']} / Backtest Draft",
            "hypothesis": payload.get("hypothesis") or f"验证股票池 {snapshot['pool_name']} 的策略表现",
        }
        experiment = BacktestWorkbenchService(self.database).create_experiment(request)
        return {"status": "draft", "pool_snapshot": snapshot, "experiment": experiment, "symbols": symbols}

    def _generate_candidates(self, pool: Mapping[str, Any], manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
        config = dict(pool.get("config") or {})
        pool_type = str(pool["pool_type"])
        if pool_type == "factor":
            factor_snapshot_id = manifest.get("factor_snapshot_id")
            if not factor_snapshot_id:
                raise ValueError("factor 生成器缺少 factor_snapshot_id")
            factor_code = str(config.get("factor_code") or "momentum_20d")
            result = self.factors.factor_snapshot_values(int(factor_snapshot_id), factor_code=factor_code, limit=100_000)
            rows = list(result["items"])
            descending = str(config.get("direction") or "desc") != "asc"
            rows.sort(key=lambda item: (
                -(float(item.get("processed_value") or 0)) if descending else float(item.get("processed_value") or 0),
                str(item["symbol"]),
            ))
            top_n = max(1, min(int(config.get("top_n") or 20), 500))
            return [
                {
                    "symbol": str(item["symbol"]),
                    "score": float(item.get("percentile") or 0) if descending else 1.0 - float(item.get("percentile") or 0),
                    "reason": f"{item['factor_name']} {item['version_no']} 排名 {item.get('rank')}，处理值 {item.get('processed_value')}",
                    "evidence": {
                        "factor_snapshot_id": int(factor_snapshot_id), "factor_manifest_hash": result["manifest_hash"],
                        "factor_code": item["factor_code"], "factor_version": item["version_no"], "trade_date": str(item["trade_date"]),
                        "rank": item.get("rank"), "percentile": item.get("percentile"), "processed_value": item.get("processed_value"),
                        "available_at": item.get("available_at"),
                    },
                    "source_object_type": "factor_snapshot", "source_object_id": str(factor_snapshot_id),
                }
                for item in rows[:top_n]
            ]
        if pool_type == "sector":
            evidence_id = manifest.get("market_evidence_snapshot_id")
            if not evidence_id:
                raise ValueError("sector 生成器缺少 market_evidence_snapshot_id")
            sectors = {str(item) for item in (config.get("sectors") or [config.get("sector")]) if item}
            params: List[Any] = [int(evidence_id)]
            query = "SELECT * FROM limit_pool_members WHERE snapshot_id=%s AND pool_kind='up'"
            if sectors:
                query += " AND industry=ANY(%s)"
                params.append(sorted(sectors))
            query += " ORDER BY limit_times DESC NULLS LAST,seal_amount DESC NULLS LAST,symbol"
            rows = self._rows(query, params)
            top_n = max(1, min(int(config.get("top_n") or 50), 500))
            maximum = max((int(item.get("limit_times") or 1) for item in rows), default=1)
            return [
                {
                    "symbol": self._internal_symbol(item["symbol"]),
                    "score": int(item.get("limit_times") or 1) / maximum,
                    "reason": f"{item.get('industry') or '未分类'}涨停，{item.get('limit_times') or 1}板，封单 {item.get('seal_amount') or '--'}",
                    "evidence": {
                        "market_evidence_snapshot_id": int(evidence_id), "content_hash": manifest.get("market_evidence_hash"),
                        "pool_kind": item["pool_kind"], "industry": item.get("industry"), "limit_times": item.get("limit_times"),
                        "seal_amount": item.get("seal_amount"), "source_label": item["source_label"], "trade_date": manifest["trade_date"],
                    },
                    "source_object_type": "market_evidence_snapshot", "source_object_id": str(evidence_id),
                }
                for item in rows[:top_n]
            ]
        if pool_type == "event":
            evidence_id = manifest.get("market_evidence_snapshot_id")
            if not evidence_id:
                raise ValueError("event 生成器缺少 market_evidence_snapshot_id")
            keyword = str(config.get("keyword") or "").strip()
            rows = self._rows(
                "SELECT * FROM short_line_rank_rows WHERE snapshot_id=%s ORDER BY rank", (int(evidence_id),)
            )
            if keyword:
                rows = [item for item in rows if keyword in str(item.get("theme") or "") or keyword in str(item.get("status") or "")]
            top_n = max(1, min(int(config.get("top_n") or 30), 200))
            return [
                {
                    "symbol": self._internal_symbol(item["symbol"]), "score": 1.0 / max(1, int(item["rank"])),
                    "reason": f"事件主题 {item.get('theme') or '未分类'}；{item.get('status') or '榜单入选'}",
                    "evidence": {
                        "market_evidence_snapshot_id": int(evidence_id), "ranking_kind": item["ranking_kind"],
                        "rank": item["rank"], "theme": item.get("theme"), "status": item.get("status"),
                        "source_label": item["source_label"], "published_at": manifest["trade_date"],
                        "original_link": (item.get("raw_payload") or {}).get("url"),
                    },
                    "source_object_type": "short_line_rank", "source_object_id": f"{evidence_id}:{item['ranking_kind']}:{item['rank']}",
                }
                for item in rows[:top_n] if item.get("symbol")
            ]
        if pool_type in {"manual", "screener"}:
            symbols = [self._internal_symbol(item) for item in config.get("symbols", [])]
            if pool_type == "screener" and not symbols:
                symbols = [
                    str(item["symbol"]) for item in self._rows(
                        "SELECT symbol FROM universe_snapshot_members WHERE snapshot_id=%s ORDER BY symbol",
                        (int(manifest["universe_snapshot_id"]),),
                    )
                ]
            return [
                {
                    "symbol": symbol, "score": 1.0,
                    "reason": "版本化筛选条件入选" if pool_type == "screener" else "版本化手工名单入选",
                    "evidence": {"rule_hash": pool["rule_hash"], "trade_date": manifest["trade_date"], "filter_config": config},
                    "source_object_type": "stock_pool_rule", "source_object_id": str(pool["rule_id"]),
                }
                for symbol in sorted(set(symbols))
            ]
        raise ValueError("尚未实现的股票池生成器")

    def _apply_universe_filters(
        self,
        candidates: Sequence[Mapping[str, Any]],
        universe: Mapping[str, Any],
        dataset: Mapping[str, Any],
        trade_date: str,
        config: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        universe_members = {str(item["symbol"]): item for item in universe["members"]}
        boards = set(config.get("boards") or [])
        exclude_st = bool(config.get("exclude_st", True))
        exclude_suspended = bool(config.get("exclude_suspended", True))
        min_listing_days = max(0, int(config.get("min_listing_days") or 0))
        unique: Dict[str, Dict[str, Any]] = {}
        for raw in candidates:
            candidate = dict(raw)
            symbol = self._internal_symbol(candidate["symbol"])
            member = universe_members.get(symbol)
            if not member:
                continue
            flags = dict(member.get("eligibility_flags") or {})
            if not flags.get("listed", True):
                continue
            if exclude_st and flags.get("is_st"):
                continue
            if exclude_suspended and flags.get("suspended"):
                continue
            if boards and self._board(symbol) not in boards:
                continue
            candidate["symbol"] = symbol
            candidate["evidence"] = {**dict(candidate["evidence"]), "universe_snapshot_id": int(universe["id"]), "universe_manifest_hash": universe["manifest_hash"], "eligibility_flags": flags}
            unique[symbol] = candidate
        if min_listing_days and unique:
            history = self._rows(
                """
                SELECT DISTINCT ON(symbol) symbol,effective_from,listing_status,is_st,suspension_status,name
                FROM security_status_history WHERE symbol=ANY(%s) AND effective_from<=%s
                ORDER BY symbol,effective_from DESC,id DESC
                """,
                (sorted(unique), trade_date),
            )
            by_symbol = {str(item["symbol"]): item for item in history}
            cutoff = date.fromisoformat(trade_date) - timedelta(days=min_listing_days)
            unique = {
                symbol: item for symbol, item in unique.items()
                if symbol in by_symbol and by_symbol[symbol]["effective_from"] <= cutoff and by_symbol[symbol]["listing_status"] == "L"
            }
        min_price = float(config.get("min_price") or 0)
        max_price = float(config.get("max_price") or 0)
        min_turnover = float(config.get("min_turnover") or 0)
        if unique and (min_price > 0 or max_price > 0 or min_turnover > 0):
            bars = self.datasets.load_daily_bars(
                int(dataset["id"]), symbols=sorted(unique), limit=100_000
            )
            bars = [item for item in bars if str(item.get("trade_date"))[:10] == trade_date]
            by_symbol = {str(item["symbol"]): item for item in bars}
            filtered: Dict[str, Dict[str, Any]] = {}
            for symbol, item in unique.items():
                bar = by_symbol.get(symbol)
                if not bar:
                    continue
                close = float(bar.get("close") or 0)
                turnover = float(bar.get("amount") or bar.get("turnover") or 0)
                if min_price > 0 and close < min_price:
                    continue
                if max_price > 0 and close > max_price:
                    continue
                if min_turnover > 0 and turnover < min_turnover:
                    continue
                item["evidence"] = {
                    **dict(item["evidence"]),
                    "selection_bar": {"trade_date": trade_date, "close": close, "turnover": turnover},
                }
                filtered[symbol] = item
            unique = filtered
        maximum = max(1, min(int(config.get("top_n") or len(unique) or 1), 500))
        ordered = sorted(unique.values(), key=lambda item: (-float(item.get("score") or 0), str(item["symbol"])))
        return ordered[:maximum]

    @staticmethod
    def _internal_symbol(value: Any) -> str:
        text = str(value or "").strip().upper()
        if text.startswith(("SH_", "SZ_", "BJ_")):
            return text
        if "." in text:
            code, exchange = text.split(".", 1)
            return f"{exchange}_{code}"
        digits = "".join(item for item in text if item.isdigit())
        if digits.startswith(("6", "9")):
            return f"SH_{digits}"
        if digits.startswith(("4", "8")):
            return f"BJ_{digits}"
        return f"SZ_{digits}"

    @staticmethod
    def _board(symbol: str) -> str:
        if symbol.startswith("BJ_"):
            return "beijing"
        code = symbol.split("_", 1)[-1]
        if code.startswith("30"):
            return "chinext"
        if code.startswith("68"):
            return "star"
        return "main_board"

    def _row(self, query: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        rows = self._rows(query, params)
        return rows[0] if rows else None

    def _rows(self, query: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(item) for item in cursor.fetchall()]

    def _execute(self, query: str, params: Sequence[Any] = ()) -> None:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)

    @staticmethod
    def _json_dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
