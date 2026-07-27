"""Versioned, snapshot-only A-share factor research runtime."""
from __future__ import annotations

import ast
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import psycopg2.extras

from app.services.dataset_snapshot_service import DatasetSnapshotService, canonical_hash
from app.services.data_purpose import infer_data_purpose
from app.services.reference_dataset_sync_service import ReferenceDatasetSyncService, normalise_trade_date, provider_ts_code


FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input", "breakpoint",
    "globals", "locals", "vars", "getattr", "setattr", "delattr", "help", "dir",
}
FORBIDDEN_ROOTS = {
    "os", "sys", "subprocess", "socket", "requests", "httpx", "urllib", "pathlib",
    "psycopg2", "sqlalchemy", "builtins", "importlib", "shutil", "tempfile",
}
SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def calculate_forward_return_metrics(
    processed_values: pd.Series,
    quantiles: pd.Series,
    base_close: pd.Series,
    future_close: pd.Series,
    horizon: int,
) -> List[Dict[str, Any]]:
    """Calculate cross-sectional forward evidence for one already-published factor date."""
    aligned = pd.concat(
        [
            pd.to_numeric(processed_values, errors="coerce").rename("factor"),
            pd.to_numeric(quantiles, errors="coerce").rename("quantile"),
            pd.to_numeric(base_close, errors="coerce").rename("base"),
            pd.to_numeric(future_close, errors="coerce").rename("future"),
        ],
        axis=1,
    ).replace([np.inf, -np.inf], np.nan).dropna()
    aligned = aligned[(aligned["base"] > 0) & (aligned["future"] > 0)]
    if len(aligned) < 3:
        return []
    forward = aligned["future"] / aligned["base"] - 1.0
    factor_std = float(aligned["factor"].std(ddof=0))
    return_std = float(forward.std(ddof=0))
    pearson = float(aligned["factor"].corr(forward)) if factor_std > 0 and return_std > 0 else None
    # Spearman is Pearson correlation over ranks.  Computing the ranks here
    # keeps the runtime deterministic without Pandas' optional SciPy import.
    rank_ic = float(aligned["factor"].rank(method="average").corr(forward.rank(method="average"))) if factor_std > 0 and return_std > 0 else None
    quantile_returns = {
        f"Q{int(group)}": float(values.mean())
        for group, values in forward.groupby(aligned["quantile"].astype(int))
    }
    long_short = None
    if "Q5" in quantile_returns and "Q1" in quantile_returns:
        long_short = float(quantile_returns["Q5"] - quantile_returns["Q1"])
    payload = {"sample_count": int(len(aligned)), "returns": quantile_returns}
    return [
        {"metric_code": "ic", "horizon": int(horizon), "metric_value": pearson, "metric_payload": {"sample_count": int(len(aligned))}},
        {"metric_code": "rank_ic", "horizon": int(horizon), "metric_value": rank_ic, "metric_payload": {"sample_count": int(len(aligned))}},
        {"metric_code": "quantile_returns", "horizon": int(horizon), "metric_value": None, "metric_payload": payload},
        {"metric_code": "long_short_return", "horizon": int(horizon), "metric_value": long_short, "metric_payload": payload},
    ]


REFERENCE_FACTORS: Sequence[Dict[str, Any]] = (
    {
        "code": "momentum_5d", "name": "5日动量", "category": "momentum", "lookback": 6, "direction": 1,
        "description": "5 个交易日收盘价动量",
        "body": "close = data.history('close', 6)\n    return close.iloc[-1] / close.iloc[0] - 1",
    },
    {
        "code": "momentum_20d", "name": "20日动量", "category": "momentum", "lookback": 21, "direction": 1,
        "description": "20 个交易日收盘价动量",
        "body": "close = data.history('close', 21)\n    return close.iloc[-1] / close.iloc[0] - 1",
    },
    {
        "code": "reversal_5d", "name": "5日反转", "category": "reversal", "lookback": 6, "direction": 1,
        "description": "5 日动量取反，用于短期反转研究",
        "body": "close = data.history('close', 6)\n    return -(close.iloc[-1] / close.iloc[0] - 1)",
    },
    {
        "code": "volatility_20d", "name": "20日年化波动", "category": "volatility", "lookback": 21, "direction": -1,
        "description": "20 日对数收益率年化波动率",
        "body": "close = data.history('close', 21)\n    returns = np.log(close / close.shift(1))\n    return returns.std() * np.sqrt(252)",
    },
    {
        "code": "turnover_rate", "name": "换手率", "category": "liquidity", "lookback": 1, "direction": 1,
        "description": "TuShare daily_basic 当日换手率",
        "body": "return data.current('turnover_rate')",
    },
    {
        "code": "volume_ratio", "name": "量比", "category": "liquidity", "lookback": 1, "direction": 1,
        "description": "TuShare daily_basic 当日量比",
        "body": "return data.current('volume_ratio')",
    },
    {
        "code": "size_log_mv", "name": "对数总市值", "category": "size", "lookback": 1, "direction": -1,
        "description": "总市值的自然对数",
        "body": "total_mv = data.current('total_mv')\n    return np.log(total_mv.where(total_mv > 0))",
    },
    {
        "code": "earnings_yield", "name": "盈利收益率", "category": "value", "lookback": 1, "direction": 1,
        "description": "PE_TTM 的倒数，亏损公司保留缺失",
        "body": "pe = data.current('pe_ttm')\n    return 1 / pe.where(pe > 0)",
    },
    {
        "code": "book_to_price", "name": "账面市值比", "category": "value", "lookback": 1, "direction": 1,
        "description": "PB 的倒数",
        "body": "pb = data.current('pb')\n    return 1 / pb.where(pb > 0)",
    },
    {
        "code": "ma_deviation_20d", "name": "20日均线乖离", "category": "technical", "lookback": 20, "direction": 1,
        "description": "收盘价相对 20 日均线的乖离率",
        "body": "close = data.history('close', 20)\n    return close.iloc[-1] / close.mean() - 1",
    },
)


def _reference_code(item: Mapping[str, Any]) -> str:
    body = "\n".join(f"    {line.strip()}" for line in str(item["body"]).splitlines())
    return (
        "FACTOR_META = {"
        f"'name': '{item['code']}', 'category': '{item['category']}', 'frequency': 'daily', "
        f"'lookback': {int(item['lookback'])}, 'direction': {int(item['direction'])}"
        "}\n\n"
        "def calculate(context, data):\n"
        f"{body}\n"
    )


