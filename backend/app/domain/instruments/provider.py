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
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        start = today - timedelta(days=14)
        rows = _records(self.client.trade_cal(
            exchange="",
            start_date=start.strftime("%Y%m%d"),
            end_date=today.strftime("%Y%m%d"),
            is_open="1",
            fields="cal_date,is_open",
        ))
        dates = sorted(str(row.get("cal_date") or "") for row in rows if str(row.get("cal_date") or ""))
        if not dates:
            raise RuntimeError("TuShare trade_cal 未返回最近开放交易日")
        return dates[-1]

    def fetch_daily(self, trade_date: str) -> list[dict]:
        return _records(self.client.daily(
            trade_date=trade_date,
            fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
        ))

    def fetch_daily_basic(self, trade_date: str) -> list[dict]:
        return _records(self.client.daily_basic(
            trade_date=trade_date,
            fields="ts_code,trade_date,turnover_rate,volume_ratio,pe,pb,total_mv,circ_mv",
        ))
