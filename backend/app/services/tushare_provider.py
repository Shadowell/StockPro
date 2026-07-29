"""
Tushare-first market data adapter.

Business services call this adapter with the small AkShare-shaped surface they
already know. For mapped data, Tushare is tried first; if the token is missing,
the Tushare API is unavailable, or the response is empty, the call falls back to
AkShare.
"""
import logging
import pickle
import subprocess
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from app.core.config import settings

try:
    import akshare as _akshare
except Exception:  # pragma: no cover - covered by tests with injected modules
    _akshare = None

try:
    import tushare as _tushare
except Exception:  # pragma: no cover - tushare may be absent in minimal tests
    _tushare = None


logger = logging.getLogger(__name__)


AKSHARE_SUBPROCESS_SCRIPT = """
import pickle
import sys

name, input_path, output_path = sys.argv[1:4]
with open(input_path, "rb") as input_file:
    args, kwargs = pickle.load(input_file)

try:
    import akshare as akshare_module

    result = getattr(akshare_module, name)(*args, **kwargs)
    payload = ("ok", result)
except BaseException as exc:
    payload = ("error", f"{type(exc).__name__}: {exc}")

with open(output_path, "wb") as output_file:
    pickle.dump(payload, output_file, protocol=pickle.HIGHEST_PROTOCOL)
"""