def validate_factor_python(code: str) -> Dict[str, Any]:
    """Validate the strict Factor API v1 authoring surface without executing it."""
    try:
        tree = ast.parse(str(code or ""), mode="exec")
    except SyntaxError as exc:
        return {"valid": False, "errors": [f"语法错误: {exc.msg} (line {exc.lineno})"], "meta": None}
    errors: List[str] = []
    calculate_functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "calculate"]
    meta_assignments = [
        node for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(isinstance(target, ast.Name) and target.id == "FACTOR_META" for target in getattr(node, "targets", [getattr(node, "target", None)]) if target)
    ]
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.FunctionDef) and node.name == "calculate":
            continue
        if node in meta_assignments:
            continue
        errors.append("顶层只允许 FACTOR_META 和 calculate(context, data)")
    if len(calculate_functions) != 1:
        errors.append("必须且只能定义一个 calculate(context, data)")
    elif [arg.arg for arg in calculate_functions[0].args.args] != ["context", "data"]:
        errors.append("calculate 参数必须为 (context, data)")
    if len(meta_assignments) != 1:
        errors.append("必须且只能定义一个 FACTOR_META")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
            errors.append(f"不允许的语法: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES | FORBIDDEN_ROOTS:
            errors.append(f"不允许的名称: {node.id}")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                errors.append("不允许访问 dunder 属性")
            root = node.value
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in FORBIDDEN_ROOTS:
                errors.append(f"不允许访问: {root.id}")
    meta: Optional[Dict[str, Any]] = None
    if meta_assignments:
        try:
            value_node = meta_assignments[0].value
            parsed = ast.literal_eval(value_node)
            meta = dict(parsed) if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            errors.append("FACTOR_META 必须是字面量 dict")
    if meta is not None:
        for key in ("name", "category", "frequency", "lookback", "direction"):
            if key not in meta:
                errors.append(f"FACTOR_META 缺少 {key}")
        try:
            if int(meta.get("lookback", 0)) <= 0:
                errors.append("lookback 必须大于 0")
        except (TypeError, ValueError):
            errors.append("lookback 必须是整数")
        if meta.get("direction") not in (-1, 1):
            errors.append("direction 必须为 -1 或 1")
        if meta.get("frequency") != "daily":
            errors.append("当前只支持 daily 因子")
    return {"valid": not errors, "errors": sorted(set(errors)), "meta": meta}


@dataclass(frozen=True)
class FactorContext:
    trade_date: str
    knowledge_cutoff_at: str
    dataset_snapshot_id: int
    universe_snapshot_id: int


class SnapshotFactorData:
    def __init__(
        self,
        trade_date: str,
        bars: Sequence[Mapping[str, Any]],
        valuation: Sequence[Mapping[str, Any]],
        members: Sequence[Mapping[str, Any]],
    ):
        self.trade_date = normalise_trade_date(trade_date)
        self._bars = pd.DataFrame(list(bars))
        self._valuation = pd.DataFrame(list(valuation))
        self._members = [dict(item) for item in members]
        bar_symbols = set(self._bars.get("symbol", pd.Series(dtype=str)).dropna().astype(str).tolist())
        universe_symbols = {
            str(item.get("symbol")) for item in self._members
            if bool((item.get("eligibility_flags") or {}).get("eligible_for_research", True))
        }
        self.symbols = sorted(bar_symbols & universe_symbols)
        if self._bars.empty or not self.symbols:
            raise ValueError("快照中没有可用的因子研究日线")
        self._bars["trade_date"] = pd.to_datetime(self._bars["trade_date"])
        self._bars = self._bars[self._bars["symbol"].isin(self.symbols)]
        self._bars = self._bars[self._bars["trade_date"] <= pd.Timestamp(self.trade_date)]
        self._bars = self._bars.drop_duplicates(["symbol", "trade_date"], keep="last")
        if not self._valuation.empty:
            self._valuation = self._valuation[self._valuation["symbol"].isin(self.symbols)]

    def history(self, field: str, lookback: int) -> pd.DataFrame:
        name = str(field)
        if name not in {"open", "high", "low", "close", "volume", "turnover"}:
            raise ValueError(f"未声明的 history 字段: {name}")
        days = sorted(self._bars["trade_date"].drop_duplicates().tolist())[-max(1, int(lookback)):]
        frame = self._bars[self._bars["trade_date"].isin(days)].pivot(index="trade_date", columns="symbol", values=name)
        return frame.reindex(columns=self.symbols).sort_index().astype(float)

    def current(self, field: str) -> pd.Series:
        name = str(field)
        if name in {"open", "high", "low", "close", "volume", "turnover"}:
            frame = self.history(name, 1)
            return frame.iloc[-1].reindex(self.symbols)
        if self._valuation.empty or name not in self._valuation.columns:
            raise ValueError(f"未声明或不可用的 current 字段: {name}")
        series = self._valuation.drop_duplicates("symbol", keep="last").set_index("symbol")[name]
        return pd.to_numeric(series, errors="coerce").reindex(self.symbols)

    def get_universe(self) -> List[str]:
        return list(self.symbols)

    def industries(self) -> Dict[str, Optional[str]]:
        return {str(item.get("symbol")): item.get("industry_code") for item in self._members if str(item.get("symbol")) in self.symbols}


class FactorResearchService:
    def __init__(self, database):
        self.database = database
        self.snapshot_service = DatasetSnapshotService(database)
        self.reference_service = ReferenceDatasetSyncService(database)

    def install_reference_factors(self) -> List[int]:
        version_ids: List[int] = []
        for item in REFERENCE_FACTORS:
            code = _reference_code(item)
            with self.database.get_connection() as connection:
                with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO factor_definitions
                        (factor_code, factor_name, category, description, formula, data_source,
                         update_frequency, unit, owner_name, direction, research_status, enabled)
                        VALUES (%s, %s, %s, %s, %s, 'sealed_dataset_snapshot', 'daily', NULL, 'system', %s, 'exploratory', TRUE)
                        ON CONFLICT (factor_code) DO UPDATE SET
                            factor_name = EXCLUDED.factor_name,
                            category = EXCLUDED.category,
                            description = EXCLUDED.description,
                            direction = EXCLUDED.direction,
                            data_source = EXCLUDED.data_source,
                            enabled = TRUE
                        RETURNING id
                        """,
                        (item["code"], item["name"], item["category"], item["description"], item["code"], item["direction"]),
                    )
                    definition_id = int(cursor.fetchone()["id"])
                    content_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
                    validation = validate_factor_python(code)
                    cursor.execute(
                        """
                        INSERT INTO factor_versions
                        (factor_definition_id, version_no, python_code, content_hash, declared_lookback,
                         dependencies, preprocessing, validation_status, validation_result)
                        VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (factor_definition_id, content_hash) DO UPDATE SET
                            validation_status = EXCLUDED.validation_status,
                            validation_result = EXCLUDED.validation_result
                        RETURNING id
                        """,
                        (
                            definition_id, code, content_hash, item["lookback"],
                            psycopg2.extras.Json(["daily_bars", "daily_valuation", "universe_history"]),
                            psycopg2.extras.Json({"winsorize": [0.01, 0.99], "missing": "drop", "standardize": True, "minimum_coverage": 0.8}),
                            "valid" if validation["valid"] else "invalid",
                            psycopg2.extras.Json(validation),
                        ),
                    )
                    version_id = int(cursor.fetchone()["id"])
                    cursor.execute("UPDATE factor_definitions SET active_version_id = %s WHERE id = %s", (version_id, definition_id))
                    version_ids.append(version_id)
        return version_ids

    def create_factor(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        code = str(payload.get("factor_code") or payload.get("code") or "").strip().lower()
        name = str(payload.get("factor_name") or payload.get("name") or "").strip()
        category = str(payload.get("category") or "").strip().lower()
        python_code = str(payload.get("python_code") or payload.get("code_content") or "")
        if not code or not name or not category or not python_code:
            raise ValueError("因子代码、名称、分类和 Python 代码必填")
        validation = validate_factor_python(python_code)
        meta = validation.get("meta") or {}
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT id FROM factor_definitions WHERE factor_code = %s", (code,))
                if cursor.fetchone():
                    raise ValueError("因子代码已存在，请创建新版本")
                cursor.execute(
                    """
                    INSERT INTO factor_definitions
                    (factor_code, factor_name, category, description, formula, data_source, update_frequency,
                     owner_name, direction, research_status, enabled)
                    VALUES (%s, %s, %s, %s, %s, 'sealed_dataset_snapshot', 'daily', %s, %s, 'exploratory', FALSE)
                    RETURNING id
                    """,
                    (code, name, category, payload.get("description"), code, payload.get("owner", "local"), int(meta.get("direction", 1))),
                )
                definition_id = int(cursor.fetchone()["id"])
        version = self.create_version(definition_id, {**dict(payload), "python_code": python_code})
        return {"definition_id": definition_id, "factor_code": code, "version": version}

    def create_version(self, definition_id: int, payload: Mapping[str, Any]) -> Dict[str, Any]:
        python_code = str(payload.get("python_code") or "")
        validation = validate_factor_python(python_code)
        meta = validation.get("meta") or {}
        content_hash = hashlib.sha256(python_code.encode("utf-8")).hexdigest()
        lookback = int(payload.get("declared_lookback") or meta.get("lookback") or 1)
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT COALESCE(MAX(version_no), 0) + 1 AS version_no FROM factor_versions WHERE factor_definition_id = %s", (int(definition_id),))
                version_no = int(cursor.fetchone()["version_no"])
                cursor.execute(
                    """
                    INSERT INTO factor_versions
                    (factor_definition_id, version_no, python_code, content_hash, declared_lookback,
                     dependencies, preprocessing, output_unit, validation_status, validation_result)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        int(definition_id), version_no, python_code, content_hash, lookback,
                        psycopg2.extras.Json(payload.get("dependencies") or ["daily_bars", "daily_valuation", "universe_history"]),
                        psycopg2.extras.Json(payload.get("preprocessing") or {"winsorize": [0.01, 0.99], "missing": "drop", "standardize": True, "minimum_coverage": 0.8}),
                        payload.get("output_unit"), "valid" if validation["valid"] else "invalid",
                        psycopg2.extras.Json(validation),
                    ),
                )
                version_id = int(cursor.fetchone()["id"])
                if validation["valid"]:
                    cursor.execute("UPDATE factor_definitions SET active_version_id = %s, direction = %s, enabled = TRUE WHERE id = %s", (version_id, int(meta.get("direction", 1)), int(definition_id)))
        return {"id": version_id, "version_no": version_no, "content_hash": content_hash, "validation": validation}

    def validate_version(self, version_id: int) -> Dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT python_code FROM factor_versions WHERE id = %s", (int(version_id),))
                row = cursor.fetchone()
                if not row:
                    raise ValueError("因子版本不存在")
                result = validate_factor_python(row["python_code"])
                cursor.execute(
                    "UPDATE factor_versions SET validation_status = %s, validation_result = %s WHERE id = %s",
                    ("valid" if result["valid"] else "invalid", psycopg2.extras.Json(result), int(version_id)),
                )
        return result

    def list_library(self) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT d.id, d.factor_code, d.factor_name, d.category, d.description, d.direction,
                           d.research_status, d.enabled, v.id AS active_version_id, v.version_no,
                           v.content_hash, v.validation_status, r.trade_date AS last_trade_date,
                           r.status AS publication_state, r.dataset_snapshot_id, r.universe_snapshot_id,
                           r.knowledge_cutoff_at,
                           MAX(COALESCE(mm.metric_value, m.metric_value)) FILTER (WHERE m.metric_code = 'coverage') AS coverage,
                           MAX(COALESCE(mm.metric_value, m.metric_value)) FILTER (WHERE m.metric_code = 'rank_ic' AND m.horizon = 1) AS rank_ic,
                           MAX(COALESCE(mm.metric_value, m.metric_value)) FILTER (WHERE m.metric_code = 'icir' AND m.horizon = 20) AS icir,
                           MAX(COALESCE(mm.metric_value, m.metric_value)) FILTER (WHERE m.metric_code = 'long_short_return' AND m.horizon = 20) AS long_short_return,
                           MAX(COALESCE(mm.metric_value, m.metric_value)) FILTER (WHERE m.metric_code = 'turnover') AS turnover,
                           MAX(COALESCE(mm.metric_value, m.metric_value)) FILTER (WHERE m.metric_code = 'decay') AS decay
                    FROM factor_definitions d
                    LEFT JOIN factor_versions v ON v.id = d.active_version_id
                    LEFT JOIN LATERAL (
                        SELECT * FROM factor_compute_runs cr
                        WHERE cr.factor_version_id = v.id AND cr.status = 'published'
                        ORDER BY cr.trade_date DESC, cr.id DESC LIMIT 1
                    ) r ON TRUE
                    LEFT JOIN factor_daily_metrics m ON m.compute_run_id = r.id
                    LEFT JOIN LATERAL (
                        SELECT matured.metric_value
                        FROM factor_matured_metrics matured
                        JOIN factor_metric_evaluations evaluation ON evaluation.id = matured.evaluation_id
                        WHERE matured.source_compute_run_id = r.id
                          AND matured.metric_code = m.metric_code
                          AND matured.horizon IS NOT DISTINCT FROM m.horizon
                          AND evaluation.status = 'sealed'
                        ORDER BY evaluation.knowledge_cutoff_at DESC, evaluation.id DESC LIMIT 1
                    ) mm ON TRUE
                    WHERE d.data_source = 'sealed_dataset_snapshot' AND d.active_version_id IS NOT NULL
                    GROUP BY d.id, v.id, r.id, r.trade_date, r.status, r.dataset_snapshot_id,
                             r.universe_snapshot_id, r.knowledge_cutoff_at
                    ORDER BY d.category, d.factor_code
                    """
                )
                return [dict(row) for row in cursor.fetchall()]

    def compute_factor(
        self,
        factor_version_id: int,
        trade_date: str,
        dataset_snapshot_id: int,
        universe_snapshot_id: int,
    ) -> Dict[str, Any]:
        target = normalise_trade_date(trade_date)
        version = self._version(int(factor_version_id))
        if version["validation_status"] != "valid":
            validation = self.validate_version(int(factor_version_id))
            if not validation["valid"]:
                raise ValueError("因子代码未通过验证")
        snapshot = self.snapshot_service.get_snapshot(int(dataset_snapshot_id))
        if not snapshot or snapshot.get("status") != "sealed":
            raise ValueError("因子计算只能使用已封存数据快照")
        universe = self.reference_service.get_universe_snapshot(int(universe_snapshot_id))
        if not universe or universe.get("status") != "sealed":
            raise ValueError("因子计算只能使用已封存 Universe 快照")
        cutoff = str(snapshot.get("knowledge_cutoff_at"))
        key = canonical_hash({
            "version": int(factor_version_id), "trade_date": target,
            "dataset_snapshot": int(dataset_snapshot_id), "universe_snapshot": int(universe_snapshot_id),
            "knowledge_cutoff": cutoff, "preprocessing": version.get("preprocessing") or {},
        })
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM factor_compute_runs WHERE idempotency_key = %s", (key,))
                existing = cursor.fetchone()
                if existing and existing["status"] == "published":
                    return self._run_payload(dict(existing), reused=True)
                if existing:
                    run_id = int(existing["id"])
                    cursor.execute("UPDATE factor_compute_runs SET status = 'running', started_at = NOW(), error_message = NULL WHERE id = %s", (run_id,))
                else:
                    cursor.execute(
                        """
                        INSERT INTO factor_compute_runs
                        (factor_version_id, trade_date, dataset_snapshot_id, universe_snapshot_id,
                         knowledge_cutoff_at, idempotency_key, status, started_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 'running', NOW()) RETURNING id
                        """,
                        (int(factor_version_id), target, int(dataset_snapshot_id), int(universe_snapshot_id), snapshot["knowledge_cutoff_at"], key),
                    )
                    run_id = int(cursor.fetchone()["id"])
        try:
            bars = self.snapshot_service.load_snapshot_dataset(int(dataset_snapshot_id), "daily_bars", limit=1_000_000)
            valuation = self.snapshot_service.load_snapshot_dataset(int(dataset_snapshot_id), "daily_valuation", limit=1_000_000)
            data = SnapshotFactorData(target, bars, valuation, universe.get("members") or [])
            context = FactorContext(target, cutoff, int(dataset_snapshot_id), int(universe_snapshot_id))
            raw = self._execute(version["python_code"], context, data)
            values, metric_rows = self._prepare_values_and_metrics(raw, data, version, target)
            coverage = next(item["metric_value"] for item in metric_rows if item["metric_code"] == "coverage")
            minimum_coverage = float((version.get("preprocessing") or {}).get("minimum_coverage", 0.8))
            if coverage is None or float(coverage) < minimum_coverage:
                raise ValueError(f"因子覆盖率 {float(coverage or 0):.2%} 低于质量门禁 {minimum_coverage:.2%}")
            value_hash = canonical_hash(values)
            metric_hash = canonical_hash(metric_rows)
            with self.database.get_connection() as connection:
                with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute("DELETE FROM factor_daily_values WHERE compute_run_id = %s", (run_id,))
                    cursor.execute("DELETE FROM factor_daily_metrics WHERE compute_run_id = %s", (run_id,))
                    psycopg2.extras.execute_values(
                        cursor,
                        """
                        INSERT INTO factor_daily_values
                        (factor_version_id, compute_run_id, trade_date, symbol, raw_value, processed_value,
                         rank, percentile, quantile, quality_flags, available_at)
                        VALUES %s
                        """,
                        [
                            (
                                int(factor_version_id), run_id, target, item["symbol"], item["raw_value"],
                                item["processed_value"], item["rank"], item["percentile"], item["quantile"],
                                psycopg2.extras.Json(item["quality_flags"]), snapshot["knowledge_cutoff_at"],
                            )
                            for item in values
                        ],
                    )
                    psycopg2.extras.execute_values(
                        cursor,
                        """
                        INSERT INTO factor_daily_metrics
                        (compute_run_id, factor_version_id, trade_date, metric_code, horizon,
                         metric_value, metric_payload, pending_reason)
                        VALUES %s
                        """,
                        [
                            (
                                run_id, int(factor_version_id), target, item["metric_code"], item.get("horizon"),
                                item.get("metric_value"), psycopg2.extras.Json(item.get("metric_payload") or {}),
                                item.get("pending_reason"),
                            )
                            for item in metric_rows
                        ],
                    )
                    missing = len([item for item in values if item["processed_value"] is None])
                    cursor.execute(
                        """
                        UPDATE factor_compute_runs SET status = 'published', input_hash = %s, value_hash = %s,
                            metric_hash = %s, input_count = %s, output_count = %s, missing_count = %s,
                            finished_at = NOW() WHERE id = %s RETURNING *
                        """,
                        (canonical_hash({"bars": len(bars), "valuation": len(valuation), "symbols": data.symbols}), value_hash, metric_hash, len(data.symbols), len(values) - missing, missing, run_id),
                    )
                    return self._run_payload(dict(cursor.fetchone()))
        except Exception as exc:
            with self.database.get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE factor_compute_runs SET status = 'failed', error_message = %s, finished_at = NOW() WHERE id = %s", (str(exc), run_id))
            raise

    def run_daily_schedule(
        self,
        trade_date: str,
        dataset_snapshot_id: int,
        universe_snapshot_id: int,
        _lock_held: bool = False,
    ) -> Dict[str, Any]:
        target = normalise_trade_date(trade_date)
        lock_key = f"factor_daily:{target}:{dataset_snapshot_id}:{universe_snapshot_id}"
        if not _lock_held:
            guard = self.database.get_connection()
            guard_cursor = guard.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            guard_cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS acquired", (lock_key,))
            if not guard_cursor.fetchone()["acquired"]:
                guard_cursor.close()
                guard.close()
                return {"status": "locked", "trade_date": target}
            try:
                return self.run_daily_schedule(target, dataset_snapshot_id, universe_snapshot_id, _lock_held=True)
            finally:
                guard_cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", (lock_key,))
                guard.commit()
                guard_cursor.close()
                guard.close()
        version_ids = self.install_reference_factors()
        schedule_key = canonical_hash({"trade_date": target, "dataset_snapshot_id": int(dataset_snapshot_id), "universe_snapshot_id": int(universe_snapshot_id), "versions": version_ids})
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM factor_schedule_runs WHERE idempotency_key = %s", (schedule_key,))
                existing = cursor.fetchone()
                if existing and existing["status"] == "sealed":
                    return {"status": "sealed", "factor_snapshot_id": existing["factor_snapshot_id"], "reused": True}
                if existing:
                    schedule_run_id = int(existing["id"])
                    cursor.execute("UPDATE factor_schedule_runs SET status = 'running', started_at = NOW(), finished_at = NULL WHERE id = %s", (schedule_run_id,))
                else:
                    cursor.execute(
                        """
                        INSERT INTO factor_schedule_runs
                        (trade_date, dataset_snapshot_id, universe_snapshot_id, idempotency_key, status)
                        VALUES (%s, %s, %s, %s, 'running') RETURNING id
                        """,
                        (target, int(dataset_snapshot_id), int(universe_snapshot_id), schedule_key),
                    )
                    schedule_run_id = int(cursor.fetchone()["id"])
        runs: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        for version_id in version_ids:
            try:
                runs.append(self.compute_factor(version_id, target, int(dataset_snapshot_id), int(universe_snapshot_id)))
            except Exception as exc:
                errors.append({"factor_version_id": version_id, "error": str(exc)})
        if errors:
            with self.database.get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE factor_schedule_runs SET status = 'partial', result = %s, error_message = %s, finished_at = NOW() WHERE id = %s",
                        (psycopg2.extras.Json(_jsonable({"runs": runs, "errors": errors})), f"{len(errors)} 个因子失败", schedule_run_id),
                    )
            return {"status": "partial", "runs": runs, "errors": errors}
        factor_snapshot = self._seal_factor_snapshot(target, int(dataset_snapshot_id), int(universe_snapshot_id), runs)
        self._store_correlations(target, int(universe_snapshot_id), runs)
        maturity = self.mature_pending_metrics(int(dataset_snapshot_id))
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE factor_schedule_runs SET status = 'sealed', factor_snapshot_id = %s, result = %s, finished_at = NOW() WHERE id = %s",
                    (factor_snapshot["id"], psycopg2.extras.Json(_jsonable({"runs": runs, "factor_snapshot": factor_snapshot, "maturity": maturity})), schedule_run_id),
                )
        return {"status": "sealed", "factor_snapshot": factor_snapshot, "runs": runs, "maturity": maturity, "reused": False}

    def mature_pending_metrics(self, evaluation_dataset_snapshot_id: int) -> Dict[str, Any]:
        """Append forward-return evidence from a later sealed snapshot; never mutate source metrics."""
        snapshot = self.snapshot_service.get_snapshot(int(evaluation_dataset_snapshot_id))
        if not snapshot or snapshot.get("status") != "sealed":
            raise ValueError("因子成熟评估只能使用已封存数据快照")
        bars = self.snapshot_service.load_snapshot_dataset(int(evaluation_dataset_snapshot_id), "daily_bars", limit=2_000_000)
        frame = pd.DataFrame(bars)
        if frame.empty:
            return {"status": "empty", "evaluated": 0, "metrics": 0}
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.drop_duplicates(["symbol", "trade_date"], keep="last")
        close = frame.pivot(index="trade_date", columns="symbol", values="close").sort_index()
        available_dates = list(close.index)
        cutoff = snapshot["knowledge_cutoff_at"]
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT r.id, r.factor_version_id, r.trade_date
                    FROM factor_compute_runs r
                    JOIN factor_daily_metrics m ON m.compute_run_id = r.id
                    WHERE r.status = 'published' AND m.pending_reason IS NOT NULL
                      AND r.trade_date < %s
                    ORDER BY r.trade_date, r.id
                    """,
                    (available_dates[-1].date(),),
                )
                candidates = [dict(row) for row in cursor.fetchall()]
        evaluated = 0
        metric_count = 0
        for run in candidates:
            source_date = pd.Timestamp(run["trade_date"])
            future_dates = [item for item in available_dates if item > source_date]
            if source_date not in close.index or not future_dates:
                continue
            with self.database.get_connection() as connection:
                with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(
                        "SELECT symbol, processed_value, quantile FROM factor_daily_values WHERE compute_run_id = %s",
                        (int(run["id"]),),
                    )
                    value_rows = cursor.fetchall()
            processed = pd.Series({row["symbol"]: row["processed_value"] for row in value_rows}, dtype=float)
            quantiles = pd.Series({row["symbol"]: row["quantile"] for row in value_rows}, dtype=float)
            metrics: List[Dict[str, Any]] = []
            for horizon in (1, 5, 20):
                if len(future_dates) < horizon:
                    continue
                metrics.extend(
                    calculate_forward_return_metrics(
                        processed,
                        quantiles,
                        close.loc[source_date],
                        close.loc[future_dates[horizon - 1]],
                        horizon,
                    )
                )
            if not metrics:
                continue
            key = canonical_hash({"source_compute_run_id": int(run["id"]), "evaluation_dataset_snapshot_id": int(evaluation_dataset_snapshot_id)})
            result_hash = canonical_hash(metrics)
            with self.database.get_connection() as connection:
                with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute("SELECT id, status FROM factor_metric_evaluations WHERE idempotency_key = %s", (key,))
                    existing = cursor.fetchone()
                    if existing and existing["status"] == "sealed":
                        continue
                    if existing:
                        evaluation_id = int(existing["id"])
                        cursor.execute("DELETE FROM factor_matured_metrics WHERE evaluation_id = %s", (evaluation_id,))
                    else:
                        cursor.execute(
                            """
                            INSERT INTO factor_metric_evaluations
                            (source_compute_run_id, evaluation_dataset_snapshot_id, knowledge_cutoff_at, idempotency_key, status)
                            VALUES (%s, %s, %s, %s, 'running') RETURNING id
                            """,
                            (int(run["id"]), int(evaluation_dataset_snapshot_id), cutoff, key),
                        )
                        evaluation_id = int(cursor.fetchone()["id"])
                    psycopg2.extras.execute_values(
                        cursor,
                        """
                        INSERT INTO factor_matured_metrics
                        (evaluation_id, source_compute_run_id, factor_version_id, factor_trade_date,
                         metric_code, horizon, metric_value, metric_payload) VALUES %s
                        """,
                        [
                            (
                                evaluation_id, int(run["id"]), int(run["factor_version_id"]), run["trade_date"],
                                item["metric_code"], item["horizon"], item.get("metric_value"),
                                psycopg2.extras.Json(item.get("metric_payload") or {}),
                            )
                            for item in metrics
                        ],
                    )
                    cursor.execute(
                        "UPDATE factor_metric_evaluations SET status = 'sealed', result_hash = %s, sealed_at = NOW() WHERE id = %s",
                        (result_hash, evaluation_id),
                    )
            evaluated += 1
            metric_count += len(metrics)
        return {"status": "sealed", "evaluated": evaluated, "metrics": metric_count, "evaluation_dataset_snapshot_id": int(evaluation_dataset_snapshot_id)}

    def list_runs(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT r.*, d.factor_code, d.factor_name, v.version_no
                    FROM factor_compute_runs r
                    JOIN factor_versions v ON v.id = r.factor_version_id
                    JOIN factor_definitions d ON d.id = v.factor_definition_id
                    ORDER BY r.created_at DESC LIMIT %s
                    """,
                    (max(1, min(int(limit), 500)),),
                )
                return [dict(row) for row in cursor.fetchall()]

    def factor_metrics(self, factor_definition_id: int) -> Dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM factor_definitions WHERE id = %s", (int(factor_definition_id),))
                definition = cursor.fetchone()
                if not definition:
                    raise ValueError("因子不存在")
                cursor.execute(
                    """
                    SELECT r.id AS compute_run_id, r.trade_date, r.dataset_snapshot_id, r.universe_snapshot_id,
                           r.knowledge_cutoff_at, r.factor_version_id, v.version_no, m.metric_code, m.horizon,
                           COALESCE(mm.metric_value, m.metric_value) AS metric_value,
                           COALESCE(mm.metric_payload, m.metric_payload) AS metric_payload,
                           CASE WHEN mm.evaluation_id IS NULL THEN m.pending_reason ELSE NULL END AS pending_reason
                    FROM factor_compute_runs r
                    JOIN factor_versions v ON v.id = r.factor_version_id
                    LEFT JOIN factor_daily_metrics m ON m.compute_run_id = r.id
                    LEFT JOIN LATERAL (
                        SELECT matured.evaluation_id, matured.metric_value, matured.metric_payload
                        FROM factor_matured_metrics matured
                        JOIN factor_metric_evaluations evaluation ON evaluation.id = matured.evaluation_id
                        WHERE matured.source_compute_run_id = r.id
                          AND matured.metric_code = m.metric_code
                          AND matured.horizon IS NOT DISTINCT FROM m.horizon
                          AND evaluation.status = 'sealed'
                        ORDER BY evaluation.knowledge_cutoff_at DESC, evaluation.id DESC LIMIT 1
                    ) mm ON TRUE
                    WHERE v.factor_definition_id = %s AND r.status = 'published'
                    ORDER BY r.trade_date, m.metric_code, m.horizon
                    """,
                    (int(factor_definition_id),),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        return {"factor": dict(definition), "metrics": rows}

    def factor_values(self, factor_definition_id: int, limit: int = 500, offset: int = 0) -> Dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT dv.trade_date, dv.symbol, dv.raw_value, dv.processed_value, dv.rank,
                           dv.percentile, dv.quantile, dv.quality_flags, dv.compute_run_id,
                           dv.factor_version_id, cr.dataset_snapshot_id, cr.universe_snapshot_id,
                           cr.knowledge_cutoff_at
                    FROM factor_daily_values dv
                    JOIN factor_versions v ON v.id = dv.factor_version_id
                    JOIN factor_compute_runs cr ON cr.id = dv.compute_run_id
                    WHERE v.factor_definition_id = %s AND cr.status = 'published'
                    ORDER BY dv.trade_date DESC, dv.rank NULLS LAST, dv.symbol
                    LIMIT %s OFFSET %s
                    """,
                    (int(factor_definition_id), max(1, min(int(limit), 5000)), max(0, int(offset))),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        for row in rows:
            try:
                row["symbol"] = provider_ts_code(row.get("symbol"))
            except ValueError:
                # Preserve an invalid stored value for visible diagnosis instead
                # of hiding the row or inventing a security identity.
                pass
        return {"items": rows, "limit": limit, "offset": offset}

    def get_factor_snapshot(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT s.*, d.name AS dataset_snapshot_name
                    FROM factor_snapshots s
                    LEFT JOIN dataset_snapshots d ON d.id = s.dataset_snapshot_id
                    WHERE s.id = %s
                    """,
                    (int(snapshot_id),),
                )
                snapshot = cursor.fetchone()
                if not snapshot:
                    return None
                cursor.execute(
                    """
                    SELECT i.factor_version_id, i.compute_run_id, i.value_hash, i.metric_hash,
                           d.factor_code, d.factor_name, v.version_no
                    FROM factor_snapshot_items i
                    JOIN factor_versions v ON v.id = i.factor_version_id
                    JOIN factor_definitions d ON d.id = v.factor_definition_id
                    WHERE i.snapshot_id = %s ORDER BY d.factor_code
                    """,
                    (int(snapshot_id),),
                )
                items = [dict(row) for row in cursor.fetchall()]
        result = {**dict(snapshot), "items": items}
        result["data_purpose"] = infer_data_purpose(
            result.get("name"),
            result.get("dataset_snapshot_name"),
        )
        return result

    def list_factor_snapshots(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT s.*, d.name AS dataset_snapshot_name,
                           COUNT(i.factor_version_id)::INTEGER AS factor_count
                    FROM factor_snapshots s
                    LEFT JOIN factor_snapshot_items i ON i.snapshot_id = s.id
                    LEFT JOIN dataset_snapshots d ON d.id = s.dataset_snapshot_id
                    GROUP BY s.id, d.name
                    ORDER BY s.trade_date DESC, s.id DESC LIMIT %s
                    """,
                    (max(1, min(int(limit), 200)),),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        for row in rows:
            row["data_purpose"] = infer_data_purpose(
                row.get("name"),
                row.get("dataset_snapshot_name"),
            )
        return rows

    def factor_snapshot_values(self, snapshot_id: int, factor_code: Optional[str] = None, limit: int = 5000) -> Dict[str, Any]:
        snapshot = self.get_factor_snapshot(int(snapshot_id))
        if not snapshot or snapshot.get("status") != "sealed":
            raise ValueError("只能读取已封存因子快照")
        clauses = ["i.snapshot_id = %s"]
        params: List[Any] = [int(snapshot_id)]
        if factor_code:
            clauses.append("d.factor_code = %s")
            params.append(str(factor_code))
        params.append(max(1, min(int(limit), 100_000)))
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT d.factor_code, d.factor_name, v.version_no, values.trade_date, values.available_at, values.symbol,
                           values.raw_value, values.processed_value, values.rank, values.percentile,
                           values.quantile, values.quality_flags, values.compute_run_id
                    FROM factor_snapshot_items i
                    JOIN factor_versions v ON v.id = i.factor_version_id
                    JOIN factor_definitions d ON d.id = v.factor_definition_id
                    JOIN factor_daily_values values ON values.compute_run_id = i.compute_run_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY d.factor_code, values.rank NULLS LAST, values.symbol LIMIT %s
                    """,
                    params,
                )
                rows = [dict(row) for row in cursor.fetchall()]
        return {
            "snapshot_id": int(snapshot_id),
            "manifest_hash": snapshot.get("manifest_hash"),
            "dataset_snapshot_id": snapshot.get("dataset_snapshot_id"),
            "universe_snapshot_id": snapshot.get("universe_snapshot_id"),
            "knowledge_cutoff_at": snapshot.get("knowledge_cutoff_at"),
            "items": rows,
        }

    def list_correlations(self, trade_date: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if trade_date:
            clauses.append("c.trade_date = %s")
            params.append(normalise_trade_date(trade_date))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 5000)))
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT c.trade_date, c.factor_version_id_a, da.factor_code AS factor_code_a,
                           c.factor_version_id_b, db.factor_code AS factor_code_b, c.window_days,
                           c.correlation, c.universe_snapshot_id
                    FROM factor_correlations c
                    JOIN factor_versions va ON va.id = c.factor_version_id_a
                    JOIN factor_definitions da ON da.id = va.factor_definition_id
                    JOIN factor_versions vb ON vb.id = c.factor_version_id_b
                    JOIN factor_definitions db ON db.id = vb.factor_definition_id
                    {where}
                    ORDER BY c.trade_date DESC, da.factor_code, db.factor_code LIMIT %s
                    """,
                    params,
                )
                return [dict(row) for row in cursor.fetchall()]

    def create_protocol(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        required = ("name", "hypothesis", "universe_code", "benchmark_code", "train_start", "train_end", "validation_start", "validation_end", "oos_start", "oos_end")
        if any(not payload.get(key) for key in required):
            raise ValueError("因子研究协议缺少必填字段")
        content_hash = canonical_hash({key: payload.get(key) for key in sorted(payload)})
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO factor_research_protocols
                    (name, hypothesis, universe_code, benchmark_code, train_start, train_end,
                     validation_start, validation_end, oos_start, oos_end, embargo_days,
                     forward_horizons, cost_model, thresholds, content_hash, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'sealed')
                    ON CONFLICT (content_hash) DO UPDATE SET name = EXCLUDED.name RETURNING *
                    """,
                    (
                        payload["name"], payload["hypothesis"], payload["universe_code"], payload["benchmark_code"],
                        payload["train_start"], payload["train_end"], payload["validation_start"], payload["validation_end"],
                        payload["oos_start"], payload["oos_end"], int(payload.get("embargo_days", 0)),
                        psycopg2.extras.Json(payload.get("forward_horizons") or [1, 5, 20]),
                        psycopg2.extras.Json(payload.get("cost_model") or {}), psycopg2.extras.Json(payload.get("thresholds") or {}), content_hash,
                    ),
                )
                return dict(cursor.fetchone())

    def create_evaluation(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        label = str(payload.get("sample_label") or "")
        if label not in {"train", "validation", "out_of_sample"}:
            raise ValueError("sample_label 必须为 train/validation/out_of_sample")
        status = str(payload.get("status") or "pending")
        if status == "passed" and label != "out_of_sample":
            raise ValueError("非样本外评估不能作为 paper_eligible 通过证据")
        if status == "passed" and (
            not payload.get("factor_snapshot_id")
            or not payload.get("selection_rationale")
            or not payload.get("rejected_variants")
            or not payload.get("metrics")
        ):
            raise ValueError("样本外通过必须绑定封存快照、指标、选择理由和被拒候选")
        result_hash = canonical_hash(dict(payload))
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO factor_evaluation_runs
                    (protocol_id, factor_version_id, factor_snapshot_id, sample_label, status,
                     metrics, selection_rationale, rejected_variants, result_hash)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
                    """,
                    (
                        int(payload["protocol_id"]), int(payload["factor_version_id"]), payload.get("factor_snapshot_id"),
                        label, status, psycopg2.extras.Json(payload.get("metrics") or {}), payload.get("selection_rationale"),
                        psycopg2.extras.Json(payload.get("rejected_variants") or []), result_hash,
                    ),
                )
                return dict(cursor.fetchone())

    def promote_factor(self, factor_definition_id: int, evaluation_id: int) -> Dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT evaluation.*, version.factor_definition_id, snapshot.status AS snapshot_status,
                           protocol.status AS protocol_status
                    FROM factor_evaluation_runs evaluation
                    JOIN factor_versions version ON version.id = evaluation.factor_version_id
                    JOIN factor_research_protocols protocol ON protocol.id = evaluation.protocol_id
                    LEFT JOIN factor_snapshots snapshot ON snapshot.id = evaluation.factor_snapshot_id
                    WHERE evaluation.id = %s
                    """,
                    (int(evaluation_id),),
                )
                evidence = cursor.fetchone()
                if not evidence or int(evidence["factor_definition_id"]) != int(factor_definition_id):
                    raise ValueError("晋级证据与因子不匹配")
                if (
                    evidence["sample_label"] != "out_of_sample"
                    or evidence["status"] != "passed"
                    or evidence["snapshot_status"] != "sealed"
                    or evidence["protocol_status"] != "sealed"
                    or not evidence["selection_rationale"]
                    or not evidence["rejected_variants"]
                    or not evidence["metrics"]
                ):
                    raise ValueError("缺少独立封存的样本外晋级证据")
                cursor.execute(
                    "UPDATE factor_definitions SET research_status = 'paper_eligible' WHERE id = %s RETURNING id, factor_code, research_status",
                    (int(factor_definition_id),),
                )
                return dict(cursor.fetchone())

    def _version(self, version_id: int) -> Dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT v.*, d.factor_code, d.factor_name, d.category, d.direction
                    FROM factor_versions v JOIN factor_definitions d ON d.id = v.factor_definition_id
                    WHERE v.id = %s
                    """,
                    (int(version_id),),
                )
                row = cursor.fetchone()
        if not row:
            raise ValueError("因子版本不存在")
        return dict(row)

    def _execute(self, code: str, context: FactorContext, data: SnapshotFactorData) -> pd.Series:
        validation = validate_factor_python(code)
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))
        namespace: Dict[str, Any] = {"__builtins__": SAFE_BUILTINS, "np": np, "pd": pd}
        exec(compile(code, "<factor-version>", "exec"), namespace, namespace)
        result = namespace["calculate"](context, data)
        if isinstance(result, Mapping):
            result = pd.Series(dict(result))
        if not isinstance(result, pd.Series):
            raise ValueError("calculate 必须返回以证券代码为索引的 pandas.Series")
        result.index = result.index.astype(str)
        return pd.to_numeric(result, errors="coerce").reindex(data.symbols)

    def _prepare_values_and_metrics(
        self,
        raw: pd.Series,
        data: SnapshotFactorData,
        version: Mapping[str, Any],
        trade_date: str,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        raw = raw.replace([np.inf, -np.inf], np.nan).reindex(data.symbols)
        valid = raw.dropna().astype(float)
        preprocessing = dict(version.get("preprocessing") or {})
        processed = valid.copy()
        outlier_rate = 0.0
        winsorized_symbols: set[str] = set()
        bounds = preprocessing.get("winsorize") or [0.01, 0.99]
        if len(processed) >= 2 and isinstance(bounds, (list, tuple)) and len(bounds) == 2:
            lower = float(processed.quantile(float(bounds[0])))
            upper = float(processed.quantile(float(bounds[1])))
            outliers = (processed < lower) | (processed > upper)
            winsorized_symbols = set(processed.index[outliers].astype(str))
            outlier_rate = float(outliers.mean())
            processed = processed.clip(lower, upper)
        if preprocessing.get("standardize", True) and len(processed) >= 2:
            std = float(processed.std(ddof=0))
            processed = (processed - float(processed.mean())) / std if std > 0 else processed * 0
        direction = int(version.get("direction") or 1)
        ranks = processed.rank(method="first", ascending=direction < 0).astype(int)
        percentile = processed.rank(method="average", pct=True, ascending=direction > 0)
        quantile = np.ceil(percentile * 5).clip(1, 5).astype(int)
        values: List[Dict[str, Any]] = []
        for symbol in data.symbols:
            raw_value = raw.get(symbol)
            processed_value = processed.get(symbol)
            missing = pd.isna(processed_value)
            values.append({
                "symbol": symbol,
                "raw_value": None if pd.isna(raw_value) else float(raw_value),
                "processed_value": None if missing else float(processed_value),
                "rank": None if missing else int(ranks[symbol]),
                "percentile": None if missing else float(percentile[symbol]),
                "quantile": None if missing else int(quantile[symbol]),
                "quality_flags": {"missing": bool(missing), "winsorized": symbol in winsorized_symbols},
            })
        coverage = float(len(valid) / len(data.symbols)) if data.symbols else 0.0
        distribution = {
            "coverage": coverage,
            "missing_rate": 1.0 - coverage,
            "outlier_rate": outlier_rate,
            "mean": float(valid.mean()) if len(valid) else None,
            "std": float(valid.std(ddof=0)) if len(valid) else None,
            "skewness": float(valid.skew()) if len(valid) >= 3 else None,
            "kurtosis": float(valid.kurt()) if len(valid) >= 4 else None,
        }
        metrics: List[Dict[str, Any]] = [
            {"metric_code": code, "metric_value": value, "metric_payload": {}}
            for code, value in distribution.items()
        ]
        industry_map = data.industries()
        industry_payload: Dict[str, Optional[float]] = {}
        if len(processed):
            grouped: Dict[str, List[float]] = {}
            for symbol, value in processed.items():
                grouped.setdefault(str(industry_map.get(symbol) or "unknown"), []).append(float(value))
            industry_payload = {key: float(np.mean(items)) for key, items in grouped.items()}
        metrics.append({"metric_code": "industry_exposure", "metric_value": None, "metric_payload": industry_payload})
        try:
            size = np.log(data.current("total_mv").where(lambda item: item > 0))
            aligned = pd.concat([processed.rename("factor"), size.rename("size")], axis=1).dropna()
            size_exposure = float(aligned.corr().iloc[0, 1]) if len(aligned) >= 3 else None
        except (ValueError, TypeError):
            size_exposure = None
        metrics.append({"metric_code": "size_exposure", "metric_value": size_exposure, "metric_payload": {}})
        pending_reason = f"{trade_date} 快照不包含成熟的未来收益，指标待后续交易日封存后追加评估"
        for horizon in (1, 5, 20):
            for code in ("ic", "rank_ic", "quantile_returns", "long_short_return"):
                metrics.append({"metric_code": code, "horizon": horizon, "metric_value": None, "metric_payload": {}, "pending_reason": pending_reason})
        for code in ("icir", "turnover", "rank_autocorrelation", "decay"):
            metrics.append({"metric_code": code, "horizon": 20 if code == "icir" else None, "metric_value": None, "metric_payload": {}, "pending_reason": "至少需要两个已成熟交易日"})
        return values, metrics

    def _seal_factor_snapshot(self, trade_date: str, dataset_snapshot_id: int, universe_snapshot_id: int, runs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        items = sorted(
            [
                {
                    "factor_version_id": int(item["factor_version_id"]),
                    "compute_run_id": int(item["id"]),
                    "value_hash": item["value_hash"],
                    "metric_hash": item["metric_hash"],
                }
                for item in runs
            ],
            key=lambda item: item["factor_version_id"],
        )
        manifest_hash = canonical_hash(items)
        snapshot = self.snapshot_service.get_snapshot(dataset_snapshot_id) or {}
        name = f"factor-daily-{trade_date}-{manifest_hash[:12]}"
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO factor_snapshots
                    (name, trade_date, dataset_snapshot_id, universe_snapshot_id, knowledge_cutoff_at, status)
                    VALUES (%s, %s, %s, %s, %s, 'draft')
                    ON CONFLICT (name) DO NOTHING RETURNING id
                    """,
                    (name, trade_date, dataset_snapshot_id, universe_snapshot_id, snapshot["knowledge_cutoff_at"]),
                )
                created = cursor.fetchone()
                if created:
                    snapshot_id = int(created["id"])
                    psycopg2.extras.execute_values(
                        cursor,
                        """
                        INSERT INTO factor_snapshot_items
                        (snapshot_id, factor_version_id, compute_run_id, value_hash, metric_hash) VALUES %s
                        """,
                        [(snapshot_id, item["factor_version_id"], item["compute_run_id"], item["value_hash"], item["metric_hash"]) for item in items],
                    )
                    cursor.execute("UPDATE factor_snapshots SET status = 'sealed', manifest_hash = %s, sealed_at = NOW() WHERE id = %s", (manifest_hash, snapshot_id))
                else:
                    cursor.execute("SELECT id FROM factor_snapshots WHERE name = %s", (name,))
                    snapshot_id = int(cursor.fetchone()["id"])
        return self.get_factor_snapshot(snapshot_id) or {}

    def _store_correlations(self, trade_date: str, universe_snapshot_id: int, runs: Sequence[Mapping[str, Any]]) -> None:
        series: Dict[int, pd.Series] = {}
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                for run in runs:
                    cursor.execute("SELECT symbol, processed_value FROM factor_daily_values WHERE compute_run_id = %s", (int(run["id"]),))
                    rows = cursor.fetchall()
                    series[int(run["factor_version_id"])] = pd.Series({row["symbol"]: row["processed_value"] for row in rows}, dtype=float)
                values = []
                ids = sorted(series)
                for index, left in enumerate(ids):
                    for right in ids[index:]:
                        aligned = pd.concat([series[left], series[right]], axis=1).dropna()
                        correlation = float(aligned.corr().iloc[0, 1]) if len(aligned) >= 3 else None
                        values.append((trade_date, left, right, 1, correlation, universe_snapshot_id))
                if values:
                    psycopg2.extras.execute_values(
                        cursor,
                        """
                        INSERT INTO factor_correlations
                        (trade_date, factor_version_id_a, factor_version_id_b, window_days, correlation, universe_snapshot_id)
                        VALUES %s ON CONFLICT DO NOTHING
                        """,
                        values,
                    )

    @staticmethod
    def _run_payload(row: Mapping[str, Any], reused: bool = False) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "factor_version_id": int(row["factor_version_id"]),
            "trade_date": str(row["trade_date"]),
            "dataset_snapshot_id": int(row["dataset_snapshot_id"]),
            "universe_snapshot_id": int(row["universe_snapshot_id"]),
            "knowledge_cutoff_at": row["knowledge_cutoff_at"],
            "status": row["status"],
            "value_hash": row.get("value_hash"),
            "metric_hash": row.get("metric_hash"),
            "input_count": int(row.get("input_count") or 0),
            "output_count": int(row.get("output_count") or 0),
            "missing_count": int(row.get("missing_count") or 0),
            "error_message": row.get("error_message"),
            "reused": reused,
        }
