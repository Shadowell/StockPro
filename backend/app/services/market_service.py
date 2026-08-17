from app.services.tushare_provider import market_data_provider as ak
import pandas as pd
import logging
import math
import calendar as pycalendar
import hashlib
import requests
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Sequence
from functools import lru_cache
import time

from app.db import get_database
from app.core.config import settings
from app.services.market_research_service import MarketResearchService

import threading
from app.db import db_instance

db = db_instance

logger = logging.getLogger(__name__)

EASTMONEY_A_SPOT_URLS = [
    "https://82.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
]
EASTMONEY_A_SPOT_FIELDS = (
    "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,"
    "f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152"
)
EASTMONEY_A_SPOT_HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://quote.eastmoney.com/center/gridlist.html",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
    ),
}
EASTMONEY_A_SPOT_COLUMN_MAP = {
    "f2": "最新价",
    "f3": "涨跌幅",
    "f4": "涨跌额",
    "f5": "成交量",
    "f6": "成交额",
    "f7": "振幅",
    "f8": "换手率",
    "f9": "市盈率-动态",
    "f10": "量比",
    "f12": "代码",
    "f14": "名称",
    "f15": "最高",
    "f16": "最低",
    "f17": "今开",
    "f18": "昨收",
    "f20": "总市值",
    "f21": "流通市值",
    "f23": "市净率",
}


def _find_column(df: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
    """Find the first matching column name from a list of candidates."""
    # First try exact match
    for col in candidates:
        if col in df.columns:
            return col
    
    # Then try case-insensitive and stripped match
    stripped_cols = {c.strip(): c for c in df.columns}
    for cand in candidates:
        stripped_cand = cand.strip()
        if stripped_cand in stripped_cols:
            return stripped_cols[stripped_cand]
            
    # Then try partial match
    for cand in candidates:
        for c in df.columns:
            if cand in c or c in cand:
                return c
                
    return None


def _fetch_eastmoney_a_spot_direct(page_size: int = 100, timeout: int = 12) -> pd.DataFrame:
    base_params = {
        "pn": "1",
        "pz": str(page_size),
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
        "fields": EASTMONEY_A_SPOT_FIELDS,
    }
    rows: list[dict[str, Any]] = []
    total = 0
    page = 1

    while page == 1 or (total and len(rows) < total):
        params = {**base_params, "pn": str(page)}
        data_json: dict[str, Any] | None = None
        last_error: Exception | None = None

        for url in EASTMONEY_A_SPOT_URLS:
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers=EASTMONEY_A_SPOT_HEADERS,
                    timeout=timeout,
                )
                response.raise_for_status()
                data_json = response.json()
                break
            except Exception as exc:
                last_error = exc

        if data_json is None:
            if page == 1:
                raise RuntimeError(f"EastMoney direct request failed: {last_error}")
            logger.warning("EastMoney direct page %s failed, using %s partial rows: %s", page, len(rows), last_error)
            break

        data = data_json.get("data") or {}
        diff = data.get("diff") or []
        if not isinstance(diff, list) or not diff:
            break

        total = int(data.get("total") or len(diff))
        rows.extend(item for item in diff if isinstance(item, dict))

        if len(diff) < page_size:
            break
        page += 1
        if page > 1:
            time.sleep(0.15)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).rename(columns=EASTMONEY_A_SPOT_COLUMN_MAP)
    for column in ("代码", "名称"):
        if column not in df.columns:
            df[column] = ""
    return df


# Common column name mappings for reuse
COLUMN_MAPPINGS = {
    "code": ["代码", "股票代码", "symbol", "证券代码", "ts_code", "code"],
    "name": ["名称", "股票名称", "name", "证券简称", "ts_name", "股票简称"],
    "price": ["最新价", "现价", "当前价格", "current_price", "price"],
    "change_percent": ["涨跌幅", "涨跌幅%", "pct_change"],
    "time": ["时间", "time", "日期时间", "datetime", "公告日期", "date", "日期", "发布时间"],
    "title": ["标题", "title", "新闻标题", "内容", "摘要", "公告标题", "公告内容"],
    "url": ["链接", "url", "网址"],
    "open": ["开盘", "open"],
    "close": ["收盘", "close"],
    "high": ["最高", "high"],
    "low": ["最低", "low"],
    "volume": ["成交量", "volume"],
    "amount": ["成交额", "amount"],
    "turnover": ["换手率", "turnover"],
    "rank": ["排名", "rank", "序号"],
    "hot": ["热度", "hot", "热度值", "热度值(万)", "热度指数"],
    "reason": ["上榜解读", "rank_reason", "解读", "原因"],
    "tags": ["标签", "concept", "题材", "概念"],
    "lianban": ["连板数"],
}

# Time-based cache decorator
def time_limited_cache(expiration_seconds=300):  # Default 5 minutes
    """
    Cache decorator that expires after a specified time
    """
    def decorator(func):
        cache = {}
        
        def wrapper(*args, **kwargs):
            # Create a cache key from function name and arguments
            key = (func.__name__, args, tuple(sorted(kwargs.items())))
            current_time = time.time()
            
            # Check if cache exists and hasn't expired
            if key in cache:
                result, timestamp = cache[key]
                if current_time - timestamp < expiration_seconds:
                    return result
                else:
                    # Remove expired cache entry
                    del cache[key]
            
            # Call the function and cache the result
            result = func(*args, **kwargs)
            cache[key] = (result, current_time)
            return result
        
        # Add a method to clear the cache
        wrapper.clear_cache = lambda: cache.clear()
        return wrapper
    
    return decorator