class TushareFirstDataProvider:
    def __init__(
        self,
        tushare_module: Any = None,
        akshare_module: Any = None,
        token: Optional[str] = None,
        realtime_source: Optional[str] = None,
        enabled: Optional[bool] = None,
    ):
        self.tushare = _tushare if tushare_module is None else tushare_module
        self.akshare = _akshare if akshare_module is None else akshare_module
        self.token = settings.TUSHARE_TOKEN if token is None else token
        self.realtime_source = realtime_source or settings.TUSHARE_REALTIME_SOURCE
        self.enabled = settings.ENABLE_TUSHARE if enabled is None else enabled
        self._pro = None

    def __getattr__(self, name: str) -> Callable[..., Any]:
        fallback = self._akshare_attr(name)

        def call_fallback(*args, **kwargs):
            return fallback(*args, **kwargs)

        return call_fallback

    def stock_zh_a_spot_em(self, *args, **kwargs) -> pd.DataFrame:
        return self._with_fallback(
            "stock_zh_a_spot_em",
            lambda: self._tushare_realtime_quote(ts_code=kwargs.get("ts_code") or ""),
            lambda: self._akshare_attr("stock_zh_a_spot_em")(*args, **kwargs),
        )

    def stock_zh_a_spot(self, *args, **kwargs) -> pd.DataFrame:
        return self._with_fallback(
            "stock_zh_a_spot",
            lambda: self._tushare_realtime_quote(ts_code=kwargs.get("ts_code") or ""),
            lambda: self._akshare_attr("stock_zh_a_spot")(*args, **kwargs),
        )

    def stock_zh_a_hist(
        self,
        symbol: str,
        period: str = "daily",
        start_date: str = "",
        end_date: str = "",
        adjust: str = "",
        *args,
        **kwargs,
    ) -> pd.DataFrame:
        return self._with_fallback(
            "stock_zh_a_hist",
            lambda: self._tushare_daily_history(symbol, period, start_date, end_date, adjust),
            lambda: self._akshare_attr("stock_zh_a_hist")(
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
                *args,
                **kwargs,
            ),
        )

    def stock_zh_a_hist_with_source(
        self,
        symbol: str,
        period: str = "daily",
        start_date: str = "",
        end_date: str = "",
        adjust: str = "",
    ) -> tuple[pd.DataFrame, str, Optional[str]]:
        """Fetch daily bars with the actual provider and an explicit fallback reason.

        The legacy AkShare-shaped method intentionally hides the fallback for
        display pages.  Dataset publication must not: one partition has one
        actual source, and its audit record has to tell a researcher why a
        fallback was used.
        """
        fallback_reason: Optional[str] = None
        if self._tushare_ready():
            try:
                frame = self._tushare_daily_history(symbol, period, start_date, end_date, adjust)
                if isinstance(frame, pd.DataFrame) and not frame.empty:
                    return frame, "tushare", None
                fallback_reason = "tushare_empty_response"
            except Exception as exc:
                fallback_reason = f"tushare_error:{type(exc).__name__}"
        else:
            fallback_reason = "tushare_not_ready"
        frame = self._akshare_attr("stock_zh_a_hist")(
            symbol=symbol,
            period=period,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )
        return frame, "akshare", fallback_reason

    def stock_zh_a_daily(
        self,
        symbol: str,
        start_date: str = "",
        end_date: str = "",
        adjust: str = "",
        *args,
        **kwargs,
    ) -> pd.DataFrame:
        plain_symbol = self._to_plain_code(symbol)
        return self._with_fallback(
            "stock_zh_a_daily",
            lambda: self._tushare_daily_history(plain_symbol, "daily", start_date, end_date, adjust),
            lambda: self._akshare_attr("stock_zh_a_daily")(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
                *args,
                **kwargs,
            ),
        )

    def stock_zh_a_minute(
        self,
        symbol: str,
        period: str = "1",
        adjust: str = "",
        *args,
        **kwargs,
    ) -> pd.DataFrame:
        return self._with_fallback(
            "stock_zh_a_minute",
            lambda: self._tushare_minute_history(symbol, period=period, adjust=adjust),
            lambda: self._akshare_attr("stock_zh_a_minute")(
                symbol=symbol,
                period=period,
                adjust=adjust,
                *args,
                **kwargs,
            ),
        )

    def stock_a_indicator_lg(self, symbol: str, *args, **kwargs) -> pd.DataFrame:
        return self._with_fallback(
            "stock_a_indicator_lg",
            lambda: self._tushare_daily_basic(symbol),
            lambda: self._akshare_attr("stock_a_indicator_lg")(symbol=symbol, *args, **kwargs),
        )

    def stock_zh_index_daily(self, symbol: str, *args, **kwargs) -> pd.DataFrame:
        return self._with_fallback(
            "stock_zh_index_daily",
            lambda: self._tushare_index_daily(symbol),
            lambda: self._akshare_attr("stock_zh_index_daily")(symbol=symbol, *args, **kwargs),
        )

    def stock_zh_index_spot_sina(self, *args, **kwargs) -> pd.DataFrame:
        return self._with_fallback(
            "stock_zh_index_spot_sina",
            lambda: self._tushare_realtime_quote(ts_code="000001.SH,399001.SZ,399006.SZ"),
            lambda: self._akshare_attr("stock_zh_index_spot_sina")(*args, **kwargs),
        )

    def stock_zh_index_spot_em(self, *args, **kwargs) -> pd.DataFrame:
        return self.stock_zh_index_spot_sina(*args, **kwargs)

    def tool_trade_date_hist_sina(self, *args, **kwargs) -> pd.DataFrame:
        return self._with_fallback(
            "tool_trade_date_hist_sina",
            self._tushare_trade_calendar,
            lambda: self._akshare_attr("tool_trade_date_hist_sina")(*args, **kwargs),
        )

    def stock_board_concept_name_em(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_board_concept_name_em", *args, **kwargs)

    def stock_board_concept_name_ths(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_board_concept_name_ths", *args, **kwargs)

    def stock_board_concept_cons_em(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_board_concept_cons_em", *args, **kwargs)

    def stock_board_concept_hist_em(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_board_concept_hist_em", *args, **kwargs)

    def stock_board_concept_hist_min_em(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_board_concept_hist_min_em", *args, **kwargs)

    def stock_board_concept_index_ths(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_board_concept_index_ths", *args, **kwargs)

    def stock_board_industry_name_em(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_board_industry_name_em", *args, **kwargs)

    def stock_board_industry_name_ths(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_board_industry_name_ths", *args, **kwargs)

    def stock_board_industry_hist_em(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_board_industry_hist_em", *args, **kwargs)

    def stock_fund_flow_concept(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_fund_flow_concept", *args, **kwargs)

    def stock_market_fund_flow(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_market_fund_flow", *args, **kwargs)

    def stock_hot_rank_em(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_hot_rank_em", *args, **kwargs)

    def stock_hot_tweet_xq(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_hot_tweet_xq", *args, **kwargs)

    def stock_info_global_cls(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_info_global_cls", *args, **kwargs)

    def stock_info_global_em(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_info_global_em", *args, **kwargs)

    def stock_info_global_ths(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_info_global_ths", *args, **kwargs)

    def stock_news_em(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_news_em", *args, **kwargs)

    def stock_notice_report(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_notice_report", *args, **kwargs)

    def stock_hsgt_hist_em(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_hsgt_hist_em", *args, **kwargs)

    def stock_lhb_detail_em(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_lhb_detail_em", *args, **kwargs)

    def stock_market_activity_legu(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_market_activity_legu", *args, **kwargs)

    def stock_rank_cxd_ths(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_rank_cxd_ths", *args, **kwargs)

    def stock_rank_cxg_ths(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_rank_cxg_ths", *args, **kwargs)

    def stock_rank_lxsz_ths(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_rank_lxsz_ths", *args, **kwargs)

    def stock_rank_lxxd_ths(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_rank_lxxd_ths", *args, **kwargs)

    def stock_zt_pool_previous_em(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_zt_pool_previous_em", *args, **kwargs)

    def stock_zt_pool_zbgc_em(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_zt_pool_zbgc_em", *args, **kwargs)

    def index_news_sentiment_scope(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("index_news_sentiment_scope", *args, **kwargs)

    def news_cctv(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("news_cctv", *args, **kwargs)

    def news_report_time_baidu(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("news_report_time_baidu", *args, **kwargs)

    def stock_individual_fund_flow(self, *args, **kwargs) -> pd.DataFrame:
        return self._fallback_only("stock_individual_fund_flow", *args, **kwargs)

    def stock_zt_pool_em(self, date: Optional[str] = None, *args, **kwargs) -> pd.DataFrame:
        trade_date = self._compact_date(date)
        return self._with_fallback(
            "stock_zt_pool_em",
            lambda: self._tushare_limit_list(trade_date=trade_date, limit_type="U"),
            lambda: self._akshare_attr("stock_zt_pool_em")(date=date, *args, **kwargs),
        )

    def stock_zt_pool_dtgc_em(self, date: Optional[str] = None, *args, **kwargs) -> pd.DataFrame:
        trade_date = self._compact_date(date)
        return self._with_fallback(
            "stock_zt_pool_dtgc_em",
            lambda: self._tushare_limit_list(trade_date=trade_date, limit_type="D"),
            lambda: self._akshare_attr("stock_zt_pool_dtgc_em")(date=date, *args, **kwargs),
        )

    def is_tushare_ready(self) -> bool:
        """Whether an authenticated TuShare request may be made right now."""
        return self._tushare_ready()

    def fetch_pro_endpoint(self, endpoint_code: str, *, fields: Optional[str] = None, **params) -> pd.DataFrame:
        """Call one catalogue endpoint without silently falling back to AkShare.

        Research ingestion needs the actual provider and permission failure, so
        this method intentionally differs from the legacy AkShare-shaped
        adapter methods above.
        """
        if not self._tushare_ready():
            raise RuntimeError("TuShare 未就绪：请检查 ENABLE_TUSHARE、TUSHARE_TOKEN 和 tushare 包。")
        endpoint_code = str(endpoint_code or "").strip()
        if not endpoint_code:
            raise ValueError("endpoint_code 不能为空")
        request_params = {key: value for key, value in params.items() if value is not None}
        if fields:
            request_params["fields"] = fields
        pro = self._pro_api()
        method = getattr(pro, endpoint_code, None)
        if callable(method):
            result = method(**request_params)
        elif hasattr(pro, "query"):
            result = pro.query(endpoint_code, **request_params)
        else:
            raise RuntimeError(f"TuShare Pro 不支持端点：{endpoint_code}")
        if not isinstance(result, pd.DataFrame):
            raise TypeError(f"TuShare {endpoint_code} 返回了非 DataFrame 结果")
        return result

    def _with_fallback(
        self,
        api_name: str,
        tushare_call: Callable[[], pd.DataFrame],
        akshare_call: Callable[[], pd.DataFrame],
    ) -> pd.DataFrame:
        if self._tushare_ready():
            try:
                df = tushare_call()
                if isinstance(df, pd.DataFrame) and not df.empty:
                    logger.debug("%s loaded from Tushare", api_name)
                    return df
                logger.warning("%s returned empty from Tushare; using AkShare fallback", api_name)
            except Exception as exc:
                logger.warning("%s failed through Tushare; using AkShare fallback: %s", api_name, exc)
        return akshare_call()

    def _tushare_ready(self) -> bool:
        return bool(self.enabled and self.token and self.tushare)

    def _akshare_attr(self, name: str) -> Callable[..., Any]:
        if self.akshare is None:
            raise RuntimeError(f"AkShare fallback is unavailable for {name}")
        if self._should_isolate_akshare():
            return lambda *args, **kwargs: self._call_akshare_in_subprocess(name, *args, **kwargs)
        return getattr(self.akshare, name)

    def _fallback_only(self, name: str, *args, **kwargs) -> Any:
        return self._akshare_attr(name)(*args, **kwargs)

    def _should_isolate_akshare(self) -> bool:
        return bool(
            settings.AKSHARE_SUBPROCESS_FALLBACK
            and self.akshare is _akshare
            and isinstance(self.akshare, types.ModuleType)
        )

    def _call_akshare_in_subprocess(self, name: str, *args, **kwargs) -> Any:
        timeout = max(1, int(settings.AKSHARE_TIMEOUT or 30))
        with tempfile.TemporaryDirectory(prefix="stockpro-akshare-") as tmpdir:
            input_path = Path(tmpdir) / "input.pkl"
            output_path = Path(tmpdir) / "output.pkl"
            with input_path.open("wb") as input_file:
                pickle.dump((args, kwargs), input_file, protocol=pickle.HIGHEST_PROTOCOL)

            try:
                completed = subprocess.run(
                    [sys.executable, "-c", AKSHARE_SUBPROCESS_SCRIPT, name, str(input_path), str(output_path)],
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError(f"AkShare fallback {name} timed out after {timeout}s") from exc

            if not output_path.exists():
                stderr = completed.stderr.decode("utf-8", errors="replace").strip()
                if stderr:
                    stderr = stderr[-1000:]
                raise RuntimeError(f"AkShare fallback {name} exited with code {completed.returncode}: {stderr}")

            with output_path.open("rb") as output_file:
                status, payload = pickle.load(output_file)

            if status == "ok":
                return payload
            raise RuntimeError(f"AkShare fallback {name} failed: {payload}")

    def _pro_api(self):
        if self._pro is None:
            if hasattr(self.tushare, "set_token"):
                self.tushare.set_token(self.token)
            if not hasattr(self.tushare, "pro_api"):
                raise RuntimeError("Tushare pro_api is unavailable")
            self._pro = self.tushare.pro_api(self.token)
        return self._pro

    def _tushare_realtime_quote(self, ts_code: str = "") -> pd.DataFrame:
        if not hasattr(self.tushare, "realtime_quote"):
            raise RuntimeError("Tushare realtime_quote is unavailable")
        kwargs = {"src": self.realtime_source}
        if ts_code:
            kwargs["ts_code"] = ts_code
        df = self.tushare.realtime_quote(**kwargs)
        return self._normalize_realtime_quote(df)

    def _tushare_daily_history(
        self,
        symbol: str,
        period: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> pd.DataFrame:
        if period not in {"daily", "D", "d"}:
            raise RuntimeError("Tushare mapped history only supports daily period")
        ts_code = self._to_ts_code(symbol)
        adj = {"qfq": "qfq", "hfq": "hfq"}.get(str(adjust or "").lower())
        df = None
        if hasattr(self.tushare, "pro_bar"):
            df = self.tushare.pro_bar(
                ts_code=ts_code,
                start_date=self._compact_date(start_date),
                end_date=self._compact_date(end_date),
                adj=adj,
                freq="D",
            )
        if df is None or df.empty:
            df = self._pro_api().daily(
                ts_code=ts_code,
                start_date=self._compact_date(start_date),
                end_date=self._compact_date(end_date),
            )
        return self._normalize_daily_history(df)

    def daily_by_trade_date(self, trade_date: str) -> pd.DataFrame:
        """Fetch one trading day's unadjusted bars for the full A-share market.

        Returns an AkShare-shaped frame plus ``ts_code`` / ``symbol`` columns so
        callers can map each row back to StockPro's ``SH_/SZ_/BJ_`` identifiers.
        """
        compact = self._compact_date(trade_date)
        if not compact:
            raise ValueError("trade_date is required")
        if not self._tushare_ready():
            raise RuntimeError("Tushare is not ready for market-daily sync")
        raw = self._pro_api().daily(trade_date=compact)
        if not isinstance(raw, pd.DataFrame) or raw.empty:
            return raw
        frame = self._normalize_daily_history(raw)
        ts_code = self._first_series(raw, ["ts_code", "TS_CODE"]).astype(str)
        frame["ts_code"] = ts_code.reset_index(drop=True)
        frame["symbol"] = frame["ts_code"].map(self._from_ts_code)
        return frame

    def trade_cal_open_dates(self, start_date: str, end_date: str, exchange: str = "SSE") -> list[str]:
        """Return open trade dates as ISO strings between start_date and end_date."""
        if not self._tushare_ready():
            raise RuntimeError("Tushare is not ready for trade calendar sync")
        frame = self._pro_api().trade_cal(
            exchange=exchange,
            start_date=self._compact_date(start_date),
            end_date=self._compact_date(end_date),
            is_open="1",
        )
        if frame is None or frame.empty:
            return []
        dates: list[str] = []
        series = frame.get("cal_date")
        if series is None:
            return []
        for value in series.tolist():
            text = str(value or "").strip()
            if len(text) == 8 and text.isdigit():
                dates.append(f"{text[:4]}-{text[4:6]}-{text[6:8]}")
            elif text:
                dates.append(text[:10])
        return sorted(set(dates))

    def _tushare_index_daily(self, symbol: str) -> pd.DataFrame:
        df = self._pro_api().index_daily(ts_code=self._to_index_ts_code(symbol))
        return self._normalize_index_daily(df)

    def _tushare_minute_history(self, symbol: str, period: str, adjust: str) -> pd.DataFrame:
        if not hasattr(self.tushare, "pro_bar"):
            raise RuntimeError("Tushare pro_bar minute data is unavailable")
        minute = str(period or "1").replace("min", "").strip() or "1"
        freq = f"{minute}min"
        ts_code = self._to_ts_code(symbol)
        today = datetime.now().strftime("%Y%m%d")
        df = self.tushare.pro_bar(
            ts_code=ts_code,
            start_date=today,
            end_date=today,
            freq=freq,
            adj={"qfq": "qfq", "hfq": "hfq"}.get(str(adjust or "").lower()),
        )
        return self._normalize_minute_history(df)

    def _tushare_daily_basic(self, symbol: str) -> pd.DataFrame:
        df = self._pro_api().daily_basic(ts_code=self._to_ts_code(symbol))
        if not isinstance(df, pd.DataFrame) or df.empty:
            return df
        result = df.copy()
        result["trade_date"] = self._first_series(result, ["trade_date"]).map(self._display_date)
        return result.sort_values("trade_date").reset_index(drop=True)

    def _tushare_trade_calendar(self) -> pd.DataFrame:
        df = self._pro_api().trade_cal(
            exchange="",
            start_date="19900101",
            end_date=datetime.now().strftime("%Y%m%d"),
        )
        if not isinstance(df, pd.DataFrame) or df.empty:
            return df
        result = df.copy()
        result["trade_date"] = pd.to_datetime(result["cal_date"], errors="coerce")
        result["交易日"] = result["trade_date"]
        return result

    def _tushare_limit_list(self, trade_date: str, limit_type: str) -> pd.DataFrame:
        pro = self._pro_api()
        if hasattr(pro, "limit_list_d"):
            df = pro.limit_list_d(trade_date=trade_date, limit_type=limit_type)
        else:
            df = pro.query("limit_list_d", trade_date=trade_date, limit_type=limit_type)
        return self._normalize_limit_list(df)

    def _normalize_realtime_quote(self, df: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return df
        result = pd.DataFrame()
        result["代码"] = self._first_series(df, ["代码", "code", "CODE", "ts_code", "TS_CODE"]).map(self._to_plain_code)
        result["名称"] = self._first_series(df, ["名称", "name", "NAME"]).fillna("")
        result["最新价"] = self._number_series(df, ["最新价", "price", "PRICE", "close", "CLOSE"])
        result["今开"] = self._number_series(df, ["今开", "open", "OPEN"])
        result["最高"] = self._number_series(df, ["最高", "high", "HIGH"])
        result["最低"] = self._number_series(df, ["最低", "low", "LOW"])
        result["昨收"] = self._number_series(df, ["昨收", "pre_close", "PRE_CLOSE"])
        result["涨跌幅"] = self._number_series(df, ["涨跌幅", "pct_change", "PCT_CHANGE", "pct_chg", "PCT_CHG"])
        result["涨跌额"] = self._number_series(df, ["涨跌额", "change", "CHANGE"])
        result["成交量"] = self._number_series(df, ["成交量", "volume", "VOL", "vol"])
        result["成交额"] = self._number_series(df, ["成交额", "amount", "AMOUNT"])
        result["换手率"] = self._number_series(df, ["换手率", "turnover_rate", "TURNOVER_RATE"])
        result["量比"] = self._number_series(df, ["量比", "volume_ratio", "VOLUME_RATIO"])
        result["市盈率-动态"] = self._number_series(df, ["市盈率-动态", "pe", "PE", "pe_ttm"])
        result["市净率"] = self._number_series(df, ["市净率", "pb", "PB"])
        result["总市值"] = self._number_series(df, ["总市值", "total_mv", "TOTAL_MV", "total_market_cap"])
        result["流通市值"] = self._number_series(df, ["流通市值", "float_mv", "FLOAT_MV", "float_market_cap"])
        result["振幅"] = self._number_series(df, ["振幅", "amplitude", "AMPLITUDE"])
        return result

    def _normalize_daily_history(self, df: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return df
        result = pd.DataFrame()
        result["日期"] = self._first_series(df, ["trade_date", "日期"]).map(self._display_date)
        result["开盘"] = self._number_series(df, ["open", "开盘"])
        result["收盘"] = self._number_series(df, ["close", "收盘"])
        result["最高"] = self._number_series(df, ["high", "最高"])
        result["最低"] = self._number_series(df, ["low", "最低"])
        result["成交量"] = self._number_series(df, ["vol", "volume", "成交量"])
        result["成交额"] = self._number_series(df, ["amount", "成交额"])
        result["涨跌幅"] = self._number_series(df, ["pct_chg", "涨跌幅"])
        result["涨跌额"] = self._number_series(df, ["change", "涨跌额"])
        result["换手率"] = self._number_series(df, ["turnover_rate", "换手率"])
        return result.sort_values("日期").reset_index(drop=True)

    def _normalize_index_daily(self, df: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return df
        result = pd.DataFrame()
        result["date"] = self._first_series(df, ["trade_date", "date"]).map(self._display_date)
        result["open"] = self._number_series(df, ["open"])
        result["close"] = self._number_series(df, ["close"])
        result["high"] = self._number_series(df, ["high"])
        result["low"] = self._number_series(df, ["low"])
        result["volume"] = self._number_series(df, ["vol", "volume"])
        return result.sort_values("date").reset_index(drop=True)

    def _normalize_minute_history(self, df: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return df
        result = pd.DataFrame()
        result["day"] = self._first_series(df, ["trade_time", "datetime", "time", "day"]).map(str)
        result["open"] = self._number_series(df, ["open"])
        result["close"] = self._number_series(df, ["close"])
        result["high"] = self._number_series(df, ["high"])
        result["low"] = self._number_series(df, ["low"])
        result["volume"] = self._number_series(df, ["vol", "volume"])
        return result.sort_values("day").reset_index(drop=True)

    def _normalize_limit_list(self, df: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return df
        result = pd.DataFrame()
        result["代码"] = self._first_series(df, ["ts_code", "代码"]).map(self._to_plain_code)
        result["名称"] = self._first_series(df, ["name", "名称"]).fillna("")
        result["最新价"] = self._number_series(df, ["close", "price", "最新价"])
        result["涨跌幅"] = self._number_series(df, ["pct_chg", "涨跌幅"])
        result["成交额"] = self._number_series(df, ["amount", "turnover", "成交额"])
        result["流通市值"] = self._number_series(df, ["float_mv", "free_float", "流通市值"])
        result["总市值"] = self._number_series(df, ["total_mv", "sum_float", "总市值"])
        result["换手率"] = self._number_series(df, ["turnover_ratio", "turnover_rate", "换手率"])
        result["封单资金"] = self._number_series(df, ["fd_amount", "limit_amount", "封单资金"])
        result["首次封板时间"] = self._first_series(df, ["first_time", "first_lu_time", "首次封板时间"]).fillna("")
        result["最后封板时间"] = self._first_series(df, ["last_time", "last_lu_time", "最后封板时间"]).fillna("")
        result["炸板次数"] = self._number_series(df, ["open_times", "open_num", "炸板次数"])
        result["涨停统计"] = self._first_series(df, ["up_stat", "status", "涨停统计"]).fillna("")
        result["连板数"] = self._number_series(df, ["limit_times", "连板数"])
        result["所属行业"] = self._first_series(df, ["industry", "所属行业"]).fillna("")
        return result

    def _first_series(self, df: pd.DataFrame, names: list[str]) -> pd.Series:
        for name in names:
            if name in df.columns:
                return df[name]
        return pd.Series([None] * len(df), index=df.index)

    def _number_series(self, df: pd.DataFrame, names: list[str]) -> pd.Series:
        return pd.to_numeric(self._first_series(df, names), errors="coerce").fillna(0)

    def _compact_date(self, value: Optional[str]) -> str:
        text = str(value or "").strip()
        if not text:
            return datetime.now().strftime("%Y%m%d")
        return text.replace("-", "")[:8]

    def _display_date(self, value: Any) -> str:
        text = str(value or "").strip()
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        return text[:10]

    def _to_plain_code(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        return text.split(".")[0].replace("SH_", "").replace("SZ_", "").replace("BJ_", "")

    def _from_ts_code(self, ts_code: Any) -> str:
        text = str(ts_code or "").strip().upper()
        if not text:
            return ""
        if "_" in text and text.startswith(("SH_", "SZ_", "BJ_")):
            return text
        if "." in text:
            code, exchange = text.split(".", 1)
            prefix = {"SH": "SH", "SZ": "SZ", "BJ": "BJ"}.get(exchange, "SZ")
            digits = "".join(ch for ch in code if ch.isdigit())
            return f"{prefix}_{digits}" if digits else ""
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return ""
        if digits.startswith("6"):
            return f"SH_{digits}"
        if digits.startswith(("8", "4")):
            return f"BJ_{digits}"
        return f"SZ_{digits}"

    def _to_ts_code(self, symbol: str) -> str:
        raw = str(symbol or "").strip().upper().replace("_", ".")
        if raw.endswith((".SH", ".SZ", ".BJ")):
            return raw
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits.startswith("6"):
            return f"{digits}.SH"
        if digits.startswith(("8", "4")):
            return f"{digits}.BJ"
        return f"{digits}.SZ"

    def _to_index_ts_code(self, symbol: str) -> str:
        mapping = {
            "sh000001": "000001.SH",
            "sz399001": "399001.SZ",
            "sz399006": "399006.SZ",
            "sh000688": "000688.SH",
        }
        raw = str(symbol or "").strip().lower()
        return mapping.get(raw, self._to_ts_code(symbol))

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None
        if pd.isna(num):
            return None
        return float(num)

    def get_order_book(self, symbol: str) -> Dict[str, Any]:
        """Fetch L5 bid/ask depth for one A-share.

        TuShare Pro ``rt_k`` only exposes L1 and requires a paid add-on this
        workspace may not have. Prefer the package's ``get_realtime_quotes``
        (Sina-backed five-level snapshot), then East Money via AkShare.
        """
        plain = self._to_plain_code(symbol)
        internal = self._from_ts_code(symbol) or self._from_ts_code(plain)
        empty = {
            "symbol": internal,
            "code": plain,
            "name": None,
            "price": None,
            "pre_close": None,
            "bid": None,
            "ask": None,
            "change_percent": None,
            "asks": [],
            "bids": [],
            "volume_unit": "手",
            "trade_date": None,
            "trade_time": None,
            "source": None,
            "source_label": None,
            "data_status": "empty",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "error": None,
        }
        if not plain:
            empty["error"] = "invalid_symbol"
            return empty

        try:
            book = self._order_book_from_tushare_quotes(plain, internal)
            if book:
                return book
        except Exception as exc:  # pragma: no cover - network/provider path
            logger.warning("TuShare order book failed for %s: %s", plain, exc)

        try:
            book = self._order_book_from_akshare(plain, internal)
            if book:
                return book
        except Exception as exc:  # pragma: no cover - network/provider path
            logger.warning("AkShare order book failed for %s: %s", plain, exc)
            empty["error"] = f"{type(exc).__name__}: {exc}"

        empty["error"] = empty.get("error") or "order_book_unavailable"
        empty["source_label"] = "实时盘口不可用"
        return empty

    def _order_book_from_tushare_quotes(self, plain: str, internal: str) -> Optional[Dict[str, Any]]:
        if self.tushare is None or not hasattr(self.tushare, "get_realtime_quotes"):
            return None
        frame = self.tushare.get_realtime_quotes([plain])
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return None
        row = frame.iloc[0]
        asks = []
        bids = []
        for level in range(5, 0, -1):
            price = self._safe_float(row.get(f"a{level}_p"))
            volume = self._safe_float(row.get(f"a{level}_v"))
            asks.append({"level": level, "price": price, "volume": volume})
        for level in range(1, 6):
            price = self._safe_float(row.get(f"b{level}_p"))
            volume = self._safe_float(row.get(f"b{level}_v"))
            bids.append({"level": level, "price": price, "volume": volume})
        price = self._safe_float(row.get("price"))
        pre_close = self._safe_float(row.get("pre_close"))
        change_percent = None
        if price is not None and pre_close not in (None, 0):
            change_percent = round((price / pre_close - 1.0) * 100.0, 2)
        return {
            "symbol": internal,
            "code": plain,
            "name": str(row.get("name") or "").strip() or None,
            "price": price,
            "pre_close": pre_close,
            "bid": self._safe_float(row.get("bid")),
            "ask": self._safe_float(row.get("ask")),
            "change_percent": change_percent,
            "asks": asks,
            "bids": bids,
            "volume_unit": "手",
            "trade_date": str(row.get("date") or "").strip() or None,
            "trade_time": str(row.get("time") or "").strip() or None,
            "source": "tushare_realtime_quotes",
            "source_label": "TuShare 五档快照（新浪源）",
            "data_status": "fresh",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "error": None,
        }

    def _order_book_from_akshare(self, plain: str, internal: str) -> Optional[Dict[str, Any]]:
        if self.akshare is None:
            return None
        frame = self._akshare_attr("stock_bid_ask_em")(symbol=plain)
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return None
        mapping = {
            str(row.get("item") or "").strip(): self._safe_float(row.get("value"))
            for _, row in frame.iterrows()
        }

        def lot(value: Optional[float]) -> Optional[float]:
            if value is None:
                return None
            # East Money bid/ask volumes are in shares; normalize to 手.
            return round(value / 100.0, 2)

        asks = []
        bids = []
        for level in range(5, 0, -1):
            asks.append(
                {
                    "level": level,
                    "price": mapping.get(f"sell_{level}"),
                    "volume": lot(mapping.get(f"sell_{level}_vol")),
                }
            )
        for level in range(1, 6):
            bids.append(
                {
                    "level": level,
                    "price": mapping.get(f"buy_{level}"),
                    "volume": lot(mapping.get(f"buy_{level}_vol")),
                }
            )
        if not any(level.get("price") is not None for level in asks + bids):
            return None
        return {
            "symbol": internal,
            "code": plain,
            "name": None,
            "price": mapping.get("最新") or mapping.get("price"),
            "pre_close": mapping.get("昨收") or mapping.get("pre_close"),
            "bid": mapping.get("buy_1"),
            "ask": mapping.get("sell_1"),
            "change_percent": mapping.get("涨跌幅"),
            "asks": asks,
            "bids": bids,
            "volume_unit": "手",
            "trade_date": None,
            "trade_time": None,
            "source": "eastmoney_bid_ask",
            "source_label": "东财五档快照（AkShare）",
            "data_status": "fresh",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "error": None,
        }


market_data_provider = TushareFirstDataProvider()
