from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import settings


def _records(frame: Any) -> list[dict]:
    if frame is None:
        return []
    rows = frame.to_dict("records")
    result: list[dict] = []
    for row in rows:
        normalized = {}
        for key, value in dict(row).items():
            normalized[key] = None if isinstance(value, float) and math.isnan(value) else value
        result.append(normalized)
    return result


class TushareAshareProvider:
    def __init__(self, *, token: str | None = None, client=None):
        self.token = str(token or settings.TUSHARE_TOKEN or "").strip()
        if client is None:
            if not self.token:
                raise RuntimeError("TUSHARE_TOKEN 未配置，无法同步全量 A 股标的")
            import tushare as ts
            client = ts.pro_api(self.token)
        self.client = client

    def fetch_instruments(self) -> list[dict]:
        fields = "ts_code,symbol,name,area,industry,fullname,enname,cnspell,market,exchange,curr_type,list_status,list_date,delist_date,is_hs,act_name,act_ent_type"
        rows: list[dict] = []
        for status in ("L", "P", "D"):
            rows.extend(_records(self.client.stock_basic(exchange="", list_status=status, fields=fields)))
        return rows

    def latest_open_trade_date(self) -> str:
        dates = self.recent_open_trade_dates()
        if not dates:
            raise RuntimeError("TuShare trade_cal 未返回最近开放交易日")
        return dates[-1]

    def recent_open_trade_dates(self, *, lookback_days: int = 14) -> list[str]:
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        start = today - timedelta(days=lookback_days)
        rows = self.fetch_trade_calendar(start.strftime("%Y%m%d"), today.strftime("%Y%m%d"), is_open="1")
        dates = sorted(str(row.get("cal_date") or "") for row in rows if str(row.get("cal_date") or ""))
        return dates

    def fetch_open_trade_dates(self, start_date: str, end_date: str) -> list[str]:
        rows = self.fetch_trade_calendar(start_date, end_date, is_open="1")
        return sorted(str(row.get("cal_date") or "") for row in rows if str(row.get("cal_date") or ""))

    def fetch_trade_calendar(self, start_date: str, end_date: str, *, is_open: str | None = None) -> list[dict]:
        params = {
            "exchange": "",
            "start_date": start_date,
            "end_date": end_date,
            "fields": "exchange,cal_date,is_open,pretrade_date",
        }
        if is_open is not None:
            params["is_open"] = is_open
        return _records(self.client.trade_cal(**params))

    def fetch_daily(self, trade_date: str) -> list[dict]:
        return _records(self.client.daily(
            trade_date=trade_date,
            fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
        ))

    def fetch_daily_basic(self, trade_date: str) -> list[dict]:
        return _records(self.client.daily_basic(
            trade_date=trade_date,
            fields="ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_mv,circ_mv,limit_status",
        ))

    def fetch_adj_factor(self, trade_date: str) -> list[dict]:
        return _records(self.client.adj_factor(
            trade_date=trade_date,
            fields="ts_code,trade_date,adj_factor",
        ))

    def fetch_suspensions(self, trade_date: str) -> list[dict]:
        return _records(self.client.suspend_d(
            trade_date=trade_date,
            fields="ts_code,trade_date,suspend_timing,suspend_type",
        ))

    def fetch_price_limits(self, trade_date: str) -> list[dict]:
        return _records(self.client.stk_limit(
            trade_date=trade_date,
            fields="ts_code,trade_date,pre_close,up_limit,down_limit",
        ))

    def fetch_corporate_actions(self, trade_date: str) -> list[dict]:
        return _records(self.client.dividend(
            ex_date=trade_date,
            fields="ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,imp_ann_date,base_date,base_share",
        ))

    def fetch_benchmark_bars(self, trade_date: str, benchmarks: list[str] | None = None) -> list[dict]:
        rows: list[dict] = []
        for ts_code in benchmarks or ["000001.SH", "399001.SZ", "399006.SZ", "000300.SH"]:
            rows.extend(_records(self.client.index_daily(
                ts_code=ts_code,
                trade_date=trade_date,
                fields="ts_code,trade_date,close,open,high,low,pre_close,change,pct_chg,vol,amount",
            )))
        return rows