class MarketService:
    @staticmethod
    def _latest_timestamp(rows: Sequence[Dict[str, Any]], field: str = "updated_at") -> Optional[Any]:
        values = [row.get(field) for row in rows if row.get(field)]
        return max(values) if values else None

    @staticmethod
    def _is_stale_timestamp(value: Any, max_age_hours: int = 36) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return True
        if not isinstance(value, datetime):
            return True
        now = datetime.now(value.tzinfo) if value.tzinfo else datetime.now()
        return now - value > timedelta(hours=max_age_hours)

    @staticmethod
    def _valid_short_line_cache(rows: Sequence[Dict[str, Any]]) -> bool:
        if not rows:
            return False
        if any(MarketService._is_stale_timestamp(row.get("updated_at")) for row in rows):
            return False
        return any((row.get("price") is not None and float(row.get("price") or 0) != 0) for row in rows)

    @staticmethod
    def _exchange_bucket(code: Any) -> str:
        text = str(code or "").strip().upper().replace(".", "_")
        if text.startswith("SH_") or text.startswith("SH"):
            return "sh"
        if text.startswith("SZ_") or text.startswith("SZ"):
            return "sz"
        if text.startswith("BJ_") or text.startswith("BJ"):
            return "bj"
        digits = "".join(ch for ch in text if ch.isdigit())
        raw = digits[-6:] if len(digits) >= 6 else digits
        if raw.startswith("6"):
            return "sh"
        if raw.startswith(("0", "3")):
            return "sz"
        if raw.startswith(("9", "8", "4")):
            return "bj"
        return ""

    @staticmethod
    def _external_fetch_enabled() -> bool:
        return bool(settings.ENABLE_EXTERNAL_MARKET_FETCH)

    @staticmethod
    def _get_indices_from_daily() -> List[Dict[str, Any]]:
        """使用日线数据获取指数（最可靠的备用方案）"""
        target_map = {
            "上证指数": "sh000001",
            "深证成指": "sz399001", 
            "创业板指": "sz399006",
            "科创50": "sh000688"
        }
        
        indices_data = []
        for name, symbol in target_map.items():
            try:
                df = ak.stock_zh_index_daily(symbol=symbol)
                if df is not None and not df.empty:
                    row = df.iloc[-1]  # 最新一天
                    prev_row = df.iloc[-2] if len(df) > 1 else row
                    
                    price = float(row.get('close', 0))
                    prev_close = float(prev_row.get('close', price))
                    change_amount = price - prev_close
                    change_percent = (change_amount / prev_close * 100) if prev_close > 0 else 0
                    
                    indices_data.append({
                        "name": name,
                        "price": round(price, 2),
                        "change_amount": round(change_amount, 2),
                        "change_percent": round(change_percent, 2)
                    })
            except Exception as e:
                logger.warning(f"获取{name}日线数据失败: {e}")
                continue
        
        return indices_data

    @staticmethod
    def _get_indices_from_sina() -> List[Dict[str, Any]]:
        """使用新浪接口获取指数数据（备用数据源）"""
        try:
            df = ak.stock_zh_index_spot_sina()
            if df is None or df.empty:
                return []
            
            # 新浪接口的列名和目标指数映射
            target_map = {
                "上证指数": "sh000001",
                "深证成指": "sz399001", 
                "创业板指": "sz399006",
                "科创50": "sh000688"
            }
            
            indices_data = []
            for name, code in target_map.items():
                hit = df[df["代码"] == code]
                if not hit.empty:
                    row = hit.iloc[0]
                    indices_data.append({
                        "name": name,
                        "price": MarketService._safe_float(row.get("最新价")),
                        "change_amount": MarketService._safe_float(row.get("涨跌额")),
                        "change_percent": MarketService._safe_float(row.get("涨跌幅"))
                    })
            return indices_data
        except Exception as e:
            logger.error(f"Error fetching indices from Sina: {e}")
            return []

    @staticmethod
    def _get_stocks_from_sina() -> pd.DataFrame:
        """使用新浪接口获取股票实时数据（备用数据源）"""
        try:
            df = ak.stock_zh_a_spot()
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.error(f"Error fetching stocks from Sina: {e}")
            return pd.DataFrame()

    @staticmethod
    def _get_sentiment_from_fund_flow() -> Dict[str, Any]:
        """从资金流向接口获取市场情绪数据"""
        try:
            df = ak.stock_fund_flow_concept(symbol="即时")
            if df is None or df.empty:
                return None
            
            # 计算涨跌幅为正的板块数量
            df['行业-涨跌幅'] = pd.to_numeric(df['行业-涨跌幅'], errors='coerce').fillna(0.0)
            advancing = int((df['行业-涨跌幅'] > 0).sum())
            declining = int((df['行业-涨跌幅'] < 0).sum())
            unchanged = int((df['行业-涨跌幅'] == 0).sum())
            
            total = advancing + declining
            sentiment_score = 50.0
            if total > 0:
                sentiment_score = (advancing / total) * 100
            
            sentiment_status = "中性"
            if sentiment_score >= 70: sentiment_status = "火热"
            elif sentiment_score >= 60: sentiment_status = "活跃"
            elif sentiment_score <= 30: sentiment_status = "冰点"
            elif sentiment_score <= 40: sentiment_status = "低迷"
            
            # 计算总资金流入
            total_inflow = pd.to_numeric(df['流入资金'], errors='coerce').fillna(0.0).sum()
            
            return {
                "sentiment": {
                    "score": round(sentiment_score, 1),
                    "status": sentiment_status,
                    "advancing": advancing,
                    "declining": declining,
                    "unchanged": unchanged
                },
                "volume": {
                    "amount": round(total_inflow, 2),
                    "unit": "亿",
                    "ratio": 1.0
                }
            }
        except Exception as e:
            logger.error(f"Error fetching sentiment from fund flow: {e}")
            return None

    @staticmethod
    def _shanghai_now() -> datetime:
        try:
            from zoneinfo import ZoneInfo

            return datetime.now(ZoneInfo("Asia/Shanghai"))
        except Exception:
            return datetime.now()

    @staticmethod
    def market_session(now: Optional[datetime] = None) -> Dict[str, Any]:
        """A-share session phase for operator status lights (clock-based, not holiday calendar)."""
        current = now or MarketService._shanghai_now()
        if current.tzinfo is not None:
            try:
                from zoneinfo import ZoneInfo

                current = current.astimezone(ZoneInfo("Asia/Shanghai"))
            except Exception:
                pass
        weekday = current.weekday()
        minutes = current.hour * 60 + current.minute
        if weekday >= 5:
            return {
                "phase": "weekend",
                "label": "休市",
                "is_open": False,
                "detail": "周末休市",
                "local_time": current.strftime("%H:%M"),
            }
        # 09:15-09:25 集合竞价；09:25-09:30 开盘准备；09:30-11:30 / 13:00-15:00 连续竞价
        if minutes < 9 * 60 + 15:
            phase, label, detail = "pre_open", "盘前", "未开盘"
        elif minutes < 9 * 60 + 25:
            phase, label, detail = "auction", "竞价中", "集合竞价"
        elif minutes < 9 * 60 + 30:
            phase, label, detail = "auction", "竞价中", "开盘准备"
        elif minutes <= 11 * 60 + 30:
            phase, label, detail = "open", "开盘中", "上午连续竞价"
        elif minutes < 13 * 60:
            phase, label, detail = "lunch", "午休", "午间休市"
        elif minutes <= 15 * 60:
            phase, label, detail = "open", "开盘中", "下午连续竞价"
        else:
            phase, label, detail = "closed", "已收盘", "今日已收盘"
        return {
            "phase": phase,
            "label": label,
            "is_open": phase == "open",
            "detail": detail,
            "local_time": current.strftime("%H:%M"),
        }

    @staticmethod
    def _is_market_open() -> bool:
        """检查当前是否是连续竞价交易时间。"""
        return bool(MarketService.market_session()["is_open"])


    @staticmethod
    def _empty_market_pulse() -> Dict[str, Any]:
        return {
            "source_label": "PostgreSQL realtime cache",
            "universe_count": None,
            "rise_fall_ratio": None,
            "median_change_percent": None,
            "avg_change_percent": None,
            "strong_up_5": None,
            "strong_up_7": None,
            "weak_down_5": None,
            "weak_down_7": None,
            "limit_up_est": None,
            "limit_down_est": None,
            "price_limit_rule_covered": 0,
            "price_limit_rule_excluded": 0,
            "price_limit_rule_unknown": 0,
            "amount_top10_share": None,
            "avg_turnover": None,
            "avg_amplitude": None,
            "avg_volume_ratio": None,
            "volume_ratio_gt2": None,
            "active_traded": None,
        }

    @staticmethod
    def _price_limit_rule(
        code: Any,
        name: Any,
        *,
        listing_trade_days: Any = None,
        is_st: Any = None,
    ) -> Dict[str, Any]:
        """Return the current exchange price-limit rule for an A-share cache row.

        Since 2026-07-06, Shanghai and Shenzhen main-board risk-warning
        securities use the same 10% limit as other main-board stocks. STAR and
        ChiNext use 20%, while Beijing uses 30%. IPOs have no price limit for
        their first five trading days on Shanghai/Shenzhen and first trading
        day on Beijing. Unknown listing-stage evidence stays unknown so a
        partial cache cannot be presented as a full-market limit estimate.
        """
        digits = "".join(ch for ch in str(code or "") if ch.isdigit())[-6:]
        exchange = MarketService._exchange_from_code(digits)
        risk_warning = bool(is_st) if is_st is not None else "ST" in str(name or "").upper()
        if exchange in {"STAR", "CHINEXT"}:
            rule_id = "star_chinext_20"
            threshold = 20.0
            no_limit_days = 5
        elif exchange == "BJ":
            rule_id = "bj_30"
            threshold = 30.0
            no_limit_days = 1
        elif exchange in {"SH", "SZ"}:
            rule_id = "sh_sz_main_10"
            threshold = 10.0
            no_limit_days = 5
        else:
            rule_id = "unknown"
            threshold = None
            no_limit_days = None

        try:
            trading_days = int(listing_trade_days) if listing_trade_days is not None else None
        except (TypeError, ValueError):
            trading_days = None
        new_stock_marker = str(name or "").strip().upper()[:1]
        if trading_days is not None and no_limit_days is not None:
            has_price_limit = trading_days > no_limit_days
        elif new_stock_marker == "N" or (
            new_stock_marker == "C" and exchange in {"SH", "SZ", "STAR", "CHINEXT"}
        ):
            has_price_limit = False
        else:
            has_price_limit = None
        return {
            "rule_id": rule_id,
            "exchange": exchange,
            "threshold_pct": threshold,
            "has_price_limit": has_price_limit,
            "listing_trade_days": trading_days,
            "is_st": risk_warning,
        }

    @staticmethod
    def _limit_threshold_pct(code: Any, name: Any) -> float:
        rule = MarketService._price_limit_rule(
            code,
            name,
            listing_trade_days=6,
        )
        return float(rule.get("threshold_pct") or 10.0) - 0.2

    @staticmethod
    def _build_market_pulse(
        stocks: Sequence[Dict[str, Any]],
        advancing: int,
        declining: int,
        unchanged: int,
    ) -> Dict[str, Any]:
        """Derive operator-facing breadth diagnostics from the realtime stock cache.

        Uses board-aware limit thresholds as estimates (not exchange-confirmed seals).
        Prefer sealed market-evidence short-line metrics for official limit ecology.
        """
        pulse = MarketService._empty_market_pulse()
        pulse["universe_count"] = len(stocks)
        pulse["active_traded"] = sum(1 for row in stocks if float(row.get("amount") or 0) > 0)
        if advancing + declining > 0:
            pulse["rise_fall_ratio"] = round(advancing / declining, 3) if declining else float(advancing)

        changes: List[float] = []
        strong_up_5 = strong_up_7 = weak_down_5 = weak_down_7 = 0
        limit_up = limit_down = 0
        price_limit_rule_covered = 0
        price_limit_rule_excluded = 0
        price_limit_rule_unknown = 0
        turnovers: List[float] = []
        amplitudes: List[float] = []
        volume_ratios: List[float] = []
        volume_ratio_gt2 = 0
        amount_rows: List[float] = []

        for row in stocks:
            raw = row.get("change_percent")
            if raw is None:
                continue
            try:
                change = float(raw)
            except (TypeError, ValueError):
                continue
            changes.append(change)
            if change >= 5:
                strong_up_5 += 1
            if change >= 7:
                strong_up_7 += 1
            if change <= -5:
                weak_down_5 += 1
            if change <= -7:
                weak_down_7 += 1
            rule = MarketService._price_limit_rule(
                row.get("code"),
                row.get("name"),
                listing_trade_days=row.get("listing_trade_days"),
                is_st=row.get("is_st"),
            )
            if rule.get("has_price_limit") is True:
                price_limit_rule_covered += 1
                threshold = float(rule.get("threshold_pct") or 0.0) - 0.2
                if change >= threshold:
                    limit_up += 1
                if change <= -threshold:
                    limit_down += 1
            elif rule.get("has_price_limit") is False:
                price_limit_rule_excluded += 1
            else:
                price_limit_rule_unknown += 1

            turnover = row.get("turnover")
            if turnover is not None:
                try:
                    turn_value = float(turnover)
                    if 0 < turn_value < 100:
                        turnovers.append(turn_value)
                except (TypeError, ValueError):
                    pass
            amplitude = row.get("amplitude")
            if amplitude is not None:
                try:
                    amp_value = float(amplitude)
                    if 0 < amp_value < 100:
                        amplitudes.append(amp_value)
                except (TypeError, ValueError):
                    pass
            volume_ratio = row.get("volume_ratio")
            if volume_ratio is not None:
                try:
                    ratio_value = float(volume_ratio)
                    if 0 < ratio_value < 100:
                        volume_ratios.append(ratio_value)
                        if ratio_value >= 2:
                            volume_ratio_gt2 += 1
                except (TypeError, ValueError):
                    pass
            amount = row.get("amount")
            if amount is not None:
                try:
                    amount_rows.append(float(amount))
                except (TypeError, ValueError):
                    pass

        if changes:
            ordered = sorted(changes)
            mid = len(ordered) // 2
            median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
            pulse["median_change_percent"] = round(median, 3)
            pulse["avg_change_percent"] = round(sum(changes) / len(changes), 3)
            pulse["strong_up_5"] = strong_up_5
            pulse["strong_up_7"] = strong_up_7
            pulse["weak_down_5"] = weak_down_5
            pulse["weak_down_7"] = weak_down_7
            if price_limit_rule_unknown == 0:
                pulse["limit_up_est"] = limit_up
                pulse["limit_down_est"] = limit_down
            pulse["price_limit_rule_covered"] = price_limit_rule_covered
            pulse["price_limit_rule_excluded"] = price_limit_rule_excluded
            pulse["price_limit_rule_unknown"] = price_limit_rule_unknown
        if turnovers:
            pulse["avg_turnover"] = round(sum(turnovers) / len(turnovers), 3)
        if amplitudes:
            pulse["avg_amplitude"] = round(sum(amplitudes) / len(amplitudes), 3)
        if volume_ratios:
            pulse["avg_volume_ratio"] = round(sum(volume_ratios) / len(volume_ratios), 3)
            pulse["volume_ratio_gt2"] = volume_ratio_gt2
        total_amount = sum(amount_rows)
        if total_amount > 0:
            top10 = sum(sorted(amount_rows, reverse=True)[:10])
            pulse["amount_top10_share"] = round(top10 / total_amount * 100, 2)
        # Keep breadth counts available for consumers that only read pulse.
        pulse["advancing"] = advancing
        pulse["declining"] = declining
        pulse["unchanged"] = unchanged
        return pulse

    @staticmethod
    def get_market_overview() -> Dict[str, Any]:
        """获取市场概览数据 - 非开盘时间展示昨日数据，开盘时间展示实时数据"""
        now = datetime.now()
        session = MarketService.market_session()
        
        # 优先从数据库读取缓存数据
        indices_data = db.get_market_indices_realtime()
        stocks = db.get_all_stocks_realtime(include_listing_status=False)
        
        # Overview must stay fast for page rendering. Full-market stock fetches are heavy
        # and unreliable on some networks, so this endpoint only uses realtime cache.
        if not stocks or len(stocks) == 0:
            logger.info("No cached realtime stocks for market overview; returning neutral breadth data")
            stocks = []
        
        if not indices_data:
            logger.info("No cached indices for market overview; page reads remain PostgreSQL-only")
            indices_data = []
        
        stock_snapshot_updated_at = MarketService._latest_timestamp(stocks)
        stock_snapshot_state = "unavailable" if not stocks else (
            "stale" if MarketService._is_stale_timestamp(stock_snapshot_updated_at) else "fresh"
        )
        index_snapshot_updated_at = MarketService._latest_timestamp(indices_data)
        index_snapshot_state = "unavailable" if not indices_data else (
            "stale" if MarketService._is_stale_timestamp(index_snapshot_updated_at) else "fresh"
        )
        sentiment_data = {
            "score": None,
            "status": "未同步",
            "advancing": None,
            "declining": None,
            "unchanged": None,
        }
        volume_data = {
            "amount": None,
            "unit": "亿",
            "ratio": None,
            "sh_amount": None,
            "sz_amount": None,
            "bj_amount": None,
        }
        market_breadth = {"up": None, "down": None, "flat": None}
        market_pulse: Dict[str, Any] = MarketService._empty_market_pulse()
        
        if stocks:
            # 计算情绪数据
            valid_changes = [
                float(s["change_percent"])
                for s in stocks
                if s.get("change_percent") is not None
            ]
            advancing = sum(1 for value in valid_changes if value > 0)
            declining = sum(1 for value in valid_changes if value < 0)
            unchanged = sum(1 for value in valid_changes if value == 0)
            
            total = advancing + declining
            if total > 0:
                score = round((advancing / total) * 100, 1)
            else:
                score = None
            
            if score is None:
                status = "不可用"
            elif score >= 80:
                status = "火热"
            elif score >= 60:
                status = "活跃"
            elif score >= 40:
                status = "中性"
            elif score >= 20:
                status = "低迷"
            else:
                status = "冰冷"
            
            sentiment_data = {
                "score": score,
                "status": status,
                "advancing": advancing,
                "declining": declining,
                "unchanged": unchanged
            }
            market_breadth = {"up": advancing, "down": declining, "flat": unchanged}
            market_pulse = MarketService._build_market_pulse(stocks, advancing, declining, unchanged)
            
            # 计算成交额
            valid_amounts = [float(s["amount"]) for s in stocks if s.get("amount") is not None]
            total_amount = sum(valid_amounts) / 100_000_000 if valid_amounts else None
            sh_values = [float(s["amount"]) for s in stocks if s.get("amount") is not None and MarketService._exchange_bucket(s.get("code")) == "sh"]
            sz_values = [float(s["amount"]) for s in stocks if s.get("amount") is not None and MarketService._exchange_bucket(s.get("code")) == "sz"]
            bj_values = [float(s["amount"]) for s in stocks if s.get("amount") is not None and MarketService._exchange_bucket(s.get("code")) == "bj"]
            
            # 计算平均量比
            ratios = [s.get('volume_ratio', 0) or 0 for s in stocks if s.get('volume_ratio') is not None and 0 < (s.get('volume_ratio') or 0) < 100]
            avg_ratio = round(sum(ratios) / len(ratios), 2) if ratios else None
            
            volume_data = {
                "amount": round(total_amount, 2) if total_amount is not None else None,
                "unit": "亿",
                "ratio": avg_ratio,
                "sh_amount": round(sum(sh_values) / 100_000_000, 2) if sh_values else None,
                "sz_amount": round(sum(sz_values) / 100_000_000, 2) if sz_values else None,
                "bj_amount": round(sum(bj_values) / 100_000_000, 2) if bj_values else None,
            }
            if market_pulse.get("avg_volume_ratio") is None and avg_ratio is not None:
                market_pulse["avg_volume_ratio"] = avg_ratio
        
        return {
            "indices": indices_data,
            "sentiment": sentiment_data,
            "volume": volume_data,
            "market_breadth": market_breadth,
            "market_pulse": market_pulse,
            "data_status": {
                "stock_snapshot_state": stock_snapshot_state,
                "stock_snapshot_count": len(stocks),
                "stock_snapshot_updated_at": stock_snapshot_updated_at,
                "index_snapshot_state": index_snapshot_state,
                "index_snapshot_count": len(indices_data),
                "index_snapshot_updated_at": index_snapshot_updated_at,
                "source_label": "PostgreSQL realtime cache",
                "message": "全市场实时快照未同步" if not stocks else (
                    "全市场实时快照已陈旧" if stock_snapshot_state == "stale" else "全市场实时快照可用"
                ),
            },
            "is_open": bool(session["is_open"]),
            "session_phase": session["phase"],
            "session_label": session["label"],
            "session_detail": session["detail"],
            "session_local_time": session["local_time"],
            "last_update": stock_snapshot_updated_at or index_snapshot_updated_at,
            "response_generated_at": now.isoformat(),
        }

    @staticmethod
    def get_short_line_indices() -> List[Dict[str, Any]]:
        """Read current short-line cache, falling back to the latest sealed market evidence."""
        results = db.get_short_line_indices_realtime()
        if MarketService._valid_short_line_cache(results):
            return results

        research = MarketResearchService(db)
        snapshots = research.list_snapshots(market_scope="all_a", limit=1)
        if not snapshots:
            return []
        snapshot = snapshots[0]
        sentiment = research.sentiment(int(snapshot["id"]))
        wanted = (
            "limit_up_count",
            "limit_down_count",
            "broken_board_count",
            "highest_board",
            "rise_count",
            "fall_count",
            "seal_rate",
            "rise_fall_ratio",
        )
        metrics = {item["metric_code"]: item for item in sentiment["metrics"]}
        output: List[Dict[str, Any]] = []
        for code in wanted:
            metric = metrics.get(code)
            if not metric or metric.get("value") is None:
                continue
            output.append({
                "code": code,
                "name": metric["label"],
                "price": metric["value"],
                "change_percent": None,
                "change_amount": None,
                "updated_at": snapshot.get("captured_at") or snapshot.get("available_at"),
                "trade_date": snapshot.get("trade_date"),
                "snapshot_id": snapshot.get("id"),
                "data_state": "sealed_snapshot",
                "source_label": metric.get("source_label"),
                "unit": metric.get("unit"),
                "definition": metric.get("definition"),
                "comparison_state": "unavailable",
            })
        return output

    @staticmethod
    def _fetch_main_indices() -> List[Dict[str, Any]]:
        """获取主要指数数据 - 使用日K线接口（更稳定）"""
        try:
            target_map = {
                "上证指数": "sh000001",
                "深证成指": "sz399001",
                "创业板指": "sz399006",
                "科创50": "sh000688"
            }
            
            indices_data = []
            for name, symbol in target_map.items():
                try:
                    # 直接使用日K线接口，更稳定
                    df = ak.stock_zh_index_daily(symbol=symbol)
                    if df is not None and not df.empty:
                        row = df.iloc[-1]
                        prev_row = df.iloc[-2] if len(df) > 1 else row
                        
                        price = float(row.get('close', 0))
                        prev_close = float(prev_row.get('close', price))
                        change_amount = price - prev_close
                        change_percent = (change_amount / prev_close * 100) if prev_close > 0 else 0
                        
                        indices_data.append({
                            "name": name,
                            "code": symbol,
                            "price": round(price, 2),
                            "change_amount": round(change_amount, 2),
                            "change_percent": round(change_percent, 2)
                        })
                        logger.debug(f"获取{name}成功: {price}")
                except Exception as e:
                    logger.warning(f"获取{name}失败: {e}")
            
            logger.info(f"成功获取 {len(indices_data)} 个主要指数")
            return indices_data
        except Exception as e:
            logger.error(f"获取主要指数失败: {e}")
            return []

    @staticmethod
    def _upsert_concept_kline_async(data: List[Dict[str, Any]]):
        def _do_upsert():
            try:
                if not data:
                    return
                # Split into chunks
                chunk_size = 500
                for i in range(0, len(data), chunk_size):
                    chunk = data[i:i + chunk_size]
                    # 使用本地数据库插入数据
                    # 由于本地数据库不需要upsert，我们直接使用批量插入
                    # 这里可以根据具体需求实现相应的数据库操作
                    pass
            except Exception as e:
                logger.error(f"Failed to upsert concept kline: {e}")
        
        threading.Thread(target=_do_upsert).start()
    @staticmethod
    def _to_code(symbol: str) -> str:
        text = str(symbol or "").strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 6:
            return digits[-6:]
        return digits

    @staticmethod
    def _safe_float(val: Any, default: float = 0.0) -> float:
        try:
            num = pd.to_numeric(val, errors="coerce")
            if num is None or pd.isna(num):
                return default
            out = float(num)
            return out if math.isfinite(out) else default
        except Exception:
            return default

    @staticmethod
    def get_all_sectors():
        if not MarketService._external_fetch_enabled():
            logger.info("External market fetch disabled; returning empty sector list")
            return []

        try:
            # Use EastMoney for comprehensive sector ranking
            df = ak.stock_board_industry_name_em()
            if df.empty:
                return []
            
            # Map columns to schema
            sectors = []
            for _, row in df.iterrows():
                sectors.append({
                    "rank": row['排名'],
                    "name": row['板块名称'],
                    "code": row['板块代码'],
                    "price": row['最新价'],
                    "change_amount": row['涨跌额'],
                    "change_percent": row['涨跌幅'],
                    "market_cap": row['总市值'],
                    "turnover_rate": row['换手率'],
                    "leading_stock": row['领涨股票'],
                    "leading_stock_change": row['领涨股票-涨跌幅']
                })
            return sectors
        except Exception as e:
            logger.error(f"Error fetching all sectors: {e}")
            return []

    @staticmethod
    @time_limited_cache(expiration_seconds=300)
    def _get_cached_all_stocks():
        if not MarketService._external_fetch_enabled():
            logger.info("External market fetch disabled; returning empty stock cache")
            return []

        try:
            df = None
            
            # 带重试的获取函数
            def fetch_with_retry(fetch_func, name, max_retries=2):
                for attempt in range(max_retries):
                    try:
                        result = fetch_func()
                        if result is not None and not result.empty:
                            logger.info(f"Successfully fetched {len(result)} stocks from {name} (attempt {attempt + 1})")
                            return result
                    except Exception as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"{name} attempt {attempt + 1} failed: {e}, retrying...")
                            time.sleep(0.5)
                        else:
                            logger.warning(f"{name} failed after {max_retries} attempts: {e}")
                return None
            
            # Priority 1: Try East Money interface with retry
            df = fetch_with_retry(ak.stock_zh_a_spot_em, "EastMoney", max_retries=2)

            # Priority 2: Direct EastMoney fallback with browser headers and controlled paging
            if df is None or df.empty:
                logger.info("Trying direct EastMoney A-share spot fallback...")
                try:
                    direct_df = _fetch_eastmoney_a_spot_direct()
                    if direct_df is not None and not direct_df.empty:
                        logger.info("Successfully fetched %s stocks from direct EastMoney fallback", len(direct_df))
                        df = direct_df
                except Exception as e:
                    logger.warning("Direct EastMoney fallback failed: %s", e)

            # Priority 3: Try hot rank as a lightweight alternative
            if df is None or df.empty:
                logger.info("Trying stock_hot_rank_em as alternative...")
                try:
                    hot_df = ak.stock_hot_rank_em()
                    if hot_df is not None and not hot_df.empty:
                        logger.info(f"Got {len(hot_df)} stocks from hot rank")
                        # 重命名列以匹配预期格式
                        col_map = {
                            '代码': '代码',
                            '股票名称': '名称',
                            '最新价': '最新价',
                            '涨跌幅': '涨跌幅',
                            '涨跌额': '涨跌额',
                        }
                        df = hot_df.rename(columns=col_map)
                except Exception as e:
                    logger.warning(f"Hot rank failed: {e}")

            if df is None or df.empty:
                logger.warning("No stock data available from any interface")
                return []

            # Identify the columns based on the source
            code_col = _find_column(df, COLUMN_MAPPINGS["code"])
            name_col = _find_column(df, COLUMN_MAPPINGS["name"])
            price_col = _find_column(df, COLUMN_MAPPINGS["price"])
            change_pct_col = _find_column(df, COLUMN_MAPPINGS["change_percent"])
            volume_col = _find_column(df, ["成交量", "volume", "vol"])
            amount_col = _find_column(df, COLUMN_MAPPINGS["amount"])
            turnover_col = _find_column(df, COLUMN_MAPPINGS["turnover"])
            volume_ratio_col = _find_column(df, ["量比", "volume_ratio"])
            pe_dynamic_col = _find_column(df, ["市盈率-动态", "pe", "dynamic_pe"])
            pb_col = _find_column(df, ["市净率", "pb"])
            total_market_cap_col = _find_column(df, ["总市值", "total_market_cap"])
            float_market_cap_col = _find_column(df, ["流通市值", "float_market_cap"])
            amplitude_col = _find_column(df, ["振幅", "amplitude"])

            # Filter and map
            stocks = []
            for _, row in df.iterrows():
                try:
                    code = str(row.get(code_col) or '').strip() if code_col else ''
                    name = str(row.get(name_col) or '').strip() if name_col else ''
                    if not code:
                        continue
                    
                    stocks.append(
                        {
                            "code": code,
                            "name": name,
                            "price": MarketService._safe_float(row.get(price_col)) if price_col else 0.0,
                            "change_percent": MarketService._safe_float(row.get(change_pct_col)) if change_pct_col else 0.0,
                            "volume": MarketService._safe_float(row.get(volume_col)) if volume_col else 0.0,
                            "amount": MarketService._safe_float(row.get(amount_col)) if amount_col else 0.0,
                            "turnover": MarketService._safe_float(row.get(turnover_col)) if turnover_col else 0.0,
                            "volume_ratio": MarketService._safe_float(row.get(volume_ratio_col)) if volume_ratio_col else None,
                            "pe_dynamic": MarketService._safe_float(row.get(pe_dynamic_col)) if pe_dynamic_col else None,
                            "pb": MarketService._safe_float(row.get(pb_col)) if pb_col else None,
                            "total_market_cap": MarketService._safe_float(row.get(total_market_cap_col)) if total_market_cap_col else None,
                            "float_market_cap": MarketService._safe_float(row.get(float_market_cap_col)) if float_market_cap_col else None,
                            "amplitude": MarketService._safe_float(row.get(amplitude_col)) if amplitude_col else None,
                        }
                    )
                except Exception as row_error:
                    logger.warning(f"Error processing stock row: {row_error}")
                    continue
            return stocks
        except Exception as e:
            logger.error(f"Error fetching all stocks: {e}")
            return []

    @staticmethod
    def get_all_stocks():
        start_time = time.time()
        logger.info("Fetching all stocks...")
        stocks = MarketService._get_cached_all_stocks()
        logger.info(f"Fetched {len(stocks)} stocks in {time.time() - start_time:.2f} seconds")
        return stocks

    @staticmethod
    def get_order_book(symbol: str) -> Dict[str, Any]:
        """On-demand L5 depth. Uses live quote sources, not PostgreSQL cache."""
        code = MarketService._to_code(symbol)
        if not code:
            return {
                "symbol": "",
                "code": "",
                "asks": [],
                "bids": [],
                "volume_unit": "手",
                "data_status": "empty",
                "error": "invalid_symbol",
                "source_label": "无效标的",
            }
        try:
            payload = ak.get_order_book(code)
            return {
                **(payload if isinstance(payload, dict) else {}),
                "price_basis": "unadjusted",
                "price_usage": "execution_quote",
            }
        except Exception as exc:
            logger.warning("get_order_book failed for %s: %s", code, exc)
            return {
                "symbol": code,
                "code": code,
                "asks": [],
                "bids": [],
                "volume_unit": "手",
                "data_status": "empty",
                "error": f"{type(exc).__name__}: {exc}",
                "source_label": "实时盘口不可用",
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "price_basis": "unadjusted",
                "price_usage": "execution_quote",
            }

    @staticmethod
    def get_stock_fundamentals(symbol: str, cache_only: bool = False) -> Dict[str, Any]:
        try:
            code = MarketService._to_code(symbol)
            if not code:
                return {"code": "", "error": "invalid symbol"}

            # Helper to convert to float safely
            def _to_float(v):
                if v is None:
                    return None
                try:
                    num = pd.to_numeric(v, errors="coerce")
                    return float(num) if pd.notna(num) else None
                except:
                    return None

            try:
                # 使用本地数据库查询
                row = db.get_stock_fundamentals(code) if hasattr(db, 'get_stock_fundamentals') else None
                if row:
                    logger.info(f"Found fundamentals for {code} in local DB")
                    return {
                        "code": code,
                        "name": row.get("name"),
                        "current_price": _to_float(row.get("current_price")),
                        "change_percent": _to_float(row.get("change_percent")),
                        "turnover_rate": _to_float(row.get("turnover_rate") or row.get("turnover")),
                        "volume_ratio": _to_float(row.get("volume_ratio")),
                        "pe_dynamic": _to_float(row.get("pe_dynamic") or row.get("pe")),
                        "pb": _to_float(row.get("pb")),
                        "total_market_cap": _to_float(row.get("total_market_cap") or row.get("market_cap")),
                        "float_market_cap": _to_float(row.get("float_market_cap")),
                        "amplitude": _to_float(row.get("amplitude")),
                        "updated_at": row.get("updated_at"),
                        "source_label": row.get("source_label") or "PostgreSQL fundamentals cache",
                        "data_status": "stale" if MarketService._is_stale_timestamp(row.get("updated_at")) else "fresh",
                        "price_basis": "unadjusted",
                        "price_usage": "valuation_snapshot",
                    }
            except Exception as e:
                logger.warning(f"Error fetching from local DB for {code}: {e}")

            if cache_only or not MarketService._external_fetch_enabled():
                return {
                    "code": code,
                    "error": "not_available_in_postgresql",
                    "source_label": "PostgreSQL fundamentals cache",
                    "data_status": "empty",
                    "price_basis": "unadjusted",
                    "price_usage": "valuation_snapshot",
                    "updated_at": None,
                }

            # Priority 1: Try East Money interface
            df_list = None
            try:
                # Use the cached version to avoid fetching 5000+ stocks every time
                stocks = MarketService.get_all_stocks()
                if stocks:
                    df = pd.DataFrame(stocks)
                    # Mapping our internal keys back to COLUMN_MAPPINGS for _num to work
                    # or just use the stocks list directly.
                    # Let's just use the stocks list directly, it's easier.
                    hit_stock = next((s for s in stocks if s['code'] == code), None)
                    if not hit_stock and len(code) < 6:
                        padded = code.zfill(6)
                        hit_stock = next((s for s in stocks if s['code'] == padded), None)
                    
                    if hit_stock:
                        logger.info(f"Found fundamentals for {code} in cached stocks")
                        return {
                            "code": code,
                            "name": hit_stock.get("name"),
                            "current_price": _to_float(hit_stock.get("price")),
                            "change_percent": _to_float(hit_stock.get("change_percent")),
                            "turnover_rate": _to_float(hit_stock.get("turnover")),
                            "volume_ratio": _to_float(hit_stock.get("volume_ratio")),
                            "pe_dynamic": _to_float(hit_stock.get("pe_dynamic")),
                            "pb": _to_float(hit_stock.get("pb")),
                            "total_market_cap": _to_float(hit_stock.get("total_market_cap")),
                            "float_market_cap": _to_float(hit_stock.get("float_market_cap")),
                            "amplitude": _to_float(hit_stock.get("amplitude")),
                        }
                
                # If not in cache or cache empty, fall back to direct API (though get_all_stocks should have handled it)
                df = ak.stock_zh_a_spot_em()
                logger.info(f"Successfully fetched fundamentals for {code} from EastMoney direct")
            except Exception as em_error:
                logger.warning(f"EastMoney interface failed for {code}: {em_error}")
                # Priority 2: Fallback to alternative interface
                try:
                    df = ak.stock_zh_a_spot()
                    logger.info(f"Successfully fetched fundamentals for {code} from alternative interface")
                except Exception as alt_error:
                    logger.error(f"Alternative interface also failed for {code}: {alt_error}")
                    return {"code": code, "error": "no data"}

            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                return {"code": code, "error": "no data"}

            code_col = _find_column(df, COLUMN_MAPPINGS["code"])
            if not code_col:
                return {"code": code, "error": "no code column"}

            # Make sure we compare strings correctly
            df[code_col] = df[code_col].astype(str).str.strip()
            hit = df[df[code_col] == code]
            
            if hit.empty:
                # Try padding if code is short
                if len(code) < 6:
                    padded_code = code.zfill(6)
                    hit = df[df[code_col] == padded_code]
                
            if hit.empty:
                return {"code": code, "error": "not found"}
                
            row_data = hit.iloc[0].to_dict()

            def _num(key_or_candidates):
                if isinstance(key_or_candidates, list):
                    key = _find_column(df, key_or_candidates)
                else:
                    key = _find_column(df, [key_or_candidates])
                
                if not key:
                    return None
                    
                val = row_data.get(key)
                return _to_float(val)

            result = {
                "code": code,
                "name": str(row_data.get(_find_column(df, COLUMN_MAPPINGS["name"])) or "").strip() or None,
                "current_price": _num(COLUMN_MAPPINGS["price"]),
                "change_percent": _num(COLUMN_MAPPINGS["change_percent"]),
                "turnover_rate": _num(COLUMN_MAPPINGS["turnover"]),
                "volume_ratio": _num("量比"),
                "pe_dynamic": _num(["市盈率-动态", "pe", "dynamic_pe", "市盈率"]),
                "pb": _num(["市净率", "pb"]),
                "total_market_cap": _num(["总市值", "total_market_cap"]),
                "float_market_cap": _num(["流通市值", "float_market_cap"]),
                "amplitude": _num(["振幅", "amplitude"]),
            }
            
            # Update cache/DB if we got valid data
            try:
                # We can save this to DB here if needed
                pass
            except:
                pass
                
            return result
        except Exception as e:
            logger.error(f"Error fetching fundamentals for {symbol}: {e}")
            code = MarketService._to_code(symbol)
            return {"code": code, "error": str(e)}
    @staticmethod
    @time_limited_cache(expiration_seconds=60)
    def _get_cached_hot_concepts():
        """Internal method to cache hot concepts data"""
        try:
            limit = 50  # Default limit

            try:
                flow_df = ak.stock_fund_flow_concept(symbol="即时")
                if flow_df is not None and isinstance(flow_df, pd.DataFrame) and not flow_df.empty:
                    flow_df = flow_df.copy()
                    flow_df["行业-涨跌幅"] = pd.to_numeric(flow_df.get("行业-涨跌幅"), errors="coerce").fillna(0.0)
                    flow_df = flow_df.sort_values(by="行业-涨跌幅", ascending=False).head(limit)
                    results: List[Dict[str, Any]] = []
                    rank = 1
                    for _, row in flow_df.iterrows():
                        name = str(row.get("行业") or "").strip()
                        if not name:
                            continue
                        results.append({
                            "rank": rank,
                            "name": name,
                            "change_percent": MarketService._safe_float(row.get("行业-涨跌幅")),
                            "inflow": MarketService._safe_float(row.get("流入资金")),
                            "outflow": MarketService._safe_float(row.get("流出资金")),
                            "net_inflow": MarketService._safe_float(row.get("净额")),
                        })
                        rank += 1
                    return results
            except Exception:
                pass

            concepts_df = ak.stock_board_concept_name_em()
            if concepts_df is None or concepts_df.empty:
                return []

            name_col = '板块名称' if '板块名称' in concepts_df.columns else ('概念名称' if '概念名称' in concepts_df.columns else None)
            if name_col is None:
                return []

            pct_col = '涨跌幅' if '涨跌幅' in concepts_df.columns else ('涨跌幅%' if '涨跌幅%' in concepts_df.columns else None)
            if pct_col is None:
                concepts_df['__change_percent'] = pd.to_numeric(concepts_df.iloc[:, 0], errors='coerce')
                pct_col = '__change_percent'

            concepts_df[pct_col] = pd.to_numeric(concepts_df[pct_col], errors='coerce').fillna(0.0)
            concepts_df = concepts_df.sort_values(by=pct_col, ascending=False).head(limit)

            results: List[Dict[str, Any]] = []
            rank = 1
            for _, row in concepts_df.iterrows():
                name = str(row.get(name_col) or '').strip()
                if not name:
                    continue
                change_percent = float(pd.to_numeric(row.get(pct_col), errors='coerce') or 0.0)
                results.append({
                    "rank": rank,
                    "name": name,
                    "change_percent": change_percent,
                    "inflow": 0.0,
                    "outflow": 0.0,
                    "net_inflow": 0.0,
                })
                rank += 1

            return results
        except Exception as e:
            logger.error(f"Error fetching hot concepts: {e}")
            return []

    @staticmethod
    def get_hot_concepts(limit: int = 50, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get hot concepts from PG cache/history for page-safe rendering."""
        start_time = time.time()
        logger.info(f"Fetching hot concepts (date={date})...")
        limit = max(1, min(int(limit), 200))

        if date:
            db_date = date.replace('-', '')
            try:
                hist = db.get_hot_concepts_history(db_date)
                if hist:
                    logger.info(f"Found {len(hist)} historical hot concepts in DB for {db_date}")
                    return hist[:limit]
            except Exception as e:
                logger.warning(f"Failed to fetch hot concepts history from DB: {e}")
            logger.info(f"No cached hot concepts history for {db_date}")
            return []

        try:
            results = db.get_hot_concepts_realtime(limit)
            if results:
                return results[:limit]
        except Exception as e:
            logger.warning(f"Failed to fetch realtime hot concepts from DB: {e}")

        today = datetime.now().strftime('%Y%m%d')
        try:
            hist = db.get_hot_concepts_history(today)
            if hist:
                return hist[:limit]
        except Exception as e:
            logger.warning(f"Failed to fetch today's hot concepts history from DB: {e}")

        elapsed_time = time.time() - start_time
        logger.info(f"No cached hot concepts available; returned empty list in {elapsed_time:.2f} seconds")
        return []

    @staticmethod
    def _amount_to_yi(value: Any) -> Optional[float]:
        """Normalize mixed 元 / 亿 caches into 亿元."""
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(amount):
            return None
        if abs(amount) >= 10_000_000:  # treat as yuan
            return amount / 100_000_000.0
        return amount

    @staticmethod
    def get_sector_fund_flow(limit: int = 30) -> Dict[str, Any]:
        """
        Build homepage sector inflow/outflow board from PG hot-concept cache.

        TuShare equivalents (for sync enrichment, not page-side live calls):
        - moneyflow_ind_dc  东财板块资金流向
        - moneyflow_ind_ths 同花顺行业资金流向
        - moneyflow_cnt_ths 同花顺概念资金流向
        Pairwise sector-migration matrices are not published by these endpoints;
        Sankey links on the homepage are proportional visualization aids.
        """
        limit = max(1, min(int(limit), 50))
        # Pull a wide slice so inflow/outflow boards are ranked by money, not by 涨跌幅 rank.
        try:
            rows = db.get_hot_concepts_realtime(500) or []
        except Exception:
            rows = MarketService.get_hot_concepts(limit=max(limit * 4, 80))
        if not rows:
            rows = MarketService.get_hot_concepts(limit=max(limit * 4, 80))
        prepared: List[Dict[str, Any]] = []
        updated_at = None
        for row in rows:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            net_yi = MarketService._amount_to_yi(row.get("net_inflow"))
            inflow_yi = MarketService._amount_to_yi(row.get("inflow"))
            outflow_yi = MarketService._amount_to_yi(row.get("outflow"))
            if net_yi is None:
                if inflow_yi is not None or outflow_yi is not None:
                    net_yi = (inflow_yi or 0.0) - (outflow_yi or 0.0)
                else:
                    continue
            stamp = row.get("updated_at")
            if stamp and (updated_at is None or str(stamp) > str(updated_at)):
                updated_at = stamp
            prepared.append(
                {
                    "rank": row.get("rank"),
                    "name": name,
                    "change_percent": row.get("change_percent"),
                    "net_inflow_yi": round(float(net_yi), 2),
                    "inflow_yi": round(float(inflow_yi), 2) if inflow_yi is not None else None,
                    "outflow_yi": round(float(outflow_yi), 2) if outflow_yi is not None else None,
                    "updated_at": stamp,
                    "source_label": row.get("source_label") or "PostgreSQL hot_concepts_realtime",
                }
            )

        inflows = sorted(
            [item for item in prepared if item["net_inflow_yi"] > 0],
            key=lambda item: item["net_inflow_yi"],
            reverse=True,
        )[:limit]
        outflows = sorted(
            [item for item in prepared if item["net_inflow_yi"] < 0],
            key=lambda item: item["net_inflow_yi"],
        )[:limit]

        if updated_at is None:
            data_status = "empty"
        elif MarketService._is_stale_timestamp(updated_at, max_age_hours=36):
            data_status = "stale"
        else:
            data_status = "fresh"

        return {
            "limit": limit,
            "unit": "亿",
            "inflows": inflows,
            "outflows": outflows,
            "rankings": prepared[:limit],
            "updated_at": updated_at,
            "data_status": data_status,
            "source_label": (
                prepared[0]["source_label"]
                if prepared
                else "PostgreSQL hot_concepts_realtime / TuShare moneyflow_ind_dc 可作同步上游"
            ),
            "methodology": (
                "按板块主力净流入排序；连线按流入侧权重分摊，"
                "不是 TuShare/东财公布的板块间迁移矩阵。"
            ),
        }

    @staticmethod
    def _limit_board_quote_from_raw(raw: Any) -> Dict[str, Optional[float]]:
        payload = raw if isinstance(raw, dict) else {}
        price = None
        change_percent = None
        for key in ("最新价", "close", "price", "Close"):
            if key in payload and payload.get(key) is not None:
                try:
                    price = float(payload.get(key))
                    break
                except (TypeError, ValueError):
                    continue
        for key in ("涨跌幅", "pct_chg", "change_percent", "change"):
            if key in payload and payload.get(key) is not None:
                try:
                    change_percent = float(payload.get(key))
                    break
                except (TypeError, ValueError):
                    continue
        # TuShare limit_list_d stores first/last times as HHMMSS integers.
        return {"price": price, "change_percent": change_percent}

    @staticmethod
    def _limit_board_item_from_member(row: Dict[str, Any], pool_kind: str) -> Dict[str, Any]:
        quote = MarketService._limit_board_quote_from_raw(row.get("raw_payload"))
        symbol = str(row.get("symbol") or "").strip()
        code = "".join(ch for ch in symbol if ch.isdigit())[-6:] or symbol
        return {
            "symbol": symbol,
            "code": code,
            "name": str(row.get("name") or "").strip() or None,
            "pool_kind": pool_kind,
            "price": quote.get("price"),
            "change_percent": quote.get("change_percent"),
            "limit_times": row.get("limit_times"),
            "first_limit_at": row.get("first_limit_at"),
            "last_limit_at": row.get("last_limit_at"),
            "open_times": row.get("open_times"),
            "seal_amount": row.get("seal_amount"),
            "turnover": row.get("turnover"),
            "industry": row.get("industry"),
            "source_label": row.get("source_label"),
        }

    @staticmethod
    def _limit_board_from_realtime_estimate() -> Dict[str, List[Dict[str, Any]]]:
        """Diagnostic-only board estimates from cache rows with complete rule evidence."""
        try:
            rows = db.get_all_stocks_realtime() or []
        except Exception as exc:
            logger.warning("limit-board realtime estimate failed: %s", exc)
            return {"up": [], "down": []}

        up: List[Dict[str, Any]] = []
        down: List[Dict[str, Any]] = []
        for row in rows:
            try:
                change = float(row.get("change_percent"))
            except (TypeError, ValueError):
                continue
            code = str(row.get("code") or "").strip()
            digits = "".join(ch for ch in code if ch.isdigit())[-6:]
            if not digits:
                continue
            rule = MarketService._price_limit_rule(
                digits,
                row.get("name"),
                listing_trade_days=row.get("listing_trade_days"),
                is_st=row.get("is_st"),
            )
            if rule.get("has_price_limit") is not True:
                continue
            if digits.startswith("6"):
                symbol = f"{digits}.SH"
            elif digits.startswith(("8", "4")) or digits.startswith("92"):
                symbol = f"{digits}.BJ"
            else:
                symbol = f"{digits}.SZ"
            item = {
                "symbol": symbol,
                "code": digits,
                "name": row.get("name"),
                "price": row.get("price"),
                "change_percent": change,
                "limit_times": None,
                "industry": row.get("industry"),
                "rule_id": rule.get("rule_id"),
                "threshold_pct": rule.get("threshold_pct"),
                "source_label": "PostgreSQL all_stocks_realtime (板块/上市阶段规则估计，非交易所封板名单)",
            }
            threshold = float(rule.get("threshold_pct") or 0.0) - 0.2
            if change >= threshold:
                up.append({**item, "pool_kind": "up"})
            elif change <= -threshold:
                down.append({**item, "pool_kind": "down"})
        up.sort(key=lambda item: (item.get("change_percent") is None, -(item.get("change_percent") or 0)))
        down.sort(key=lambda item: (item.get("change_percent") is None, item.get("change_percent") or 0))
        return {"up": up, "down": down}

    @staticmethod
    def get_limit_board(trade_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Homepage limit-up / limit-down member board for chart drill-down.

        Only sealed market-evidence members qualify for the formal board. A
        sealed zero-member pool is authoritative and must not be replaced by a
        percentage-threshold estimate.
        """
        research = MarketResearchService(db)
        snapshot = research._latest_snapshot(trade_date, "all_a")
        up: List[Dict[str, Any]] = []
        down: List[Dict[str, Any]] = []
        source_label = "封存涨跌停名单未生成"
        data_status = "empty"
        captured_at = None
        snapshot_id = None
        resolved_trade_date = trade_date

        if snapshot and snapshot.get("id") is not None:
            snapshot_id = int(snapshot["id"])
            resolved_trade_date = str(snapshot.get("trade_date") or "")[:10] or resolved_trade_date
            captured_at = snapshot.get("captured_at")
            ecology = research.limit_ecosystem(snapshot_id)
            pools = ecology.get("pools") or {}
            up = [
                MarketService._limit_board_item_from_member(item, "up")
                for item in (pools.get("up") or [])
            ]
            down = [
                MarketService._limit_board_item_from_member(item, "down")
                for item in (pools.get("down") or [])
            ]
            formal_source = ecology.get("source_label")
            formal_available = bool(formal_source or up or down)
            if not formal_available:
                sentiment = research.sentiment(snapshot_id)
                metrics = sentiment.get("metrics") if isinstance(sentiment, dict) else []
                formal_metrics = [
                    item
                    for item in (metrics or [])
                    if item.get("metric_code") in {"limit_up_count", "limit_down_count"}
                    and item.get("value") is not None
                ]
                formal_available = bool(formal_metrics)
                formal_source = next(
                    (item.get("source_label") for item in formal_metrics if item.get("source_label")),
                    None,
                )
            if formal_available:
                source_label = formal_source or "封存涨跌停名单"
                data_status = "stale" if research._is_stale(captured_at) else "fresh"

        return {
            "trade_date": resolved_trade_date,
            "snapshot_id": snapshot_id,
            "captured_at": captured_at.isoformat() if hasattr(captured_at, "isoformat") else captured_at,
            "data_status": data_status,
            "source_label": source_label,
            "counts": {"up": len(up), "down": len(down)},
            "up": up,
            "down": down,
            "methodology": (
                "仅展示封存市场证据 limit_pool_members（TuShare limit_list_d / AkShare 涨跌停池）；"
                "封存 0 家是有效结果；未封存时保持不可用，不用涨跌幅阈值估计冒充正式名单。"
            ),
        }

    @staticmethod
    def get_ths_hot(limit: int = 100, date: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            limit = max(1, min(int(limit), 200))

            if date:
                db_date = date.replace('-', '')
                try:
                    hist = db.get_ths_hot_history(db_date)
                    if hist:
                        logger.info(f"Found {len(hist)} historical THS hot in DB for {db_date}")
                        return hist[:limit]
                except Exception as e:
                    logger.warning(f"Failed to fetch THS hot history from DB: {e}")
                logger.info(f"No cached THS hot history for {db_date}")
                return []

            try:
                results = db.get_ths_hot_realtime(limit)
                if results:
                    return results[:limit]
            except Exception as e:
                logger.warning(f"Failed to fetch realtime THS hot from DB: {e}")

            today = datetime.now().strftime('%Y%m%d')
            try:
                hist = db.get_ths_hot_history(today)
                if hist:
                    return hist[:limit]
            except Exception as e:
                logger.warning(f"Failed to fetch today's THS hot history from DB: {e}")

            logger.info("No cached THS hot available; returning empty list")
            return []
        except Exception as e:
            logger.error(f"Error fetching THS hot rank: {e}")
            return []

    @staticmethod
    def _latest_trade_dates() -> List[str]:
        try:
            df = ak.tool_trade_date_hist_sina()
            if df is None or df.empty:
                return []
            col = 'trade_date' if 'trade_date' in df.columns else df.columns[0]
            dates = pd.to_datetime(df[col], errors='coerce').dropna().dt.strftime('%Y%m%d').tolist()
            # Always ascending so callers can take [-1] as the latest session.
            return sorted(set(dates))
        except Exception:
            return []

    @staticmethod
    def get_lianban_ladder(date: Optional[str] = None) -> Dict[str, Any]:
        try:
            dates = MarketService._latest_trade_dates()
            if not dates:
                # Fallback: sealed limit_pool snap dates when calendar fetch fails.
                try:
                    sealed = db.get_latest_sealed_limit_pool_snapshot() or {}
                    snap_date = str(sealed.get("trade_date") or "").replace("-", "")[:8]
                    if len(snap_date) == 8 and snap_date.isdigit():
                        dates = [snap_date]
                except Exception:
                    pass
            if not dates:
                return {"date": None, "prev_date": None, "levels": []}

            today_str = datetime.now().strftime('%Y%m%d')
            available = [d for d in dates if d <= today_str]
            if not available:
                available = dates

            if date:
                date = str(date).strip().replace('-', '')
                if date in available:
                    target_date = date
                else:
                    target_date = available[-1]
            else:
                target_date = available[-1]

            idx = available.index(target_date)
            prev_date = available[idx - 1] if idx > 0 else None

            # Check DB cache first for historical dates
            if date and target_date < today_str:
                try:
                    cached = db.get_lianban_ladder_history(target_date)
                    if cached and cached.get('levels'):
                        logger.info(f"Returning cached lianban ladder for {target_date}")
                        return cached
                except Exception as cache_err:
                    logger.warning(f"Failed to get lianban ladder from cache: {cache_err}")

            today_df = ak.stock_zt_pool_em(date=target_date)
            prev_df = None
            try:
                prev_df = ak.stock_zt_pool_previous_em(date=target_date)
            except Exception:
                prev_df = None

            def group(df: Optional[pd.DataFrame]) -> Dict[int, List[Dict[str, Any]]]:
                if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                    return {}
                lianban_col = '连板数' if '连板数' in df.columns else None
                if lianban_col is None:
                    return {}
                code_col = '代码' if '代码' in df.columns else None
                name_col = '名称' if '名称' in df.columns else None
                pct_col = '涨跌幅' if '涨跌幅' in df.columns else None
                price_col = '最新价' if '最新价' in df.columns else None

                grouped: Dict[int, List[Dict[str, Any]]] = {}
                for _, r in df.iterrows():
                    lv = int(pd.to_numeric(r.get(lianban_col), errors='coerce') or 0)
                    if lv <= 0:
                        continue
                    # 获取可能存在的额外列
                    reason_col = '涨停原因' if '涨停原因' in df.columns else None
                    duration_col = '连板天数' if '连板天数' in df.columns else None
                    success_rate_col = '涨停成功率' if '涨停成功率' in df.columns else None
                                    
                    item = {
                        "code": str(r.get(code_col) or '').strip() if code_col else '',
                        "name": str(r.get(name_col) or '').strip() if name_col else '',
                        "change_percent": float(pd.to_numeric(r.get(pct_col), errors='coerce')) if pct_col else 0.0,
                        "price": float(pd.to_numeric(r.get(price_col), errors='coerce')) if price_col else 0.0,
                    }
                                    
                    # 添加可选字段
                    if reason_col:
                        item["reason"] = str(r.get(reason_col) or '')
                    if duration_col:
                        duration_val = pd.to_numeric(r.get(duration_col), errors='coerce')
                        if not pd.isna(duration_val):
                            item["duration_days"] = int(duration_val)
                    if success_rate_col:
                        success_rate_val = pd.to_numeric(r.get(success_rate_col), errors='coerce')
                        if not pd.isna(success_rate_val):
                            item["success_rate"] = float(success_rate_val)
                                    
                    if pd.isna(item["change_percent"]):
                        item["change_percent"] = 0.0
                    if pd.isna(item["price"]):
                        item["price"] = 0.0
                    grouped.setdefault(lv, []).append(item)
                return grouped

            today_groups = group(today_df)
            prev_groups = group(prev_df)

            max_today = max(today_groups.keys()) if today_groups else 1
            max_prev = max(prev_groups.keys()) if prev_groups else 1
            max_level = max(max_today, max_prev + 1)

            levels: List[Dict[str, Any]] = []
            for lv in range(2, max_level + 1):
                prev_lv = lv - 1
                prev_items = prev_groups.get(prev_lv, [])
                today_items = today_groups.get(lv, [])
                levels.append({
                    "prev_level": prev_lv,
                    "prev_count": len(prev_items),
                    "prev_items": prev_items,
                    "today_level": lv,
                    "today_count": len(today_items),
                    "today_items": today_items,
                })

            result = {
                "date": target_date,
                "prev_date": prev_date,
                "levels": levels,
            }
            
            # Save to database cache
            try:
                db.insert_lianban_ladder_history(target_date, prev_date, levels)
                logger.info(f"Saved lianban ladder to DB for {target_date}")
            except Exception as save_err:
                logger.warning(f"Failed to save lianban ladder to DB: {save_err}")

            return result
        except Exception as e:
            logger.error(f"Error fetching lianban ladder: {e}")
            # Try to get from DB cache if API fails
            if date:
                try:
                    db_date = str(date).replace('-', '')
                    cached = db.get_lianban_ladder_history(db_date)
                    if cached:
                        logger.info(f"Returning cached lianban ladder for {db_date}")
                        return cached
                except Exception as cache_err:
                    logger.warning(f"Failed to get lianban ladder from cache: {cache_err}")
            return {"date": None, "prev_date": None, "levels": []}

    @staticmethod
    def get_concept_intraday_kline(name: str, period: str = "1", date: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            nm = str(name or "").strip()
            if not nm:
                return []
            period = str(period or "1").strip()
            if period not in {"1", "5", "15", "30", "60"}:
                period = "1"

            # 1. Fetch from API
            df = ak.stock_board_concept_hist_min_em(symbol=nm, period=period)
            api_data = []
            if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                time_col = _find_column(df, COLUMN_MAPPINGS["time"])
                open_col = _find_column(df, COLUMN_MAPPINGS["open"])
                close_col = _find_column(df, COLUMN_MAPPINGS["close"])
                high_col = _find_column(df, COLUMN_MAPPINGS["high"])
                low_col = _find_column(df, COLUMN_MAPPINGS["low"])
                vol_col = _find_column(df, COLUMN_MAPPINGS["volume"])
                amt_col = _find_column(df, COLUMN_MAPPINGS["amount"])

                for _, row in df.iterrows():
                    t = str(row.get(time_col) or "").strip() if time_col else ""
                    if not t:
                        continue
                    api_data.append(
                        {
                            "name": nm,
                            "period": period,
                            "time": t,
                            "open": MarketService._safe_float(row.get(open_col)) if open_col else 0.0,
                            "close": MarketService._safe_float(row.get(close_col)) if close_col else 0.0,
                            "high": MarketService._safe_float(row.get(high_col)) if high_col else 0.0,
                            "low": MarketService._safe_float(row.get(low_col)) if low_col else 0.0,
                            "volume": MarketService._safe_float(row.get(vol_col)) if vol_col else 0.0,
                            "amount": MarketService._safe_float(row.get(amt_col)) if amt_col else 0.0,
                        }
                    )

            # 2. Async upsert to DB
            if api_data:
                MarketService._upsert_concept_kline_async(api_data)

            # 3. If API failed, try DB entirely
            if not api_data:
                try:
                    # 本地数据库实现
                    res = []
                    # 这里可以根据实际需求实现本地数据库查询
                    # 例如: res = db.get_concept_kline_data(nm, period, 500)
                    rows = res.data or []
                    # Sort by time asc
                    rows.sort(key=lambda x: x.get("time"))
                    return [
                        {
                            "time": r.get("time"),
                            "open": r.get("open"),
                            "close": r.get("close"),
                            "high": r.get("high"),
                            "low": r.get("low"),
                            "volume": r.get("volume"),
                            "amount": r.get("amount"),
                        }
                        for r in rows
                    ]
                except Exception:
                    return []

            # 4. If API succeeded, we can merge or just return API (for freshness)
            # The requirement is "History from DB, Today from API".
            # Let's define "Today"
            now = datetime.now()
            today_str = now.strftime('%Y-%m-%d')
            
            # Get earliest time in API data
            min_api_time = min(d["time"] for d in api_data) if api_data else today_str
            
            # Fetch history from DB where time < min_api_time
            try:
                # 本地数据库实现
                res = []
                # 这里可以根据实际需求实现本地数据库查询
                # 例如: res = db.get_concept_kline_history(nm, period, min_api_time, 1000)
                res = type('obj', (object,), {'data': []})()
                db_rows = res.data or []
            except Exception:
                db_rows = []
            
            # Combine DB (history) + API (recent/today)
            # Convert DB rows to match format
            history_data = [
                {
                    "time": r.get("time"),
                    "open": r.get("open"),
                    "close": r.get("close"),
                    "high": r.get("high"),
                    "low": r.get("low"),
                    "volume": r.get("volume"),
                    "amount": r.get("amount"),
                }
                for r in db_rows
            ]
            
            # API data is already formatted but has extra keys (name, period)
            recent_data = [
                {
                    "time": d["time"],
                    "open": d["open"],
                    "close": d["close"],
                    "high": d["high"],
                    "low": d["low"],
                    "volume": d["volume"],
                    "amount": d["amount"],
                }
                for d in api_data
            ]
            
            # Sort combined data
            combined = history_data + recent_data
            combined.sort(key=lambda x: x["time"])
            
            # Deduplicate by time
            unique_data = []
            seen_times = set()
            for item in combined:
                if item["time"] not in seen_times:
                    unique_data.append(item)
                    seen_times.add(item["time"])
            
            return unique_data

        except Exception as e:
            logger.error(f"Error fetching concept intraday kline: {e}")
            return []

    @staticmethod
    def get_concept_leading_stocks(name: str, limit: int = 20, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取概念板块龙头股 - 优先从数据库读取缓存"""
        try:
            nm = str(name or "").strip()
            if not nm:
                return []

            limit = max(1, min(int(limit), 200))

            # 优先从数据库缓存读取
            try:
                cached_leaders = db.get_concept_leaders_cache(nm, limit)
                if cached_leaders and len(cached_leaders) > 0:
                    # 检查缓存是否过期（5分钟）
                    updated_at = db.get_concept_leaders_cache_updated_at(nm)
                    if updated_at:
                        from datetime import timedelta
                        try:
                            cache_time = datetime.strptime(updated_at, "%Y-%m-%d %H:%M:%S")
                            if datetime.now() - cache_time < timedelta(minutes=5):
                                logger.info(f"返回缓存的龙头股数据: {nm}, 共 {len(cached_leaders)} 条")
                                return cached_leaders
                            else:
                                logger.info(f"龙头股缓存已过期: {nm}")
                        except Exception as parse_err:
                            logger.warning(f"解析缓存时间失败: {parse_err}")
                    else:
                        # 有数据但没有时间戳，也返回
                        logger.info(f"返回缓存的龙头股数据(无时间戳): {nm}, 共 {len(cached_leaders)} 条")
                        return cached_leaders
            except Exception as cache_error:
                logger.warning(f"读取龙头股缓存失败 {nm}: {cache_error}")

            # 缓存没有或已过期，从API获取
            logger.info(f"从API获取龙头股: {nm}")
            results = MarketService._fetch_concept_leaders_from_api(nm, limit)
            
            # 存入缓存
            if results:
                try:
                    db.update_concept_leaders_cache(nm, results)
                    logger.info(f"已缓存龙头股数据: {nm}, 共 {len(results)} 条")
                except Exception as cache_error:
                    logger.warning(f"缓存龙头股数据失败 {nm}: {cache_error}")

            return results
        except Exception as e:
            logger.error(f"获取龙头股失败: {e}")
            return []

    @staticmethod
    def _fetch_concept_leaders_from_api(name: str, limit: int = 20) -> List[Dict[str, Any]]:
        """从API获取概念板块龙头股（带重试）"""
        import time
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                df = ak.stock_board_concept_cons_em(symbol=name)
                if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                    return []

                code_col = _find_column(df, COLUMN_MAPPINGS["code"])
                name_col = _find_column(df, COLUMN_MAPPINGS["name"])
                price_col = _find_column(df, COLUMN_MAPPINGS["price"])
                pct_col = _find_column(df, COLUMN_MAPPINGS["change_percent"])
                amount_col = _find_column(df, COLUMN_MAPPINGS["amount"])
                turnover_col = _find_column(df, COLUMN_MAPPINGS["turnover"])

                if pct_col:
                    df = df.copy()
                    df[pct_col] = pd.to_numeric(df[pct_col], errors="coerce").fillna(0.0)
                    df = df.sort_values(by=pct_col, ascending=False)
                df = df.head(limit)

                results: List[Dict[str, Any]] = []
                for _, row in df.iterrows():
                    code = str(row.get(code_col) or "").strip() if code_col else ""
                    nm2 = str(row.get(name_col) or "").strip() if name_col else ""
                    if not code:
                        continue
                    results.append(
                        {
                            "code": code,
                            "name": nm2,
                            "price": MarketService._safe_float(row.get(price_col)) if price_col else 0.0,
                            "change_percent": MarketService._safe_float(row.get(pct_col)) if pct_col else 0.0,
                            "amount": MarketService._safe_float(row.get(amount_col)) if amount_col else 0.0,
                            "turnover": MarketService._safe_float(row.get(turnover_col)) if turnover_col else 0.0,
                        }
                    )
                return results
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"从API获取龙头股失败 {name} (尝试 {attempt + 1}/{max_retries}): {e}, 重试中...")
                    time.sleep(0.5 * (attempt + 1))
                else:
                    logger.error(f"从API获取龙头股失败 {name}: {e}")
        return []

    @staticmethod
    def _exchange_from_code(code: str) -> str:
        c = str(code or "").strip()
        if c.startswith("688"):
            return "STAR"
        if c.startswith("300"):
            return "CHINEXT"
        if c.startswith("6"):
            return "SH"
        if c.startswith("0") or c.startswith("3"):
            return "SZ"
        if c.startswith(("4", "8", "92")):
            return "BJ"
        return "UNKNOWN"

    @staticmethod
    def _abnormal_rules() -> List[Dict[str, Any]]:
        return [
            {"id": "sh_sz_main_10", "exchange": "SH/SZ", "threshold_pct": 10.0, "name": "沪深主板（含风险警示）涨跌停板"},
            {"id": "star_chinext_20", "exchange": "STAR/CHINEXT", "threshold_pct": 20.0, "name": "科创/创业涨跌停板"},
            {"id": "bj_30", "exchange": "BJ", "threshold_pct": 30.0, "name": "北交所涨跌幅限制"},
        ]

    @staticmethod
    def _threshold_for_stock(
        code: str,
        name: str,
        *,
        listing_trade_days: Any = None,
        is_st: Any = None,
    ) -> Dict[str, Any]:
        return MarketService._price_limit_rule(
            code,
            name,
            listing_trade_days=listing_trade_days,
            is_st=is_st,
        )

    @staticmethod
    def _upsert_abnormal_events(events: List[Dict[str, Any]]) -> None:
        if not events:
            return
        try:
            chunk_size = 500
            for i in range(0, len(events), chunk_size):
                # 本地数据库实现
                # db.insert_abnormal_events(events[i : i + chunk_size])
                pass
        except Exception as e:
            logger.error(f"Failed to upsert abnormal events: {e}")

    @staticmethod
    def get_message_stream(limit: int = 50) -> Dict[str, Any]:
        """
        获取消息流数据
        
        优先从数据库读取已同步的新闻（快速），如果没有数据则实时获取。
        异动数据在交易时间内实时计算。
        """
        try:
            limit = max(1, min(int(limit), 200))
        except Exception:
            limit = 50

        now = datetime.now()
        trade_date = now.date().isoformat()
        
        # 判断是否是交易时间（简化判断）
        hour = now.hour
        is_trading_time = now.weekday() < 5 and 9 <= hour <= 15

        # Page reads use only the stored market cache. Stale cache cannot create
        # a current intraday anomaly claim.
        try:
            cached_stocks = db.get_all_stocks_realtime()
        except Exception as exc:
            logger.warning("读取全市场缓存失败: %s", exc)
            cached_stocks = []
        stock_updated_at = MarketService._latest_timestamp(cached_stocks)
        stock_state = "unavailable" if not cached_stocks else (
            "stale" if MarketService._is_stale_timestamp(stock_updated_at) else "fresh"
        )
        stocks = cached_stocks if is_trading_time and stock_state == "fresh" else []

        triggered: List[Dict[str, Any]] = []
        near: List[Dict[str, Any]] = []
        for s in stocks:
            code = str(s.get("code") or "").strip()
            name = str(s.get("name") or "").strip()
            if not code:
                continue
            pct = float(pd.to_numeric(s.get("change_percent"), errors="coerce") or 0.0)
            rule = MarketService._threshold_for_stock(
                code,
                name,
                listing_trade_days=s.get("listing_trade_days"),
                is_st=s.get("is_st"),
            )
            if rule.get("has_price_limit") is not True:
                continue
            threshold = float(rule.get("threshold_pct") or 10.0)
            abs_pct = abs(pct)
            item = {
                "code": code,
                "name": name,
                "exchange": rule.get("exchange"),
                "rule_id": rule.get("rule_id"),
                "threshold_pct": threshold,
                "change_percent": pct,
                "direction": "UP" if pct >= 0 else "DOWN",
            }
            if abs_pct >= threshold:
                triggered.append(item)
            elif abs_pct >= max(0.0, threshold - 1.0):
                near.append(item)

        triggered = sorted(triggered, key=lambda x: abs(float(x.get("change_percent") or 0.0)), reverse=True)[:limit]
        near = sorted(near, key=lambda x: abs(float(x.get("change_percent") or 0.0)), reverse=True)[:limit]
        # 新闻数据 - 优先从数据库读取（快速）
        cailian_news = MarketService._get_news_from_db_or_api('ths', limit)
        cls_news = MarketService._get_news_from_db_or_api('cls', limit)
        
        # 合并财联社的两个来源（ths 同花顺快讯 + cls 财联社电报）
        all_cailian = cailian_news + cls_news
        all_cailian.sort(key=lambda x: x.get('time', ''), reverse=True)
        
        # 其他新闻 - 直接返回空列表，后续可以通过定时任务同步
        # 这些接口太慢，严重影响用户体验
        mergers: List[Dict[str, Any]] = []
        good_news: List[Dict[str, Any]] = []
        bad_news: List[Dict[str, Any]] = []
        xueqiu_news: List[Dict[str, Any]] = []
        eastmoney_news: List[Dict[str, Any]] = []
        content_times = [item.get("time") for item in all_cailian if item.get("time")]
        content_updated_at = max(content_times) if content_times else stock_updated_at

        return {
            "updated_at": content_updated_at,
            "source_updated_at": content_updated_at,
            "response_generated_at": now.isoformat(),
            "data_status": {
                "stock_snapshot_state": stock_state,
                "stock_snapshot_updated_at": stock_updated_at,
                "news_state": "available" if all_cailian else "empty",
                "message": (
                    "全市场缓存陈旧，未计算当前异动"
                    if stock_state == "stale"
                    else "全市场缓存不可用，未计算当前异动"
                    if stock_state == "unavailable"
                    else "异动基于新鲜 PostgreSQL 行情缓存"
                ),
            },
            "abnormal": {
                "rules": MarketService._abnormal_rules(),
                "triggered": triggered,
                "near": near,
            },
            "mergers": mergers,
            "good_news": good_news,
            "bad_news": bad_news,
            "cailian_news": all_cailian[:limit],
            "xueqiu_news": xueqiu_news,
            "eastmoney_news": eastmoney_news,
        }
    
    @staticmethod
    def _get_news_from_db_or_api(source: str, limit: int) -> List[Dict[str, Any]]:
        """
        从数据库读取新闻。页面请求保持只读，外部同步由定时/手动接口负责。
        """
        from app.db import db_instance

        try:
            db_news = db_instance.get_news_stream(limit=limit, source=source)
            items = []
            for n in db_news or []:
                items.append({
                    "id": hashlib.sha1(f"{n.get('source')}:{n.get('publish_time')}:{n.get('title', '')[:30]}".encode("utf-8")).hexdigest(),
                    "time": n.get('publish_time', ''),
                    "title": n.get('title') or n.get('content', '')[:100],
                    "source": n.get('source', source),
                    "url": None,
                    "sentiment": None,
                    "related_stocks": [],
                })
            if items:
                logger.info(f"从数据库读取 {len(items)} 条 {source} 新闻")
            return items
        except Exception as e:
            logger.warning(f"从数据库读取 {source} 新闻失败: {e}")
        return []

    @staticmethod
    def _fetch_merger_restruct_messages(limit: int = 50) -> List[Dict[str, Any]]:
        keywords = ["并购", "重组", "重大资产重组", "收购", "吸收合并", "发行股份购买资产", "借壳"]
        try:
            df = ak.stock_notice_report()
        except Exception:
            df = None

        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return []

        try:
            if any(c in df.columns for c in ["公告日期", "时间", "date", "日期"]):
                time_col_raw = None
                for c in ["公告日期", "时间", "date", "日期"]:
                    if c in df.columns:
                        time_col_raw = c
                        break
                if time_col_raw:
                    df = df.copy()
                    df["__ts"] = pd.to_datetime(df[time_col_raw], errors="coerce")
                    df = df.sort_values("__ts", ascending=False)
        except Exception:
            pass

        title_col = None
        for c in ["公告标题", "标题", "title", "公告内容"]:
            if c in df.columns:
                title_col = c
                break
        code_col = None
        for c in ["代码", "股票代码", "symbol", "证券代码"]:
            if c in df.columns:
                code_col = c
                break
        name_col = None
        for c in ["名称", "股票简称", "name", "证券简称"]:
            if c in df.columns:
                name_col = c
                break
        time_col = None
        for c in ["公告日期", "时间", "date", "日期"]:
            if c in df.columns:
                time_col = c
                break

        items: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            title = str(row.get(title_col) or "").strip() if title_col else ""
            if not title:
                continue
            if not any(k in title for k in keywords):
                continue
            code = str(row.get(code_col) or "").strip() if code_col else ""
            name = str(row.get(name_col) or "").strip() if name_col else ""
            t = str(row.get(time_col) or "").strip() if time_col else ""
            items.append(
                {
                    "id": hashlib.sha1(f"{t}:{code}:{title}".encode("utf-8")).hexdigest(),
                    "time": t or None,
                    "title": title,
                    "source": "ak.stock_notice_report",
                    "related_stocks": [{"code": code, "name": name or None}] if code else [],
                }
            )

        if not items:
            return []

        times = [it.get("time") or "" for it in items]
        try:
            ts = pd.to_datetime(times, errors="coerce")
        except Exception:
            ts = pd.Series([pd.NaT] * len(items))

        pairs: List[tuple[datetime, Dict[str, Any]]] = []
        for it, dt_val in zip(items, ts):
            if pd.isna(dt_val):
                continue
            pairs.append((dt_val.to_pydatetime(), it))

        if not pairs:
            return items[:limit]

        now = datetime.now()
        cutoff = now - timedelta(days=30)
        recent = [p for p in pairs if p[0] >= cutoff]
        base = recent if recent else pairs
        base.sort(key=lambda x: x[0], reverse=True)
        return [it for _, it in base[:limit]]

    @staticmethod
    def _classify_national_news(title: str) -> Optional[str]:
        t = str(title or "").strip()
        if not t:
            return None

        good = ["降准", "降息", "稳增长", "刺激", "专项债", "扩内需", "支持资本市场", "纾困", "减税", "降费", "并表", "国资", "央行", "政策利好", "大规模设备更新", "以旧换新"]
        bad = ["加息", "收紧", "制裁", "冲突", "地缘", "战争", "疫情", "爆雷", "违约", "暴跌", "下调", "监管趋严", "风险", "危机"]

        if any(k in t for k in good):
            return "good"
        if any(k in t for k in bad):
            return "bad"
        return None

    @staticmethod
    def _fetch_national_news(limit: int = 50) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        def _normalize(df: pd.DataFrame, source: str) -> List[Dict[str, Any]]:
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                return []

            time_col = None
            for c in ["时间", "time", "日期", "date", "发布时间"]:
                if c in df.columns:
                    time_col = c
                    break
            title_col = None
            for c in ["标题", "title", "新闻标题", "内容", "摘要"]:
                if c in df.columns:
                    title_col = c
                    break
            url_col = None
            for c in ["链接", "url", "网址"]:
                if c in df.columns:
                    url_col = c
                    break

            items: List[Dict[str, Any]] = []
            for _, r in df.iterrows():
                title = str(r.get(title_col) or "").strip() if title_col else ""
                if not title:
                    continue
                sentiment = MarketService._classify_national_news(title)
                if sentiment is None:
                    continue
                t = str(r.get(time_col) or "").strip() if time_col else ""
                url = str(r.get(url_col) or "").strip() if url_col else ""
                items.append(
                    {
                        "id": hashlib.sha1(f"{source}:{t}:{title}".encode("utf-8")).hexdigest(),
                        "time": t or None,
                        "title": title,
                        "source": source,
                        "url": url or None,
                        "sentiment": sentiment,
                        "related_stocks": [],
                    }
                )

            if not items:
                return []

            times = [it.get("time") or "" for it in items]
            try:
                ts = pd.to_datetime(times, errors="coerce")
            except Exception:
                ts = pd.Series([pd.NaT] * len(items))

            pairs: List[tuple[datetime, Dict[str, Any]]] = []
            for it, dt_val in zip(items, ts):
                if pd.isna(dt_val):
                    continue
                pairs.append((dt_val.to_pydatetime(), it))

            if not pairs:
                return items[:limit]

            now = datetime.now()
            cutoff = now - timedelta(days=7)
            recent = [p for p in pairs if p[0] >= cutoff]
            base = recent if recent else pairs
            base.sort(key=lambda x: x[0], reverse=True)
            return [it for _, it in base[:limit]]

        frames: List[tuple[pd.DataFrame, str]] = []
        try:
            frames.append((ak.news_report_time_baidu(), "ak.news_report_time_baidu"))
        except Exception:
            pass
        try:
            frames.append((ak.news_cctv(), "ak.news_cctv"))
        except Exception:
            pass

        merged: List[Dict[str, Any]] = []
        for df, source in frames:
            merged.extend(_normalize(df, source))

        seen: set[str] = set()
        uniq: List[Dict[str, Any]] = []
        for it in merged:
            k = str(it.get("id") or "")
            if not k or k in seen:
                continue
            seen.add(k)
            uniq.append(it)

        good = [x for x in uniq if x.get("sentiment") == "good"][:limit]
        bad = [x for x in uniq if x.get("sentiment") == "bad"][:limit]
        return good, bad

    @staticmethod
    def _fetch_cailian_news(limit: int = 50) -> List[Dict[str, Any]]:
        """获取财联社财经资讯 - 使用多个数据源"""
        try:
            items: List[Dict[str, Any]] = []
            today = datetime.now().date()
            
            # 尝试获取财联社电报 - 最及时的财经快讯
            try:
                df = ak.stock_info_global_cls()
                if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                    for idx, row in df.head(limit).iterrows():
                        try:
                            # 尝试多种列名
                            title = str(row.get('内容', '') or row.get('content', '') or row.get('title', '') or '').strip()
                            if not title or len(title) < 5:
                                continue
                            
                            time_str = str(row.get('发布时间', '') or row.get('时间', '') or row.get('time', '') or '')
                            if not time_str:
                                time_str = datetime.now().strftime('%Y-%m-%d %H:%M')
                            
                            items.append({
                                "id": hashlib.sha1(f"cls_telegraph:{time_str}:{title[:50]}".encode("utf-8")).hexdigest(),
                                "time": time_str,
                                "title": title[:200],  # 限制长度
                                "source": "财联社电报",
                                "url": "",
                                "sentiment": MarketService._classify_national_news(title),
                                "related_stocks": [],
                            })
                        except Exception as e:
                            logger.debug(f"Error parsing cls telegraph row: {e}")
                            continue
            except Exception as e:
                logger.warning(f"Failed to fetch cls telegraph: {e}")
            
            # 尝试获取央视新闻作为补充
            if len(items) < limit // 2:
                try:
                    df = ak.news_cctv()
                    if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                        for idx, row in df.head(limit // 2).iterrows():
                            try:
                                title = str(row.get('title', '') or row.get('标题', '') or '').strip()
                                if not title:
                                    continue
                                
                                time_str = str(row.get('date', '') or row.get('时间', '') or '')
                                if not time_str:
                                    time_str = datetime.now().strftime('%Y-%m-%d')
                                
                                items.append({
                                    "id": hashlib.sha1(f"cctv:{time_str}:{title}".encode("utf-8")).hexdigest(),
                                    "time": time_str,
                                    "title": title,
                                    "source": "央视财经",
                                    "url": str(row.get('url', '') or ''),
                                    "sentiment": MarketService._classify_national_news(title),
                                    "related_stocks": [],
                                })
                            except Exception as e:
                                logger.debug(f"Error parsing cctv row: {e}")
                                continue
                except Exception as e:
                    logger.warning(f"Failed to fetch cctv news: {e}")
            
            # 按时间排序
            items.sort(key=lambda x: x.get('time', ''), reverse=True)
            return items[:limit]
            
        except Exception as e:
            logger.error(f"Error fetching cailian news: {e}")
            return []

    @staticmethod
    def _fetch_xueqiu_news(limit: int = 50) -> List[Dict[str, Any]]:
        """获取雪球热门资讯"""
        try:
            items: List[Dict[str, Any]] = []
            
            # 尝试获取雪球热门讨论
            try:
                df = ak.stock_hot_tweet_xq(symbol="最热门")
                if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                    for _, row in df.head(limit).iterrows():
                        try:
                            code = str(row.get('代码', '') or row.get('code', '')).strip()
                            name = str(row.get('名称', '') or row.get('name', '')).strip()
                            
                            if not name:
                                continue
                            
                            title = f"热门讨论: {name}"
                            if code:
                                title += f" ({code})"
                            
                            items.append({
                                "id": hashlib.sha1(f"xueqiu_hot:{code}:{name}".encode("utf-8")).hexdigest(),
                                "time": datetime.now().strftime('%Y-%m-%d %H:%M'),
                                "title": title,
                                "source": "雪球",
                                "url": f"https://xueqiu.com/S/{code}" if code else "",
                                "sentiment": "",
                                "related_stocks": [{"code": code, "name": name}] if code and name else [],
                            })
                        except Exception as e:
                            logger.debug(f"Failed to parse xueqiu row: {e}")
                            continue
            except Exception as e:
                logger.warning(f"Failed to fetch xueqiu hot tweets: {e}")
            
            # 如果没有数据，尝试使用热榜数据
            if not items:
                try:
                    df = ak.stock_hot_rank_em()
                    if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                        for _, row in df.head(limit).iterrows():
                            try:
                                code = str(row.get('代码', '') or row.get('code', '')).strip()
                                name = str(row.get('股票名称', '') or row.get('name', '')).strip()
                                hot = float(row.get('热度', 0) or 0)
                                
                                if not name:
                                    continue
                                
                                title = f"热度飙升: {name} - 热度{hot:.0f}"
                                
                                items.append({
                                    "id": hashlib.sha1(f"xueqiu_rank:{code}:{name}".encode("utf-8")).hexdigest(),
                                    "time": datetime.now().strftime('%Y-%m-%d %H:%M'),
                                    "title": title,
                                    "source": "雪球热榜",
                                    "url": f"https://xueqiu.com/S/{code}" if code else "",
                                    "sentiment": "",
                                    "related_stocks": [{"code": code, "name": name}] if code and name else [],
                                })
                            except Exception as e:
                                logger.debug(f"Failed to parse xueqiu rank row: {e}")
                                continue
                except Exception as e:
                    logger.warning(f"Failed to fetch xueqiu hot rank: {e}")
            
            return items[:limit]
        except Exception as e:
            logger.error(f"Failed to fetch xueqiu news: {e}")
            return []

    @staticmethod
    def _fetch_eastmoney_news(limit: int = 50) -> List[Dict[str, Any]]:
        """获取东方财富快讯"""
        try:
            items: List[Dict[str, Any]] = []
            
            # 先尝试获取财经快讯
            try:
                df = ak.stock_info_global_em()
                if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                    for _, row in df.head(limit).iterrows():
                        try:
                            title = str(row.get('内容', '') or row.get('content', '') or '').strip()
                            time_str = str(row.get('发布时间', '') or row.get('时间', '') or '')
                            
                            if not title or len(title) < 5:
                                continue
                            
                            if not time_str:
                                time_str = datetime.now().strftime('%Y-%m-%d %H:%M')
                            
                            items.append({
                                "id": hashlib.sha1(f"em_global:{time_str}:{title[:50]}".encode("utf-8")).hexdigest(),
                                "time": time_str,
                                "title": title[:200],
                                "source": "东方财富全球",
                                "url": "",
                                "sentiment": MarketService._classify_national_news(title),
                                "related_stocks": [],
                            })
                        except Exception as e:
                            logger.debug(f"Failed to parse em global row: {e}")
                            continue
            except Exception as e:
                logger.warning(f"Failed to fetch em global news: {e}")
            
            # 补充热门股票新闻
            if len(items) < limit // 2:
                try:
                    hot_stocks = ak.stock_hot_rank_em()
                    if hot_stocks is not None and isinstance(hot_stocks, pd.DataFrame) and not hot_stocks.empty:
                        for _, stock_row in hot_stocks.head(3).iterrows():
                            try:
                                code = str(stock_row.get('代码', '') or stock_row.get('code', '')).strip()
                                name = str(stock_row.get('股票名称', '') or stock_row.get('name', '')).strip()
                                
                                if not code:
                                    continue
                                
                                news_df = ak.stock_news_em(symbol=code)
                                if news_df is not None and isinstance(news_df, pd.DataFrame) and not news_df.empty:
                                    for _, news_row in news_df.head(3).iterrows():
                                        try:
                                            title = str(news_row.get('新闻标题', '') or news_row.get('title', '')).strip()
                                            time_str = str(news_row.get('发布时间', '') or news_row.get('time', '')).strip()
                                            url = str(news_row.get('新闻链接', '') or news_row.get('url', '')).strip()
                                            
                                            if not title:
                                                continue
                                            
                                            items.append({
                                                "id": hashlib.sha1(f"eastmoney:{code}:{title}".encode("utf-8")).hexdigest(),
                                                "time": time_str or datetime.now().strftime('%Y-%m-%d %H:%M'),
                                                "title": title,
                                                "source": "东方财富",
                                                "url": url or "",
                                                "sentiment": "",
                                                "related_stocks": [{"code": code, "name": name}] if code and name else [],
                                            })
                                            
                                            if len(items) >= limit:
                                                break
                                        except Exception as e:
                                            logger.debug(f"Failed to parse eastmoney news row: {e}")
                                            continue
                                
                                if len(items) >= limit:
                                    break
                            except Exception as e:
                                logger.debug(f"Failed to fetch news for stock {code}: {e}")
                                continue
                except Exception as e:
                    logger.warning(f"Failed to fetch eastmoney stock news: {e}")
            
            return items[:limit]
        except Exception as e:
            logger.error(f"Failed to fetch eastmoney news: {e}")
            return []


    @staticmethod
    def _iso_date(value: Any) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        return text[:10]

    @staticmethod
    def _compact_ymd(value: str) -> str:
        return str(value or "").replace("-", "")[:8]

    @staticmethod
    def _holiday_name(iso_date: str) -> Optional[str]:
        for item in MarketService._get_holidays():
            if item.get("event_date") == iso_date:
                title = str(item.get("title") or "")
                return title.replace("休市", "").strip() or title
        return None

    @staticmethod
    def get_trading_calendar(start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Any]:
        """Month grid payload: session open/closed + delivery + macro tags per day.

        Built live from TuShare ``trade_cal`` / ``fut_basic`` / ``eco_cal`` when
        available, with rule-based options/month-end supplements. Does not invent
        missing provider rows.
        """
        today = datetime.now().date()
        try:
            start_d = datetime.strptime((start or "")[:10], "%Y-%m-%d").date() if start else today.replace(day=1)
        except ValueError:
            start_d = today.replace(day=1)
        try:
            end_d = datetime.strptime((end or "")[:10], "%Y-%m-%d").date() if end else (
                (start_d.replace(day=28) + timedelta(days=4)).replace(day=1) + timedelta(days=32)
            ).replace(day=1) - timedelta(days=1)
        except ValueError:
            end_d = (start_d.replace(day=28) + timedelta(days=4)).replace(day=1) + timedelta(days=32)
            end_d = end_d.replace(day=1) - timedelta(days=1)
        if end_d < start_d:
            start_d, end_d = end_d, start_d

        start_iso = start_d.isoformat()
        end_iso = end_d.isoformat()
        start_c = MarketService._compact_ymd(start_iso)
        end_c = MarketService._compact_ymd(end_iso)
        sources: List[str] = []
        errors: List[str] = []

        open_by_date: Dict[str, bool] = {}
        try:
            pro = ak._pro_api() if hasattr(ak, "_pro_api") else None
            if pro is None:
                raise RuntimeError("tushare_pro_unavailable")
            cal = pro.trade_cal(exchange="SSE", start_date=start_c, end_date=end_c)
            if isinstance(cal, pd.DataFrame) and not cal.empty:
                sources.append("tushare.trade_cal")
                for _, row in cal.iterrows():
                    iso = MarketService._iso_date(row.get("cal_date"))
                    if not iso:
                        continue
                    open_by_date[iso] = str(row.get("is_open")).strip() in {"1", "1.0", "True", "true"}
            else:
                errors.append("trade_cal_empty")
        except Exception as exc:
            errors.append(f"trade_cal:{type(exc).__name__}")
            logger.warning("trading calendar trade_cal failed: %s", exc)

        delivery_index: Dict[str, List[str]] = {}
        delivery_bond: Dict[str, List[str]] = {}
        delivery_commodity: Dict[str, List[str]] = {}
        try:
            pro = ak._pro_api() if hasattr(ak, "_pro_api") else None
            if pro is None:
                raise RuntimeError("tushare_pro_unavailable")
            for exchange in ("CFFEX", "SHFE", "DCE", "CZCE", "INE", "GFEX"):
                try:
                    frame = pro.fut_basic(exchange=exchange)
                except Exception as exc:
                    errors.append(f"fut_basic:{exchange}:{type(exc).__name__}")
                    continue
                if not isinstance(frame, pd.DataFrame) or frame.empty:
                    continue
                sources.append(f"tushare.fut_basic:{exchange}")
                for _, row in frame.iterrows():
                    iso = MarketService._iso_date(row.get("last_ddate") or row.get("delist_date"))
                    if not iso or iso < start_iso or iso > end_iso:
                        continue
                    code = str(row.get("fut_code") or "").strip().upper()
                    name = str(row.get("name") or row.get("symbol") or row.get("ts_code") or "").strip()
                    label = name or code or str(row.get("ts_code") or "")
                    if exchange == "CFFEX" and code in {"IF", "IH", "IC", "IM"}:
                        delivery_index.setdefault(iso, []).append(label)
                    elif exchange == "CFFEX":
                        delivery_bond.setdefault(iso, []).append(label)
                    else:
                        delivery_commodity.setdefault(iso, []).append(label)
        except Exception as exc:
            errors.append(f"fut_basic:{type(exc).__name__}")
            logger.warning("trading calendar fut_basic failed: %s", exc)

        macro_by_date: Dict[str, List[str]] = {}
        try:
            pro = ak._pro_api() if hasattr(ak, "_pro_api") else None
            if pro is None:
                raise RuntimeError("tushare_pro_unavailable")
            eco = pro.eco_cal(start_date=start_c, end_date=end_c)
            if isinstance(eco, pd.DataFrame) and not eco.empty:
                sources.append("tushare.eco_cal")
                for _, row in eco.iterrows():
                    currency = str(row.get("currency") or "").upper()
                    event = str(row.get("event") or "").strip()
                    if currency != "CNY":
                        continue
                    iso = MarketService._iso_date(row.get("date"))
                    if not iso or iso < start_iso or iso > end_iso or not event:
                        continue
                    short = event
                    for token, alias in (
                        ("贷款市场报价利率(LPR)", "LPR"),
                        ("5年期贷款市场报价利率(LPR)", "五年LPR"),
                        ("居民消费价格指数", "CPI"),
                        ("工业生产者出厂价格指数", "PPI"),
                        ("国内生产总值", "GDP"),
                        ("制造业采购经理指数", "PMI"),
                    ):
                        if token in event:
                            short = alias
                            break
                    if len(short) > 12:
                        short = short[:12]
                    macro_by_date.setdefault(iso, []).append(short)
            else:
                errors.append("eco_cal_empty")
        except Exception as exc:
            errors.append(f"eco_cal:{type(exc).__name__}")
            logger.warning("trading calendar eco_cal failed: %s", exc)

        open_dates = sorted(
            datetime.strptime(d, "%Y-%m-%d").date()
            for d, is_open in open_by_date.items()
            if is_open
        )
        options_days = {
            ev["event_date"]
            for ev in MarketService._calculate_options_expiry_dates(open_dates)
            if start_iso <= ev["event_date"] <= end_iso
        }
        month_end_days = {
            ev["event_date"]
            for ev in MarketService._calculate_month_end_dates(open_dates)
            if start_iso <= ev["event_date"] <= end_iso
        }
        quarter_end_days = {
            ev["event_date"]
            for ev in MarketService._calculate_quarter_end_dates(open_dates)
            if start_iso <= ev["event_date"] <= end_iso
        }
        if options_days:
            sources.append("rule.options_expiry")
        if month_end_days or quarter_end_days:
            sources.append("rule.month_quarter_end")

        days: List[Dict[str, Any]] = []
        cursor = start_d
        while cursor <= end_d:
            iso = cursor.isoformat()
            weekday = cursor.weekday()  # 0=Mon
            known_open = open_by_date.get(iso)
            if known_open is True:
                session = "open"
                is_open = True
            elif known_open is False:
                session = "closed"
                is_open = False
            elif weekday >= 5:
                session = "weekend"
                is_open = False
            else:
                session = "unknown"
                is_open = False

            tags: List[Dict[str, Any]] = []
            if session == "open":
                tags.append({"kind": "session", "label": "开盘", "tone": "open", "detail": "上交所交易日"})
            elif session == "weekend":
                tags.append({"kind": "session", "label": "休市", "tone": "closed", "detail": "周末"})
            elif session == "closed":
                holiday = MarketService._holiday_name(iso)
                tags.append(
                    {
                        "kind": "session",
                        "label": "休市",
                        "tone": "closed",
                        "detail": f"{holiday}休市" if holiday else "非交易日",
                    }
                )
                if holiday:
                    tags.append({"kind": "holiday", "label": holiday, "tone": "holiday", "detail": f"{holiday}假期"})
            else:
                tags.append({"kind": "session", "label": "待定", "tone": "muted", "detail": "交易日历未覆盖"})

            if iso in delivery_index:
                names = sorted(set(delivery_index[iso]))
                tags.append(
                    {
                        "kind": "index_futures",
                        "label": "股指交割",
                        "tone": "danger",
                        "detail": "、".join(names[:8]) + (f" 等{len(names)}个" if len(names) > 8 else ""),
                    }
                )
            if iso in delivery_bond:
                names = sorted(set(delivery_bond[iso]))
                tags.append(
                    {
                        "kind": "bond_futures",
                        "label": "国债交割",
                        "tone": "warn",
                        "detail": "、".join(names[:6]) + (f" 等{len(names)}个" if len(names) > 6 else ""),
                    }
                )
            if iso in delivery_commodity:
                names = sorted(set(delivery_commodity[iso]))
                tags.append(
                    {
                        "kind": "commodity_futures",
                        "label": f"商品交割·{len(names)}",
                        "tone": "warn",
                        "detail": "、".join(names[:8]) + (f" 等{len(names)}个" if len(names) > 8 else ""),
                    }
                )
            if iso in options_days:
                tags.append({"kind": "options", "label": "期权交割", "tone": "accent", "detail": "股指/ETF期权交割临近窗口"})
            if iso in quarter_end_days:
                tags.append({"kind": "quarter_end", "label": "季末", "tone": "info", "detail": "季度末交易日"})
            elif iso in month_end_days:
                tags.append({"kind": "month_end", "label": "月末", "tone": "info", "detail": "月度最后交易日"})
            for event_label in list(dict.fromkeys(macro_by_date.get(iso, [])))[:3]:
                tags.append({"kind": "macro", "label": event_label, "tone": "macro", "detail": event_label})

            days.append(
                {
                    "date": iso,
                    "is_open": is_open,
                    "session": session,
                    "weekday": weekday,
                    "tags": tags,
                }
            )
            cursor += timedelta(days=1)

        # Persist a flat event cache so legacy /market/calendar list is not empty.
        try:
            written = MarketService._persist_trading_calendar_events(days)
            if written:
                sources.append("cache.market_calendar_events")
        except Exception as exc:
            errors.append(f"persist:{type(exc).__name__}")
            logger.warning("persist trading calendar events failed: %s", exc)

        return {
            "start": start_iso,
            "end": end_iso,
            "days": days,
            "source_label": " · ".join(dict.fromkeys(sources)) if sources else "日历数据不可用",
            "sources": sources,
            "errors": errors,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

    @staticmethod
    def _persist_trading_calendar_events(days: List[Dict[str, Any]]) -> int:
        written = 0
        if not hasattr(db, "insert_market_calendar_event"):
            return 0
        for day in days:
            iso = str(day.get("date") or "")
            for tag in day.get("tags") or []:
                kind = str(tag.get("kind") or "")
                label = str(tag.get("label") or "")
                if kind == "session" and label in {"开盘", "待定"}:
                    continue
                category = {
                    "session": "休市",
                    "holiday": "节假日",
                    "index_futures": "交割日",
                    "bond_futures": "交割日",
                    "commodity_futures": "交割日",
                    "options": "交割日",
                    "month_end": "结算日",
                    "quarter_end": "结算日",
                    "macro": "重大事项",
                }.get(kind, "市场事件")
                detail = str(tag.get("detail") or label)
                db.insert_market_calendar_event(
                    event_date=iso,
                    title=f"{label}" + (f" · {detail}" if detail and detail != label else ""),
                    category=category,
                    market="A股",
                    source="trading_calendar_builder",
                    details=detail,
                    event_key=f"{iso}:{kind}:{label}",
                )
                written += 1
        return written

    @staticmethod
    def get_market_calendar_events(start: Optional[str] = None, end: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        try:
            limit = max(1, min(int(limit), 500))
        except Exception:
            limit = 200

        # 使用本地数据库查询
        try:
            events = db.get_market_calendar_events(start, end)
            # 应用限制
            events = events[:limit]
            mapped = [
                {
                    "event_key": r.get("event_key", str(r.get("id", ""))),  # 使用event_key作为主键
                    "event_date": r.get("event_date"),
                    "title": r.get("title", r.get("event_description", "")),
                    "category": r.get("category", r.get("event_type", "")),
                    "market": r.get("market", "A股"),
                    "source": r.get("source", "database"),
                    "details": r.get("details", ""),
                    "updated_at": r.get("updated_at", r.get("created_at", "")),
                }
                for r in events
            ]
            if mapped:
                return mapped
        except Exception as e:
            logger.error(f"Failed to read market calendar events: {e}")

        # Empty cache: build live month window so the UI is not blank.
        today = datetime.now().date()
        start_iso = (start or today.replace(day=1).isoformat())[:10]
        try:
            start_d = datetime.strptime(start_iso, "%Y-%m-%d").date()
        except ValueError:
            start_d = today.replace(day=1)
        end_iso = (end or ((start_d.replace(day=28) + timedelta(days=4)).replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)).isoformat()[:10]
        built = MarketService.get_trading_calendar(start=start_iso, end=end_iso if isinstance(end_iso, str) else str(end_iso))
        flat: List[Dict[str, Any]] = []
        for day in built.get("days") or []:
            for tag in day.get("tags") or []:
                kind = str(tag.get("kind") or "")
                label = str(tag.get("label") or "")
                if kind == "session" and label == "开盘":
                    continue
                flat.append(
                    {
                        "event_key": f"{day.get('date')}:{kind}:{label}",
                        "event_date": day.get("date"),
                        "title": label,
                        "category": kind,
                        "market": "A股",
                        "source": built.get("source_label"),
                        "details": tag.get("detail"),
                        "updated_at": built.get("updated_at"),
                    }
                )
        return flat[:limit]

    @staticmethod
    def fetch_free_calendar_data() -> List[Dict[str, Any]]:
        """
        获取免费的日历数据，包括重要的金融日期事件
        如期权交割日、期货交割日、节假日等
        """
        try:
            # 获取交易日历
            trade_dates_df = ak.tool_trade_date_hist_sina()
            if trade_dates_df is None or trade_dates_df.empty:
                return []
            
            # 获取节假日信息
            holidays = MarketService._get_holidays()
            
            # 获取交易日列表
            trade_dates = []
            date_col = 'trade_date' if 'trade_date' in trade_dates_df.columns else trade_dates_df.columns[0]
            for _, row in trade_dates_df.iterrows():
                date_str = str(row[date_col])
                # 格式化日期为 YYYY-MM-DD
                try:
                    parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
                    trade_dates.append(parsed_date.date())
                except ValueError:
                    try:
                        parsed_date = datetime.strptime(date_str, '%Y%m%d')
                        trade_dates.append(parsed_date.date())
                    except ValueError:
                        continue
            
            # 按日期排序
            trade_dates.sort()
            
            # 计算重要的金融日期事件
            events = []
            
            # 1. 期权交割日（每月第四个星期三的前一个交易日）
            events.extend(MarketService._calculate_options_expiry_dates(trade_dates))
            
            # 2. 股指期货交割日（每月第三个星期五的前一个交易日）
            events.extend(MarketService._calculate_futures_expiry_dates(trade_dates))
            
            # 3. 月度结算日（每个交易月的最后一个交易日）
            events.extend(MarketService._calculate_month_end_dates(trade_dates))
            
            # 4. 季度末事件（季度末月的最后交易日）
            events.extend(MarketService._calculate_quarter_end_dates(trade_dates))
            
            # 5. 节假日事件
            events.extend(holidays)
            
            return events
        
        except Exception as e:
            logger.error(f"Error fetching free calendar data: {e}")
            return []

    @staticmethod
    def _get_holidays() -> List[Dict[str, Any]]:
        """获取节假日信息"""
        # 目前暂时使用硬编码的节假日信息
        # 在实际应用中，可以从API获取最新的节假日安排
        holidays = [
            # 2026年节假日
            {"date": "2026-01-01", "name": "元旦", "type": "节假日"},
            {"date": "2026-02-17", "name": "春节", "type": "节假日"},
            {"date": "2026-02-18", "name": "春节", "type": "节假日"},
            {"date": "2026-02-19", "name": "春节", "type": "节假日"},
            {"date": "2026-02-20", "name": "春节", "type": "节假日"},
            {"date": "2026-02-21", "name": "春节", "type": "节假日"},
            {"date": "2026-02-22", "name": "春节", "type": "节假日"},
            {"date": "2026-02-23", "name": "春节", "type": "节假日"},
            {"date": "2026-04-04", "name": "清明节", "type": "节假日"},
            {"date": "2026-04-05", "name": "清明节", "type": "节假日"},
            {"date": "2026-04-06", "name": "清明节", "type": "节假日"},
            {"date": "2026-05-01", "name": "劳动节", "type": "节假日"},
            {"date": "2026-05-02", "name": "劳动节", "type": "节假日"},
            {"date": "2026-05-03", "name": "劳动节", "type": "节假日"},
            {"date": "2026-05-04", "name": "劳动节", "type": "节假日"},
            {"date": "2026-06-10", "name": "端午节", "type": "节假日"},
            {"date": "2026-09-15", "name": "中秋节", "type": "节假日"},
            {"date": "2026-09-16", "name": "中秋节", "type": "节假日"},
            {"date": "2026-09-17", "name": "中秋节", "type": "节假日"},
            {"date": "2026-10-01", "name": "国庆节", "type": "节假日"},
            {"date": "2026-10-02", "name": "国庆节", "type": "节假日"},
            {"date": "2026-10-03", "name": "国庆节", "type": "节假日"},
            {"date": "2026-10-04", "name": "国庆节", "type": "节假日"},
            {"date": "2026-10-05", "name": "国庆节", "type": "节假日"},
            {"date": "2026-10-06", "name": "国庆节", "type": "节假日"},
            {"date": "2026-10-07", "name": "国庆节", "type": "节假日"},
        ]
        
        # 转换为市场日历事件格式
        events = []
        for holiday in holidays:
            events.append({
                "event_key": f"holiday:{holiday['date']}:{holiday['name']}",
                "event_date": holiday['date'],
                "title": f"{holiday['name']}休市",
                "category": holiday['type'],
                "market": "A股",
                "source": "holiday_data",
                "details": f"因{holiday['name']}假期，A股市场休市",
                "updated_at": datetime.now().isoformat(),
            })
        return events

    @staticmethod
    def _calculate_options_expiry_dates(trade_dates: List[date]) -> List[Dict[str, Any]]:
        """计算期权交割日（每月第四个星期三的前一个交易日）"""
        from collections import defaultdict
        
        # 按年月分组交易日
        monthly_trades = defaultdict(list)
        for trade_date in trade_dates:
            key = (trade_date.year, trade_date.month)
            monthly_trades[key].append(trade_date)
        
        events = []
        for (year, month), dates in monthly_trades.items():
            # 找到该月第四个星期三
            # 计算当月第一个星期三是几号
            first_day = date(year, month, 1)
            # 计算第一个星期三是哪一天
            first_wednesday_offset = (2 - first_day.weekday()) % 7  # 2代表星期三
            first_wednesday = first_day + timedelta(days=first_wednesday_offset)
            
            # 第四个星期三
            fourth_wednesday = first_wednesday + timedelta(weeks=3)
            
            # 期权交割日是第四个星期三的前一个交易日
            expiry_date = None
            for trade_date in sorted(dates, reverse=True):
                if trade_date <= fourth_wednesday:
                    expiry_date = trade_date
                    break
            
            if expiry_date:
                events.append({
                    "event_key": f"options_expiry:{expiry_date.isoformat()}",
                    "event_date": expiry_date.isoformat(),
                    "title": f"期权交割日 - {year}年{month}月", 
                    "category": "交割日",
                    "market": "A股",
                    "source": "calculated",
                    "details": f"ETF期权及股指期权交割日，通常会对市场产生波动影响",
                    "updated_at": datetime.now().isoformat(),
                })
        
        return events

    @staticmethod
    def _calculate_futures_expiry_dates(trade_dates: List[date]) -> List[Dict[str, Any]]:
        """计算股指期货交割日（每月第三个星期五的前一个交易日）"""
        from collections import defaultdict
        
        # 按年月分组交易日
        monthly_trades = defaultdict(list)
        for trade_date in trade_dates:
            key = (trade_date.year, trade_date.month)
            monthly_trades[key].append(trade_date)
        
        events = []
        for (year, month), dates in monthly_trades.items():
            # 找到该月第三个星期五
            first_day = date(year, month, 1)
            # 计算第一个星期五是哪一天
            first_friday_offset = (4 - first_day.weekday()) % 7  # 4代表星期五
            first_friday = first_day + timedelta(days=first_friday_offset)
            
            # 第三个星期五
            third_friday = first_friday + timedelta(weeks=2)
            
            # 期货交割日是第三个星期五的前一个交易日
            expiry_date = None
            for trade_date in sorted(dates, reverse=True):
                if trade_date <= third_friday:
                    expiry_date = trade_date
                    break
            
            if expiry_date:
                events.append({
                    "event_key": f"futures_expiry:{expiry_date.isoformat()}",
                    "event_date": expiry_date.isoformat(),
                    "title": f"股指期货交割日 - {year}年{month}月",
                    "category": "交割日",
                    "market": "A股",
                    "source": "calculated",
                    "details": f"沪深300、中证500、上证50等股指期货交割日，市场波动可能加剧",
                    "updated_at": datetime.now().isoformat(),
                })
        
        return events

    @staticmethod
    def _calculate_month_end_dates(trade_dates: List[date]) -> List[Dict[str, Any]]:
        """计算月末交易日"""
        from collections import defaultdict
        
        # 按年月分组交易日
        monthly_trades = defaultdict(list)
        for trade_date in trade_dates:
            key = (trade_date.year, trade_date.month)
            monthly_trades[key].append(trade_date)
        
        events = []
        for (year, month), dates in monthly_trades.items():
            # 月末交易日是该月的最后一个交易日
            last_trade_date = max(dates)
            events.append({
                "event_key": f"month_end:{last_trade_date.isoformat()}",
                "event_date": last_trade_date.isoformat(),
                "title": f"{year}年{month}月月末交易日",
                "category": "结算日",
                "market": "A股",
                "source": "calculated",
                "details": f"月末结算日，基金调仓、机构结账等操作可能增加市场波动",
                "updated_at": datetime.now().isoformat(),
            })
        
        return events

    @staticmethod
    def _calculate_quarter_end_dates(trade_dates: List[date]) -> List[Dict[str, Any]]:
        """计算季度末交易日"""
        quarter_months = {3, 6, 9, 12}  # 季度末月份
        from collections import defaultdict
        
        # 按年月分组交易日
        monthly_trades = defaultdict(list)
        for trade_date in trade_dates:
            key = (trade_date.year, trade_date.month)
            monthly_trades[key].append(trade_date)
        
        events = []
        for (year, month), dates in monthly_trades.items():
            if month in quarter_months:  # 如果是季度末月份
                # 季度末交易日是该月的最后一个交易日
                last_trade_date = max(dates)
                quarter = (month - 1) // 3 + 1
                events.append({
                    "event_key": f"quarter_end:{last_trade_date.isoformat()}",
                    "event_date": last_trade_date.isoformat(),
                    "title": f"{year}年第{quarter}季度末交易日",
                    "category": "季报期",
                    "market": "A股",
                    "source": "calculated",
                    "details": f"季度末及季报披露关键期，市场关注企业业绩表现",
                    "updated_at": datetime.now().isoformat(),
                })
        
        return events

    @staticmethod
    def refresh_market_calendar_with_free_data(months: int = 6) -> Dict[str, Any]:
        """使用免费数据源刷新市场日历"""
        try:
            months = max(1, min(int(months), 24))
        except Exception:
            months = 6
        
        # 获取免费日历数据
        free_events = MarketService.fetch_free_calendar_data()
        
        # 过滤出未来几个月的数据
        today = datetime.now().date()
        future_cutoff = today + timedelta(days=months * 31)
        
        future_events = []
        for event in free_events:
            event_date = datetime.strptime(event['event_date'], '%Y-%m-%d').date()
            if today <= event_date <= future_cutoff:
                future_events.append(event)
        
        # 清空数据库中的现有日历事件
        # 注意：这里应该更精确地只删除指定范围内的数据，为简化实现暂时跳过清空
        
        # 插入新事件到数据库
        written = 0
        try:
            # 按月份分批处理
            from collections import defaultdict
            monthly_events = defaultdict(list)
            for event in future_events:
                event_date = datetime.strptime(event['event_date'], '%Y-%m-%d').date()
                key = (event_date.year, event_date.month)
                monthly_events[key].append(event)
            
            for (year, month), events in monthly_events.items():
                for event in events:
                    # 提取所需字段
                    event_date = event['event_date']
                    event_type = event['category']
                    event_description = event['title']
                    source = event['source']
                    details = event['details']
                    
                    # 插入到数据库
                    db.insert_market_calendar_event(
                        event_date=event_date,
                        event_type=event_type,
                        event_description=event_description,
                        source=source,
                        details=details
                    )
                    written += 1
        
        except Exception as e:
            logger.error(f"Failed to insert market calendar events: {e}")
            return {"written": written, "error": str(e)}
        
        return {"written": written, "error": None}

    @staticmethod
    def refresh_market_calendar(months: int = 6) -> Dict[str, Any]:
        try:
            months = max(1, min(int(months), 24))
        except Exception:
            months = 6

        trade_dates = MarketService._latest_trade_dates()
        if not trade_dates:
            return {"written": 0, "error": "no trade dates"}

        td: List[date] = []
        for d in trade_dates:
            try:
                td.append(datetime.strptime(d, "%Y%m%d").date())
            except Exception:
                continue

        today = datetime.now().date()
        end_day = today + timedelta(days=months * 31)
        td = [d for d in td if today <= d <= end_day]
        if not td:
            return {"written": 0, "error": "no dates in range"}

        trade_set = set(td)

        def prev_trade_day(d: date) -> Optional[date]:
            cur = d
            for _ in range(15):
                if cur in trade_set:
                    return cur
                cur = cur - timedelta(days=1)
            return None

        by_month: Dict[tuple[int, int], List[date]] = {}
        for d in td:
            by_month.setdefault((d.year, d.month), []).append(d)

        events: List[Dict[str, Any]] = []
        for (y, m), days in sorted(by_month.items()):
            days_sorted = sorted(days)
            last_td = days_sorted[-1]
            events.append(
                {
                    "event_key": f"month_end:{last_td.isoformat()}",
                    "event_date": last_td.isoformat(),
                    "title": f"{y}-{m:02d} 月末交易日",
                    "category": "结算",
                    "market": "A",
                    "source": "computed",
                    "details": None,
                    "updated_at": datetime.now().isoformat(),
                }
            )

            cal = pycalendar.monthcalendar(y, m)
            fridays = [week[pycalendar.FRIDAY] for week in cal if week[pycalendar.FRIDAY] != 0]
            wednesdays = [week[pycalendar.WEDNESDAY] for week in cal if week[pycalendar.WEDNESDAY] != 0]
            third_friday = date(y, m, fridays[2]) if len(fridays) >= 3 else None
            fourth_wed = date(y, m, wednesdays[3]) if len(wednesdays) >= 4 else None

            if third_friday:
                d2 = prev_trade_day(third_friday)
                if d2:
                    events.append(
                        {
                            "event_key": f"index_futures_expiry:{d2.isoformat()}",
                            "event_date": d2.isoformat(),
                            "title": "股指期货交割日(第三个周五)",
                            "category": "交割",
                            "market": "A",
                            "source": "computed",
                            "details": None,
                            "updated_at": datetime.now().isoformat(),
                        }
                    )

            if fourth_wed:
                d3 = prev_trade_day(fourth_wed)
                if d3:
                    events.append(
                        {
                            "event_key": f"etf_options_expiry:{d3.isoformat()}",
                            "event_date": d3.isoformat(),
                            "title": "ETF期权到期日(第四个周三)",
                            "category": "交割",
                            "market": "A",
                            "source": "computed",
                            "details": None,
                            "updated_at": datetime.now().isoformat(),
                        }
                    )

        written = 0
        try:
            chunk_size = 500
            for i in range(0, len(events), chunk_size):
                chunk = events[i : i + chunk_size]
                # 本地数据库实现
                for event in chunk:
                    db.insert_market_calendar_event(
                        event_date=event['event_date'],
                        event_type=event['category'],
                        event_description=event['title'],
                        source=event['source'],
                        details=event['details']
                    )
                written += len(chunk)
        except Exception as e:
            logger.error(f"Failed to upsert market calendar events: {e}")
            return {"written": written, "error": str(e)}

        return {"written": written, "error": None}


    @staticmethod
    def generate_market_calendar_with_ai(start_date: str, end_date: str) -> Dict[str, Any]:
        """
        使用千问大模型归纳股市相关的重大日期
        如股权交割、金融场景的重大交割等
        """
        try:
            from app.services.ai_service import AIService
            import dashscope
            from app.core.config import settings
            
            # 设置dashscope API密钥
            dashscope.api_key = settings.QWEN_API_KEY
            
            # 构造AI提示词，让大模型归纳重大金融日期
            prompt = f"""
            请基于A股市场特点，归纳从{start_date}到{end_date}期间可能发生的重大金融日期事件。
            
            重点关注以下类型的事件：
            1. 股权交割日
            2. 重大金融产品的交割日
            3. IPO/增发缴款日
            4. 股息发放日
            5. 除权除息日
            6. 重大财报发布日
            7. 重要经济数据发布日
            8. 政策实施日
            9. 节假日对市场的影响
            10. 其他对市场有重大影响的日期
            
            请严格按照以下JSON格式返回结果，不要包含任何额外的文字说明：
            [
              {{
                "event_date": "YYYY-MM-DD",
                "title": "事件标题",
                "category": "事件类别(如:交割日、财报、政策等)",
                "market": "A股",
                "source": "AI归纳",
                "details": "事件详细说明"
              }}
            ]
            
            请确保返回的日期在{start_date}到{end_date}范围内。
            """
            
            # 调用千问API
            response = dashscope.Generation.call(
                model=settings.QWEN_STOCK_MODEL,
                prompt=prompt,
                result_format="message",
            )
            
            if response.status_code == 200:
                content = response.output.choices[0].message.content
                
                # 清理markdown格式
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                
                import json
                events = json.loads(content.strip())
                
                # 生成唯一事件键并准备插入数据库
                processed_events = []
                for event in events:
                    event_key = hashlib.sha1(f"ai_calendar:{event['event_date']}:{event['title']}".encode("utf-8")).hexdigest()
                    processed_events.append({
                        "event_key": event_key,
                        "event_date": event["event_date"],
                        "title": event["title"],
                        "category": event.get("category", "金融事件"),
                        "market": event.get("market", "A股"),
                        "source": event.get("source", "AI归纳"),
                        "details": event.get("details", ""),
                        "updated_at": datetime.now().isoformat(),
                    })
                
                # 插入到数据库
                if processed_events:
                    chunk_size = 500
                    written = 0
                    for i in range(0, len(processed_events), chunk_size):
                        chunk = processed_events[i : i + chunk_size]
                        # 本地数据库实现
                        for event in chunk:
                            db.insert_market_calendar_event(
                                event_date=event['event_date'],
                                event_type=event['category'],
                                event_description=event['title'],
                                source=event['source'],
                                details=event['details']
                            )
                        written += len(chunk)
                
                return {
                    "generated_events": processed_events,
                    "count": len(processed_events),
                    "status": "success",
                    "message": f"成功生成{len(processed_events)}个AI归纳的金融事件"
                }
            else:
                logger.error(f"AI API Error: {response.code} - {response.message}")
                return {
                    "status": "error",
                    "message": f"AI API调用失败: {response.code} - {response.message}",
                    "generated_events": [],
                    "count": 0
                }
        
        except json.JSONDecodeError as e:
            logger.error(f"AI response JSON decode error: {e}")
            return {
                "status": "error",
                "message": f"AI响应解析失败: {str(e)}",
                "generated_events": [],
                "count": 0
            }
        except Exception as e:
            logger.error(f"Error generating market calendar with AI: {e}")
            return {
                "status": "error",
                "message": str(e),
                "generated_events": [],
                "count": 0
            }

    # =============== 复盘中心相关方法 ===============

    @staticmethod
    def get_lianban_history_for_pulse(days: int = 30, min_level: int = 2) -> List[Dict[str, Any]]:
        """获取连板历史数据用于复盘展示"""
        try:
            # 从数据库获取历史数据
            cached_data = db.get_lianban_history_multi_days(days, min_level)
            if cached_data:
                return cached_data
            
            # 如果数据库没有，尝试获取最近几天的实时数据并缓存
            dates = MarketService._latest_trade_dates()
            if not dates:
                return []
            
            today_str = datetime.now().strftime('%Y%m%d')
            available = [d for d in dates if d <= today_str][-days:]
            
            result = []
            for target_date in available:
                try:
                    ladder_data = MarketService.get_lianban_ladder(target_date)
                    if ladder_data and ladder_data.get('levels'):
                        stocks = []
                        for level_info in ladder_data['levels']:
                            level = level_info.get('today_level', 0)
                            if level >= min_level:
                                for item in level_info.get('today_items', []):
                                    stocks.append({
                                        'code': item.get('code', ''),
                                        'name': item.get('name', ''),
                                        'level': level,
                                        'change_percent': item.get('change_percent', 0),
                                        'price': item.get('price', 0),
                                        'duration_days': item.get('duration_days'),
                                        'reason': item.get('reason', '')
                                    })
                        if stocks:
                            result.append({
                                'date': target_date,
                                'stocks': stocks
                            })
                except Exception as e:
                    logger.warning(f"Failed to get lianban ladder for {target_date}: {e}")
                    continue
            
            return result
        except Exception as e:
            logger.error(f"Error getting lianban history for pulse: {e}")
            return []

    @staticmethod
    def get_daily_sector_stats(days: int = 30, min_change_pct: float = 3.0) -> List[Dict[str, Any]]:
        """获取每日板块涨幅统计数据，用于复盘展示板块轮动"""
        try:
            dates = MarketService._latest_trade_dates()
            if not dates:
                return []
            
            today_str = datetime.now().strftime('%Y%m%d')
            available = [d for d in dates if d <= today_str][-days:]
            
            result = []
            
            for target_date in available:
                try:
                    # 获取当日板块数据
                    df = ak.stock_board_concept_name_em()
                    if df is None or df.empty:
                        continue
                    
                    # 找到涨幅列
                    change_col = _find_column(df, ["涨跌幅", "涨幅", "change_percent"])
                    name_col = _find_column(df, ["板块名称", "名称", "name"])
                    code_col = _find_column(df, ["板块代码", "代码", "code"])
                    
                    if not change_col or not name_col:
                        continue
                    
                    sectors = []
                    for _, row in df.iterrows():
                        change_pct = float(pd.to_numeric(row.get(change_col), errors='coerce') or 0)
                        if change_pct >= min_change_pct:
                            sectors.append({
                                'name': str(row.get(name_col, '')),
                                'code': str(row.get(code_col, '')) if code_col else '',
                                'change_percent': round(change_pct, 2)
                            })
                    
                    # 按涨幅排序
                    sectors.sort(key=lambda x: x['change_percent'], reverse=True)
                    
                    if sectors:
                        result.append({
                            'date': target_date,
                            'sectors': sectors[:20]  # 取前20个
                        })
                    
                    # 添加延时避免请求过快
                    time.sleep(0.1)
                    
                except Exception as e:
                    logger.warning(f"Failed to get sector stats for {target_date}: {e}")
                    continue
            
            return result
        except Exception as e:
            logger.error(f"Error getting daily sector stats: {e}")
            return []
