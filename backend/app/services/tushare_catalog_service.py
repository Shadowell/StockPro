"""TuShare 5,000-credit endpoint catalogue and post-close market evidence.

The catalogue intentionally keeps raw endpoint payloads separate from the
normalised research datasets.  That makes an entitlement change, an upstream
schema change or a new endpoint visible without silently changing a factor or
backtest input.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import pandas as pd
import psycopg2.extras

from app.core.config import settings
from app.services.tushare_provider import TushareFirstDataProvider, market_data_provider


TUSHARE_WCT_BASE = "https://tushare.pro/wctapi/documents"


@dataclass(frozen=True)
class EndpointDefinition:
    code: str
    module: str
    name: str
    schedule_kind: str
    storage_dataset: str
    document_id: int
    required_credits: int = 5000
    requires_independent_authorization: bool = False
    baseline_state: str = "eligible"

    @property
    def contract_url(self) -> str:
        return f"{TUSHARE_WCT_BASE}/{self.document_id}.md"


def _specs(
    module: str,
    schedule_kind: str,
    storage_dataset: str,
    values: Iterable[Tuple[str, str, int]],
) -> List[EndpointDefinition]:
    return [
        EndpointDefinition(
            code=code,
            module=module,
            name=name,
            schedule_kind=schedule_kind,
            storage_dataset=storage_dataset,
            document_id=document_id,
        )
        for code, name, document_id in values
    ]


CATALOG: Tuple[EndpointDefinition, ...] = tuple(
    _specs(
        "reference_calendar",
        "monthly_or_change",
        "reference_master",
        [
            ("stock_basic", "股票列表", 25),
            ("stock_company", "上市公司基本信息", 112),
            ("namechange", "股票曾用名", 100),
            ("trade_cal", "交易日历", 26),
            ("new_share", "IPO 新股上市", 123),
        ],
    )
    + _specs(
        "price_valuation",
        "daily_after_close",
        "price_valuation",
        [
            ("daily", "A 股日线", 27),
            ("weekly", "A 股周线", 144),
            ("monthly", "A 股月线", 145),
            ("adj_factor", "复权因子", 28),
            ("daily_basic", "每日指标", 32),
            ("bak_daily", "备用行情", 255),
            ("suspend_d", "每日停复牌", 214),
            ("stk_limit", "每日涨跌停价格", 183),
        ],
    )
    + _specs(
        "financial_disclosure",
        "disclosure_or_quarterly",
        "financial_disclosure",
        [
            ("income", "利润表", 33),
            ("balancesheet", "资产负债表", 36),
            ("cashflow", "现金流量表", 44),
            ("fina_indicator", "财务指标", 79),
            ("fina_audit", "财务审计意见", 80),
            ("fina_mainbz", "主营业务构成", 81),
            ("forecast", "业绩预告", 45),
            ("express", "业绩快报", 46),
            ("dividend", "分红送股", 103),
            ("disclosure_date", "财报披露日期", 162),
        ],
    )
    + _specs(
        "index_industry",
        "daily_after_close",
        "index_industry",
        [
            ("index_basic", "指数基础信息", 94),
            ("index_daily", "指数日线", 95),
            ("index_weekly", "指数周线", 171),
            ("index_monthly", "指数月线", 172),
            ("index_dailybasic", "指数每日指标", 128),
            ("index_weight", "指数成分和权重", 96),
            ("index_classify", "申万行业分类", 181),
            ("index_member_all", "申万行业成分", 335),
            ("sw_daily", "申万行业日线", 327),
            ("ci_daily", "中信行业日线", 308),
            ("ci_index_member", "中信行业成分", 373),
            ("daily_info", "沪深市场每日交易统计", 215),
            ("sz_daily_info", "深圳市场每日交易情况", 268),
        ],
    )
    + _specs(
        "capital_flow_dragon_tiger",
        "daily_after_close",
        "capital_flow",
        [
            ("moneyflow", "个股资金流向", 170),
            ("moneyflow_hsgt", "沪深港通资金流向", 47),
            ("hsgt_top10", "沪深股通十大成交股", 48),
            ("ggt_daily", "港股通每日成交统计", 196),
            ("ggt_top10", "港股通十大成交股", 49),
            ("top_list", "龙虎榜每日统计", 106),
            ("top_inst", "龙虎榜机构交易单", 107),
            ("moneyflow_ind_dc", "东财板块资金流", 344),
            ("moneyflow_mkt_dc", "东财大盘资金流", 345),
            ("moneyflow_dc", "东财个股资金流", 349),
        ],
    )
    + _specs(
        "limit_up_ecology",
        "daily_after_close",
        "market_evidence",
        [
            ("limit_list_d", "涨跌停和炸板", 298),
            ("kpl_list", "开盘啦榜单", 347),
        ],
    )
    + _specs(
        "fund_etf_convertible",
        "daily_after_close",
        "fund_etf_convertible",
        [
            ("fund_basic", "基金列表", 19),
            ("fund_daily", "ETF 日线", 127),
            ("fund_adj", "ETF 复权因子", 199),
            ("fund_nav", "基金净值", 119),
            ("fund_portfolio", "基金持仓", 121),
            ("fund_share", "基金规模", 207),
            ("fund_manager", "基金经理", 208),
            ("fund_company", "基金管理人", 118),
            ("fund_div", "基金分红", 120),
            ("etf_basic", "ETF 基础信息", 385),
            ("etf_share_size", "ETF 份额规模", 408),
            ("etf_index", "ETF 跟踪指数", 386),
            ("cb_basic", "可转债基础信息", 185),
            ("cb_daily", "可转债行情", 187),
            ("cb_issue", "可转债发行", 186),
            ("cb_call", "可转债赎回信息", 269),
            ("cb_price_chg", "可转债转股价变动", 246),
            ("cb_rating", "可转债评级", 458),
            ("cb_share", "可转债转股结果", 247),
            ("cb_rate", "可转债票面利率", 305),
        ],
    )
    + _specs(
        "macro_context",
        "monthly_or_release",
        "macro_context",
        [
            ("cn_cpi", "中国 CPI", 219),
            ("cn_ppi", "中国 PPI", 239),
            ("cn_pmi", "中国 PMI", 130),
            ("cn_gdp", "中国 GDP", 124),
            ("cn_m", "货币供应量", 131),
            ("sf_month", "社会融资规模", 151),
            ("shibor", "Shibor", 149),
            ("shibor_lpr", "LPR", 151),
        ],
    )
    + [
        EndpointDefinition("ths_hot", "restricted_extensions", "THS 热榜", "intraday", "heat_ranking", 320, 6000, baseline_state="restricted"),
        EndpointDefinition("moneyflow_cnt_ths", "restricted_extensions", "THS 概念资金流", "daily_after_close", "sector_evidence", 371, 6000, baseline_state="restricted"),
        EndpointDefinition("moneyflow_ind_ths", "restricted_extensions", "THS 行业资金流", "daily_after_close", "sector_evidence", 343, 6000, baseline_state="restricted"),
        EndpointDefinition("moneyflow_ths", "restricted_extensions", "THS 个股资金流", "daily_after_close", "capital_flow", 348, 6000, baseline_state="restricted"),
        EndpointDefinition("limit_step", "restricted_extensions", "连板天梯", "daily_after_close", "market_evidence", 356, 8000, baseline_state="restricted"),
        EndpointDefinition("limit_cpt_list", "restricted_extensions", "涨停最强板块", "daily_after_close", "sector_evidence", 357, 8000, baseline_state="restricted"),
        EndpointDefinition("dc_hot", "restricted_extensions", "东财热榜", "intraday", "heat_ranking", 321, 8000, baseline_state="restricted"),
        EndpointDefinition("news", "independent_extensions", "新闻快讯", "intraday", "research_events", 143, requires_independent_authorization=True, baseline_state="independent_authorization"),
        EndpointDefinition("anns_d", "independent_extensions", "上市公司公告", "daily_after_close", "research_events", 176, requires_independent_authorization=True, baseline_state="independent_authorization"),
        EndpointDefinition("research_report", "independent_extensions", "券商研究报告", "daily_after_close", "research_events", 415, requires_independent_authorization=True, baseline_state="independent_authorization"),
    ]
)

CATALOG_BY_CODE = {item.code: item for item in CATALOG}


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            pass
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if pd.isna(value):
        return None
    return value


def dataframe_records(frame: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    return [_jsonable(row) for row in frame.where(pd.notna(frame), None).to_dict("records")]


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _number(value: Any) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> Optional[int]:
    number = _number(value)
    return int(number) if number is not None else None


def _ts_code(value: Any) -> Optional[str]:
    text = str(value or "").strip().upper()
    if not text:
        return None
    if "." in text:
        return text
    digits = "".join(char for char in text if char.isdigit())
    if not digits:
        return text
    if digits.startswith("6"):
        return f"{digits}.SH"
    if digits.startswith(("4", "8")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def normalise_limit_pool_rows(records: Iterable[Mapping[str, Any]], pool_kind: str, source_label: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for raw in records:
        symbol = _ts_code(_first(raw, "ts_code", "代码", "code"))
        if not symbol:
            continue
        rows.append(
            {
                "pool_kind": pool_kind,
                "symbol": symbol,
                "name": str(_first(raw, "name", "名称") or ""),
                "limit_times": _integer(_first(raw, "limit_times", "连板数")),
                "first_limit_at": _first(raw, "first_time", "首次封板时间", "first_lu_time"),
                "last_limit_at": _first(raw, "last_time", "最后封板时间", "last_lu_time"),
                "open_times": _integer(_first(raw, "open_times", "炸板次数", "open_num")),
                "seal_amount": _number(_first(raw, "fd_amount", "封单资金", "limit_order")),
                "turnover": _number(_first(raw, "turnover_ratio", "换手率", "turnover_rate")),
                "industry": str(_first(raw, "industry", "所属行业") or ""),
                "source_label": source_label,
                "raw_payload": _jsonable(raw),
            }
        )
    return rows


def build_limit_ecology(
    limit_up_records: Iterable[Mapping[str, Any]],
    limit_down_records: Iterable[Mapping[str, Any]],
    broken_records: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    up = list(limit_up_records)
    down = list(limit_down_records)
    broken = list(broken_records)
    board_counts = [int(_integer(row.get("limit_times")) or 0) for row in up]
    metrics: List[Dict[str, Any]] = [
        {"metric_code": "limit_up_count", "value": float(len(up)), "unit": "stocks"},
        {"metric_code": "limit_down_count", "value": float(len(down)), "unit": "stocks"},
        {"metric_code": "broken_board_count", "value": float(len(broken)), "unit": "stocks"},
        {"metric_code": "seal_rate", "value": (len(up) / (len(up) + len(broken)) * 100) if up or broken else None, "unit": "percent"},
        {"metric_code": "highest_board", "value": float(max(board_counts) if board_counts else 0), "unit": "boards"},
    ]
    for level in range(1, 5):
        metrics.append(
            {
                "metric_code": f"ladder_{level}_board_count",
                "value": float(sum(1 for count in board_counts if count == level)),
                "unit": "stocks",
            }
        )
    metrics.append(
        {
            "metric_code": "ladder_5_plus_board_count",
            "value": float(sum(1 for count in board_counts if count >= 5)),
            "unit": "stocks",
        }
    )
    return metrics


def _is_a_share_symbol(symbol: str) -> bool:
    code, _, exchange = str(symbol or "").partition(".")
    if exchange == "SH":
        return code.startswith(("600", "601", "603", "605", "688"))
    if exchange == "SZ":
        return code.startswith(("000", "001", "002", "003", "300", "301"))
    if exchange == "BJ":
        return code.startswith(("4", "8", "9"))
    return False


def _in_market_scope(symbol: str, market_scope: str) -> bool:
    code, _, exchange = str(symbol or "").partition(".")
    if market_scope == "all_a":
        return _is_a_share_symbol(symbol)
    if market_scope == "main_board":
        return (exchange == "SH" and code.startswith(("600", "601", "603", "605"))) or (
            exchange == "SZ" and code.startswith(("000", "001", "002", "003"))
        )
    if market_scope == "chinext":
        return exchange == "SZ" and code.startswith(("300", "301"))
    if market_scope == "star":
        return exchange == "SH" and code.startswith("688")
    if market_scope == "beijing":
        return exchange == "BJ" and code.startswith(("4", "8", "9"))
    if market_scope == "exclude_st":
        raise ValueError("历史日线不包含 ST 状态，不能生成非 ST 市场广度")
    raise ValueError(f"不支持的市场范围：{market_scope}")


def build_market_breadth(records: Iterable[Mapping[str, Any]], market_scope: str = "all_a") -> List[Dict[str, Any]]:
    """Calculate post-close breadth from one TuShare daily response.

    The provider's full-market ``daily`` response is the only input here.  Rows
    without a usable close change are excluded rather than treated as flat, so
    an incomplete provider response cannot become a fabricated market fact.
    """
    rise = fall = flat = valid = 0
    for raw in records:
        symbol = _ts_code(_first(raw, "ts_code", "代码", "code"))
        if not symbol or not _in_market_scope(symbol, market_scope):
            continue
        change = _number(_first(raw, "pct_chg", "涨跌幅", "change", "涨跌额"))
        if change is None:
            close = _number(_first(raw, "close", "收盘价"))
            pre_close = _number(_first(raw, "pre_close", "昨收价"))
            change = close - pre_close if close is not None and pre_close is not None else None
        if change is None:
            continue
        valid += 1
        if change > 0:
            rise += 1
        elif change < 0:
            fall += 1
        else:
            flat += 1

    unavailable = valid == 0
    return [
        {"metric_code": "rise_count", "value": None if unavailable else float(rise), "unit": "stocks"},
        {"metric_code": "fall_count", "value": None if unavailable else float(fall), "unit": "stocks"},
        {"metric_code": "flat_count", "value": None if unavailable else float(flat), "unit": "stocks"},
        {"metric_code": "red_market_ratio", "value": None if unavailable else rise / valid * 100, "unit": "percent"},
        {"metric_code": "rise_fall_ratio", "value": None if unavailable or fall == 0 else rise / fall, "unit": "ratio"},
    ]


class TushareCatalogService:
    """Persist catalogue/probe/raw payload facts without exposing credentials."""

    def __init__(self, database, provider: Optional[TushareFirstDataProvider] = None):
        self.database = database
        self.provider = provider or market_data_provider
        self.credit_tier = int(settings.TUSHARE_CREDIT_TIER)

    def install_catalog(self) -> int:
        rows = [
            (
                item.code,
                item.module,
                item.name,
                item.required_credits,
                item.requires_independent_authorization,
                item.schedule_kind,
                item.storage_dataset,
                item.contract_url,
                item.baseline_state,
                self._is_eligible(item),
            )
            for item in CATALOG
        ]
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO tushare_endpoint_catalog
                    (endpoint_code, module_code, display_name, required_credits,
                     requires_independent_authorization, schedule_kind, storage_dataset,
                     contract_url, baseline_state, enabled)
                    VALUES %s
                    ON CONFLICT (endpoint_code) DO UPDATE SET
                        module_code = EXCLUDED.module_code,
                        display_name = EXCLUDED.display_name,
                        required_credits = EXCLUDED.required_credits,
                        requires_independent_authorization = EXCLUDED.requires_independent_authorization,
                        schedule_kind = EXCLUDED.schedule_kind,
                        storage_dataset = EXCLUDED.storage_dataset,
                        contract_url = EXCLUDED.contract_url,
                        baseline_state = EXCLUDED.baseline_state,
                        enabled = EXCLUDED.enabled,
                        updated_at = NOW()
                    """,
                    rows,
                )
        return len(rows)

    def catalogue(self, module: Optional[str] = None) -> List[Dict[str, Any]]:
        query = """
            SELECT c.endpoint_code, c.module_code, c.display_name, c.required_credits,
                   c.requires_independent_authorization, c.schedule_kind, c.storage_dataset,
                   c.contract_url, c.baseline_state, c.enabled,
                   p.permission_state, p.checked_at, p.supported_fields, p.rate_limit,
                   p.error_code, p.error_message
            FROM tushare_endpoint_catalog c
            LEFT JOIN LATERAL (
                SELECT permission_state, checked_at, supported_fields, rate_limit, error_code, error_message
                FROM tushare_endpoint_probes
                WHERE endpoint_code = c.endpoint_code
                ORDER BY checked_at DESC, id DESC
                LIMIT 1
            ) p ON TRUE
        """
        params: List[Any] = []
        if module:
            query += " WHERE c.module_code = %s"
            params.append(module)
        query += " ORDER BY c.module_code, c.endpoint_code"
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    def probe(self, endpoint_code: str, params: Optional[Dict[str, Any]] = None, fields: Optional[str] = None) -> Dict[str, Any]:
        definition = self._definition(endpoint_code)
        if not self._is_eligible(definition):
            return self._record_probe(
                definition,
                permission_state=definition.baseline_state,
                error_code="credit_or_authorization_required",
                error_message=self._restriction_message(definition),
            )
        if not self.provider.is_tushare_ready():
            return self._record_probe(
                definition,
                permission_state="missing_token",
                error_code="tushare_token_missing",
                error_message="TUSHARE_TOKEN 未配置，未发起远端探测。",
            )
        try:
            frame = self.provider.fetch_pro_endpoint(endpoint_code, **(params or {}), fields=fields)
        except Exception as exc:
            return self._record_probe(
                definition,
                permission_state="failed",
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
        records = dataframe_records(frame)
        return self._record_probe(
            definition,
            permission_state="available" if records else "available_empty",
            supported_fields=list(frame.columns) if isinstance(frame, pd.DataFrame) else [],
            response_hash=_canonical_hash(records),
        )

    def sync_endpoint(
        self,
        endpoint_code: str,
        params: Optional[Dict[str, Any]] = None,
        fields: Optional[str] = None,
        include_records: bool = False,
    ) -> Dict[str, Any]:
        definition = self._definition(endpoint_code)
        if not self._is_eligible(definition):
            raise ValueError(self._restriction_message(definition))
        if not self.provider.is_tushare_ready():
            raise RuntimeError("TUSHARE_TOKEN 未配置，不能同步 TuShare 数据。")
        requested_params = _jsonable(params or {})
        run_id = self._create_endpoint_run(definition.code, requested_params, fields)
        try:
            frame = self.provider.fetch_pro_endpoint(definition.code, **requested_params, fields=fields)
            records = dataframe_records(frame)
            response_hash = _canonical_hash(records)
            self._store_endpoint_records(run_id, definition.code, records)
            self._complete_endpoint_run(run_id, "success", len(records), response_hash=response_hash)
            result = {
                "run_id": run_id,
                "endpoint_code": definition.code,
                "status": "success",
                "row_count": len(records),
                "response_hash": response_hash,
            }
            # Internal orchestration occasionally needs a tiny, just-fetched
            # endpoint response (for example one trade-calendar day) to make a
            # gate decision.  The public sync API deliberately keeps its
            # existing compact response and does not return arbitrary raw data.
            if include_records:
                result["records"] = records
            return result
        except Exception as exc:
            self._complete_endpoint_run(run_id, "failed", 0, error_message=str(exc))
            raise

    def sync_market_evidence(self, trade_date: str, market_scope: str = "all_a") -> Dict[str, Any]:
        compact_date = str(trade_date).replace("-", "")
        pools: Dict[str, List[Dict[str, Any]]] = {}
        source_map: Dict[str, str] = {}
        errors: Dict[str, str] = {}
        for pool_kind, limit_type in (("up", "U"), ("down", "D"), ("broken", "Z")):
            try:
                frame, source_label = self._limit_pool_frame(compact_date, pool_kind, limit_type)
                pools[pool_kind] = normalise_limit_pool_rows(dataframe_records(frame), pool_kind, source_label)
                source_map[pool_kind] = source_label
            except Exception as exc:
                pools[pool_kind] = []
                source_map[pool_kind] = "unavailable"
                errors[pool_kind] = str(exc)

        kpl_rows: List[Dict[str, Any]] = []
        try:
            if self.provider.is_tushare_ready():
                kpl_frame = self.provider.fetch_pro_endpoint("kpl_list", trade_date=compact_date, tag="涨停")
                for ordinal, raw in enumerate(dataframe_records(kpl_frame), start=1):
                    kpl_rows.append(
                        {
                            "ranking_kind": "limit_up",
                            "rank": ordinal,
                            "symbol": _ts_code(_first(raw, "ts_code", "代码")),
                            "name": str(_first(raw, "name", "名称") or ""),
                            "theme": str(_first(raw, "theme", "板块") or ""),
                            "status": str(_first(raw, "status", "涨停统计") or ""),
                            "source_label": "tushare_kpl_list",
                            "raw_payload": raw,
                        }
                    )
                source_map["kpl_list"] = "tushare_kpl_list"
            else:
                source_map["kpl_list"] = "missing_token"
        except Exception as exc:
            source_map["kpl_list"] = "unavailable"
            errors["kpl_list"] = str(exc)

        metrics = build_limit_ecology(pools["up"], pools["down"], pools["broken"])
        for item in metrics:
            item["definition_version"] = "limit-ecology-v1"
            item["source_label"] = "tushare_limit_list_derived" if source_map.get("up") == "tushare_limit_list_d" else source_map.get("up", "unavailable")

        try:
            if not self.provider.is_tushare_ready():
                raise RuntimeError("TuShare 未就绪，不能封存全市场涨跌广度")
            breadth_frame = self.provider.fetch_pro_endpoint("daily", trade_date=compact_date)
            breadth_metrics = build_market_breadth(dataframe_records(breadth_frame), market_scope)
            for item in breadth_metrics:
                item["definition_version"] = "market-breadth-v1"
                item["source_label"] = "tushare_daily"
            metrics.extend(breadth_metrics)
            source_map["market_breadth"] = "tushare_daily"
        except Exception as exc:
            source_map["market_breadth"] = "unavailable"
            errors["market_breadth"] = str(exc)

        content = {"trade_date": compact_date, "scope": market_scope, "sources": source_map, "pools": pools, "kpl": kpl_rows, "metrics": metrics}
        snapshot_id, created = self._store_market_evidence_snapshot(
            trade_date=compact_date,
            market_scope=market_scope,
            source_map=source_map,
            status="partial" if errors else "published",
            content=content,
            pools=pools,
            kpl_rows=kpl_rows,
            metrics=metrics,
        )
        return {"snapshot_id": snapshot_id, "created": created, "trade_date": compact_date, "status": "partial" if errors else "published", "sources": source_map, "errors": errors, "metrics": metrics}

    def latest_market_evidence(self, trade_date: Optional[str] = None, market_scope: str = "all_a") -> Optional[Dict[str, Any]]:
        query = """
            SELECT id, trade_date, snapshot_type, market_scope, captured_at, available_at,
                   source_map, status, content_hash
            FROM market_evidence_snapshots
            WHERE snapshot_type = 'post_close' AND market_scope = %s
        """
        params: List[Any] = [market_scope]
        if trade_date:
            query += " AND trade_date = %s"
            params.append(str(trade_date).replace("-", ""))
        query += " ORDER BY trade_date DESC, captured_at DESC LIMIT 1"
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                snapshot = cursor.fetchone()
                if not snapshot:
                    return None
                snapshot_id = snapshot["id"]
                cursor.execute(
                    "SELECT metric_code, value, unit, definition_version, source_label FROM market_evidence_metrics WHERE snapshot_id = %s ORDER BY metric_code",
                    (snapshot_id,),
                )
                metrics = [dict(row) for row in cursor.fetchall()]
                cursor.execute(
                    "SELECT pool_kind, symbol, name, limit_times, first_limit_at, last_limit_at, open_times, seal_amount, turnover, industry, source_label FROM limit_pool_members WHERE snapshot_id = %s ORDER BY pool_kind, limit_times DESC NULLS LAST, symbol",
                    (snapshot_id,),
                )
                pools = [dict(row) for row in cursor.fetchall()]
        return {**dict(snapshot), "metrics": metrics, "limit_pool_members": pools}

    def _limit_pool_frame(self, trade_date: str, pool_kind: str, limit_type: str) -> Tuple[pd.DataFrame, str]:
        if self.provider.is_tushare_ready():
            return self.provider.fetch_pro_endpoint("limit_list_d", trade_date=trade_date, limit_type=limit_type), "tushare_limit_list_d"
        akshare = getattr(self.provider, "akshare", None)
        method_name = {"up": "stock_zt_pool_em", "down": "stock_zt_pool_dtgc_em", "broken": "stock_zt_pool_zbgc_em"}[pool_kind]
        if akshare is None or not hasattr(akshare, method_name):
            raise RuntimeError("TuShare 不可用且 AkShare 对应涨跌停池不可用")
        return getattr(akshare, method_name)(date=trade_date), "akshare_eastmoney_limit_pool"

    def _definition(self, endpoint_code: str) -> EndpointDefinition:
        definition = CATALOG_BY_CODE.get(str(endpoint_code).strip())
        if not definition:
            raise ValueError(f"未注册的 TuShare 端点：{endpoint_code}")
        return definition

    def _is_eligible(self, definition: EndpointDefinition) -> bool:
        return not definition.requires_independent_authorization and definition.required_credits <= self.credit_tier and definition.baseline_state == "eligible"

    def _restriction_message(self, definition: EndpointDefinition) -> str:
        if definition.requires_independent_authorization:
            return f"{definition.code} 需要单独授权，不属于 5,000 积分标准权限。"
        return f"{definition.code} 需要至少 {definition.required_credits} 积分，当前基线为 {self.credit_tier}。"

    def _record_probe(
        self,
        definition: EndpointDefinition,
        permission_state: str,
        supported_fields: Optional[List[str]] = None,
        rate_limit: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        response_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tushare_endpoint_probes
                    (endpoint_code, permission_state, supported_fields, rate_limit, error_code, error_message, response_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, checked_at
                    """,
                    (definition.code, permission_state, psycopg2.extras.Json(supported_fields or []), rate_limit, error_code, error_message, response_hash),
                )
                probe_id, checked_at = cursor.fetchone()
        return {"probe_id": probe_id, "endpoint_code": definition.code, "permission_state": permission_state, "checked_at": checked_at.isoformat(), "supported_fields": supported_fields or [], "error_code": error_code, "error_message": error_message}

    def _create_endpoint_run(self, endpoint_code: str, params: Dict[str, Any], fields: Optional[str]) -> int:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tushare_endpoint_runs (endpoint_code, requested_params, fields_requested)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (endpoint_code, psycopg2.extras.Json(params), fields),
                )
                return int(cursor.fetchone()[0])

    def _store_endpoint_records(self, run_id: int, endpoint_code: str, records: List[Dict[str, Any]]) -> None:
        if not records:
            return
        values = [(run_id, endpoint_code, ordinal, _canonical_hash(record), psycopg2.extras.Json(record)) for ordinal, record in enumerate(records, start=1)]
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    "INSERT INTO tushare_endpoint_records (run_id, endpoint_code, record_ordinal, record_hash, payload) VALUES %s",
                    values,
                )

    def _complete_endpoint_run(self, run_id: int, status: str, row_count: int, response_hash: Optional[str] = None, error_message: Optional[str] = None) -> None:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE tushare_endpoint_runs
                    SET status = %s, row_count = %s, response_hash = %s, error_message = %s, finished_at = NOW()
                    WHERE id = %s
                    """,
                    (status, int(row_count), response_hash, error_message, run_id),
                )

    def _store_market_evidence_snapshot(
        self,
        trade_date: str,
        market_scope: str,
        source_map: Dict[str, str],
        status: str,
        content: Dict[str, Any],
        pools: Dict[str, List[Dict[str, Any]]],
        kpl_rows: List[Dict[str, Any]],
        metrics: List[Dict[str, Any]],
    ) -> Tuple[int, bool]:
        content_hash = _canonical_hash(content)
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO market_evidence_snapshots
                    (trade_date, snapshot_type, market_scope, source_map, status, content_hash)
                    VALUES (%s, 'post_close', %s, %s, %s, %s)
                    ON CONFLICT (trade_date, snapshot_type, market_scope, content_hash) DO NOTHING
                    RETURNING id
                    """,
                    (trade_date, market_scope, psycopg2.extras.Json(source_map), status, content_hash),
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        """
                        SELECT id FROM market_evidence_snapshots
                        WHERE trade_date = %s AND snapshot_type = 'post_close' AND market_scope = %s AND content_hash = %s
                        """,
                        (trade_date, market_scope, content_hash),
                    )
                    return int(cursor.fetchone()[0]), False
                snapshot_id = int(row[0])
                metric_values = [
                    (snapshot_id, item["metric_code"], item.get("value"), item.get("unit"), item.get("definition_version", "v1"), item["source_label"])
                    for item in metrics
                ]
                if metric_values:
                    psycopg2.extras.execute_values(
                        cursor,
                        "INSERT INTO market_evidence_metrics (snapshot_id, metric_code, value, unit, definition_version, source_label) VALUES %s",
                        metric_values,
                    )
                member_values = [
                    (snapshot_id, item["pool_kind"], item["symbol"], item["name"], item.get("limit_times"), item.get("first_limit_at"), item.get("last_limit_at"), item.get("open_times"), item.get("seal_amount"), item.get("turnover"), item.get("industry"), item["source_label"], psycopg2.extras.Json(item["raw_payload"]))
                    for rows in pools.values()
                    for item in rows
                ]
                if member_values:
                    psycopg2.extras.execute_values(
                        cursor,
                        """
                        INSERT INTO limit_pool_members
                        (snapshot_id, pool_kind, symbol, name, limit_times, first_limit_at, last_limit_at,
                         open_times, seal_amount, turnover, industry, source_label, raw_payload)
                        VALUES %s
                        """,
                        member_values,
                    )
                rank_values = [
                    (snapshot_id, item["ranking_kind"], item["rank"], item.get("symbol"), item.get("name"), item.get("theme"), item.get("status"), item["source_label"], psycopg2.extras.Json(item["raw_payload"]))
                    for item in kpl_rows
                ]
                if rank_values:
                    psycopg2.extras.execute_values(
                        cursor,
                        """
                        INSERT INTO short_line_rank_rows
                        (snapshot_id, ranking_kind, rank, symbol, name, theme, status, source_label, raw_payload)
                        VALUES %s
                        """,
                        rank_values,
                    )
        return snapshot_id, True
