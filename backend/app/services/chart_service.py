import logging
from typing import Any, Dict, List, Optional

from app.db import db_instance


logger = logging.getLogger(__name__)


class ChartService:
    """Read-only chart access over locally persisted PostgreSQL bars."""

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
    def get_intraday_data(symbol: str) -> List[Dict[str, Any]]:
        """Return the latest stored one-minute session without provider calls."""
        normalised = ChartService._normalise_symbol(symbol)
        if not normalised:
            return []
        try:
            minute_rows = db_instance.get_kline_history(normalised, timeframe="1m")
            if not minute_rows:
                return []
            latest_date = minute_rows[-1].get("date")
            session = [item for item in minute_rows if item.get("date") == latest_date][-240:]
            daily_rows = db_instance.get_kline_history(normalised, timeframe="1d")
            previous_close = daily_rows[-2].get("close") if len(daily_rows) >= 2 else None
            return [
                {
                    "time": item.get("timestamp"),
                    "price": item.get("close"),
                    "volume": item.get("volume"),
                    **({"pre_close": previous_close, "trade_date": latest_date} if index == 0 else {}),
                }
                for index, item in enumerate(session)
            ]
        except Exception as exc:
            logger.warning("PostgreSQL intraday chart read failed for %s: %s", normalised, exc)
            return []
