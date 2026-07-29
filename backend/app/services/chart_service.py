import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from app.db import db_instance
from app.services.tushare_provider import market_data_provider as ak

try:
    import akshare as akshare_raw
except Exception:  # pragma: no cover - optional local dep
    akshare_raw = None

logger = logging.getLogger(__name__)


class ChartService:
    """Chart access over PostgreSQL bars with provider fallback for missing sessions."""

    @staticmethod
    def _get_market_prefix(code: str) -> str:
        if code.startswith("6"):
            return f"SH_{code}"
        if code.startswith(("0", "3")):
            return f"SZ_{code}"
        if code.startswith(("9", "8", "4")):
            return f"BJ_{code}"
        return code

    @staticmethod
    def _normalise_symbol(symbol: str) -> str:
        code = "".join(filter(str.isdigit, str(symbol or "")))
        return ChartService._get_market_prefix(code)

    @staticmethod
    def _public_code(normalised: str) -> str:
        digits = "".join(filter(str.isdigit, normalised))
        return digits[-6:] if digits else normalised

    @staticmethod
    def get_daily_data(symbol: str, stock_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return ascending daily bars without provider calls or cache writes."""
        normalised = ChartService._normalise_symbol(symbol)
        if not normalised:
            return []
        try:
            rows = db_instance.get_kline_history(normalised, timeframe="1d")
        except Exception as exc:
            logger.warning("PostgreSQL daily chart read failed for %s: %s", normalised, exc)
            return []
        return [
            {
                "date": item.get("date"),
                "open": item.get("open"),
                "close": item.get("close"),
                "high": item.get("high"),
                "low": item.get("low"),
                "volume": item.get("volume"),
                "source_label": item.get("source") or "PostgreSQL cache",
                "updated_at": item.get("updated_at"),
            }
            for item in rows
        ]

    @staticmethod
    def _close_plausible(candidate: Optional[float], anchor: Optional[float]) -> bool:
        """Reject stale/corrupt daily closes that diverge wildly from the live session."""
        if candidate is None or anchor is None:
            return candidate is not None
        try:
            c = float(candidate)
            a = float(anchor)
        except (TypeError, ValueError):
            return False
        if c <= 0 or a <= 0:
            return False
        ratio = max(c, a) / min(c, a)
        return ratio <= 1.35

    @staticmethod
    def _previous_close(
        normalised: str,
        trade_date: Optional[str],
        session_anchor: Optional[float] = None,
    ) -> Optional[float]:
        try:
            daily_rows = db_instance.get_kline_history(normalised, timeframe="1d")
        except Exception:
            daily_rows = []

        candidate: Optional[float] = None
        if daily_rows and trade_date:
            for index in range(len(daily_rows) - 1, -1, -1):
                row_date = str(daily_rows[index].get("date") or "")[:10]
                if row_date < str(trade_date)[:10]:
                    try:
                        candidate = float(daily_rows[index].get("close"))
                    except (TypeError, ValueError):
                        candidate = None
                    break
        if candidate is None and daily_rows and len(daily_rows) >= 2:
            try:
                candidate = float(daily_rows[-2].get("close"))
            except (TypeError, ValueError):
                candidate = None

        if ChartService._close_plausible(candidate, session_anchor):
            return candidate

        # Provider fallback: prior daily bar from raw AkShare when PG daily is missing/corrupt.
        code = ChartService._public_code(normalised)
        if not code:
            return session_anchor
        hist = akshare_raw.stock_zh_a_hist if akshare_raw is not None else None
        if hist is None:
            hist = getattr(ak, "stock_zh_a_hist", None)
        if hist is None:
            return session_anchor
        try:
            frame = hist(
                symbol=code,
                period="daily",
                start_date="20200101",
                adjust="",
            )
            if frame is None or frame.empty:
                return session_anchor
            date_col = "日期" if "日期" in frame.columns else frame.columns[0]
            close_col = "收盘" if "收盘" in frame.columns else None
            if not close_col:
                return session_anchor
            frame = frame.copy()
            frame["_d"] = pd.to_datetime(frame[date_col], errors="coerce")
            frame = frame.dropna(subset=["_d"]).sort_values("_d")
            if trade_date:
                cutoff = pd.to_datetime(str(trade_date)[:10], errors="coerce")
                prior = frame[frame["_d"] < cutoff] if pd.notna(cutoff) else frame
            else:
                prior = frame.iloc[:-1] if len(frame) >= 2 else frame
            if prior.empty:
                return session_anchor
            value = float(prior.iloc[-1][close_col])
            if ChartService._close_plausible(value, session_anchor):
                return value
        except Exception as exc:
            logger.warning("Provider previous-close fallback failed for %s: %s", code, exc)
        return session_anchor

    @staticmethod
    def _fetch_intraday_from_provider(normalised: str) -> List[Dict[str, Any]]:
        """
        Pull today's (or latest available) 1-minute session from AkShare/Eastmoney.

        TuShare equivalents require separate realtime-minute permission:
        rt_min / rt_min_daily. Prefer AkShare hist_min_em for workstation completeness.
        """
        code = ChartService._public_code(normalised)
        if not code:
            return []
        try:
            frame = ak.stock_zh_a_hist_min_em(symbol=code, period="1", adjust="")
        except Exception as exc:
            logger.warning("Provider 1m fetch failed for %s: %s", code, exc)
            return []
        if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
            return []

        time_col = "时间" if "时间" in frame.columns else None
        close_col = "收盘" if "收盘" in frame.columns else None
        open_col = "开盘" if "开盘" in frame.columns else None
        high_col = "最高" if "最高" in frame.columns else None
        low_col = "最低" if "最低" in frame.columns else None
        vol_col = "成交量" if "成交量" in frame.columns else None
        if not time_col or not close_col:
            return []

        parsed: List[Dict[str, Any]] = []
        for _, row in frame.iterrows():
            stamp = str(row.get(time_col) or "").strip()
            if not stamp:
                continue
            try:
                dt = pd.to_datetime(stamp)
            except Exception:
                continue
            trade_date = dt.strftime("%Y-%m-%d")
            try:
                close = float(row.get(close_col))
            except (TypeError, ValueError):
                continue
            item = {
                "timestamp": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "date": trade_date,
                "open": float(row.get(open_col)) if open_col and pd.notna(row.get(open_col)) else close,
                "close": close,
                "high": float(row.get(high_col)) if high_col and pd.notna(row.get(high_col)) else close,
                "low": float(row.get(low_col)) if low_col and pd.notna(row.get(low_col)) else close,
                "volume": float(row.get(vol_col)) if vol_col and pd.notna(row.get(vol_col)) else 0.0,
                "source": "akshare_stock_zh_a_hist_min_em",
            }
            parsed.append(item)
        if not parsed:
            return []

        latest_date = parsed[-1]["date"]
        session = [item for item in parsed if item["date"] == latest_date][-240:]
        session_anchor = None
        if session:
            try:
                session_anchor = float(session[0].get("open") or session[0].get("close"))
            except (TypeError, ValueError):
                session_anchor = None
        previous_close = ChartService._previous_close(normalised, latest_date, session_anchor)
        return [
            {
                "time": item["timestamp"],
                "price": item["close"],
                "volume": item["volume"],
                "source_label": item.get("source"),
                **({"pre_close": previous_close, "trade_date": latest_date} if index == 0 else {}),
            }
            for index, item in enumerate(session)
        ]

    @staticmethod
    def get_intraday_data(symbol: str) -> List[Dict[str, Any]]:
        """Return latest one-minute session; fall back to AkShare when PG 1m is empty."""
        normalised = ChartService._normalise_symbol(symbol)
        if not normalised:
            return []
        try:
            minute_rows = db_instance.get_kline_history(normalised, timeframe="1m")
            if minute_rows:
                latest_date = minute_rows[-1].get("date")
                session = [item for item in minute_rows if item.get("date") == latest_date][-240:]
                session_anchor = None
                if session:
                    try:
                        session_anchor = float(session[0].get("open") or session[0].get("close"))
                    except (TypeError, ValueError):
                        session_anchor = None
                previous_close = ChartService._previous_close(
                    normalised,
                    str(latest_date) if latest_date else None,
                    session_anchor,
                )
                return [
                    {
                        "time": item.get("timestamp"),
                        "price": item.get("close"),
                        "volume": item.get("volume"),
                        "source_label": item.get("source") or "PostgreSQL cache",
                        **({"pre_close": previous_close, "trade_date": latest_date} if index == 0 else {}),
                    }
                    for index, item in enumerate(session)
                ]
        except Exception as exc:
            logger.warning("PostgreSQL intraday chart read failed for %s: %s", normalised, exc)

        provider_rows = ChartService._fetch_intraday_from_provider(normalised)
        if provider_rows:
            logger.info(
                "Intraday fallback served %s bars for %s from provider at %s",
                len(provider_rows),
                normalised,
                datetime.now().isoformat(timespec="seconds"),
            )
        return provider_rows
