import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

import akshare as ak
import pandas as pd

from app.db import get_database
from app.services.market_service import MarketService

logger = logging.getLogger(__name__)


def _normalize_code(value: str) -> str:
    text = str(value or "").strip().upper()
    if text.startswith(("SH", "SZ", "BJ")) and len(text) >= 8:
        return text[-6:]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits


def _get_exchange_from_code(code: str) -> str:
    """根据股票代码确定交易所"""
    c = str(code or "").strip()
    if c.startswith("688"):
        return "STAR"
    if c.startswith("300"):
        return "CHINEXT"
    if c.startswith("6"):
        return "SH"
    if c.startswith("0") or c.startswith("3"):
        return "SZ"
    if c.startswith("4") or c.startswith("8"):
        return "BJ"
    return "UNKNOWN"


def _is_st_stock(name: str) -> bool:
    """判断是否为ST股票"""
    return "ST" in str(name or "").upper()


def _to_date_str_ymd(date_yyyymmdd: Optional[str]) -> str:
    if date_yyyymmdd and len(date_yyyymmdd) == 8 and date_yyyymmdd.isdigit():
        return f"{date_yyyymmdd[0:4]}-{date_yyyymmdd[4:6]}-{date_yyyymmdd[6:8]}"
    return datetime.now().strftime("%Y-%m-%d")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _zscore(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").fillna(0.0)
    std = float(s.std(ddof=0))
    if std == 0.0:
        return s * 0.0
    mean = float(s.mean())
    return (s - mean) / std


class SentimentService:
    @staticmethod
    def compute_sentiment(
        date: Optional[str] = None,
        universe: Literal["all", "hot"] = "all",
        limit: int = 5000,
    ) -> Dict[str, Any]:
        stocks = MarketService.get_all_stocks()
        if not stocks:
            return {"date": date, "results": [], "message": "no stock data"}

        df = pd.DataFrame(stocks)
        df["code"] = df["code"].apply(_normalize_code)
        df = df[df["code"].str.len() == 6]

        df["change_percent"] = pd.to_numeric(df.get("change_percent"), errors="coerce").fillna(0.0)
        df["amount"] = pd.to_numeric(df.get("amount"), errors="coerce").fillna(0.0)
        df["turnover"] = pd.to_numeric(df.get("turnover"), errors="coerce").fillna(0.0)

        if universe == "hot":
            df = df.sort_values(by="amount", ascending=False).head(600)

        if limit > 0:
            df = df.head(limit)

        limit_map: Dict[str, int] = {}
        try:
            target_date = date or datetime.now().strftime("%Y%m%d")
            zt_df = ak.stock_zt_pool_em(date=target_date)
            if isinstance(zt_df, pd.DataFrame) and not zt_df.empty and "代码" in zt_df.columns:
                zt_df = zt_df.copy()
                if "连板数" in zt_df.columns:
                    zt_df["连板数"] = pd.to_numeric(zt_df["连板数"], errors="coerce").fillna(0).astype(int)
                else:
                    zt_df["连板数"] = 0
                for _, r in zt_df.iterrows():
                    code = _normalize_code(r.get("代码"))
                    lv = int(r.get("连板数") or 0)
                    if code and lv > 0:
                        limit_map[code] = lv
        except Exception as e:
            logger.error(f"limit-up pool unavailable: {e}")

        hot_rank_map: Dict[str, int] = {}
        try:
            hot_df = ak.stock_hot_rank_em()
            if isinstance(hot_df, pd.DataFrame) and not hot_df.empty:
                for _, r in hot_df.head(200).iterrows():
                    code = _normalize_code(r.get("代码"))
                    rank = int(pd.to_numeric(r.get("当前排名"), errors="coerce") or 0)
                    if code and rank > 0:
                        hot_rank_map[code] = rank
        except Exception as e:
            logger.error(f"hot rank unavailable: {e}")

        # 获取市场整体情绪指标
        market_adj = 0.0
        try:
            senti_df = ak.index_news_sentiment_scope()
            if isinstance(senti_df, pd.DataFrame) and not senti_df.empty:
                senti_df = senti_df.copy()
                senti_df["日期"] = pd.to_datetime(senti_df["日期"], errors="coerce")
                if date and len(date) == 8 and date.isdigit():
                    target = pd.to_datetime(date, format="%Y%m%d", errors="coerce")
                    row = senti_df[senti_df["日期"] <= target].tail(1)
                else:
                    row = senti_df.tail(1)
                if not row.empty:
                    value = float(pd.to_numeric(row.iloc[0].get("市场情绪指数"), errors="coerce") or 0.0)
                    all_vals = pd.to_numeric(senti_df["市场情绪指数"], errors="coerce").fillna(0.0)
                    mean = float(all_vals.mean())
                    std = float(all_vals.std(ddof=0)) or 1.0
                    z = (value - mean) / std
                    market_adj = 5.0 * _clamp(z, -2.0, 2.0) / 2.0
        except Exception as e:
            logger.error(f"market sentiment index unavailable: {e}")

        # 计算基础因子
        z_change = _zscore(df["change_percent"])
        z_amount = _zscore(pd.Series([math.log(max(x, 0.0) + 1.0) for x in df["amount"].tolist()]))
        z_turnover = _zscore(df["turnover"])

        # 计算市场情绪因子
        market_sentiment_factors = {}
        try:
            # 获取市场新闻情绪
            news_sentiment_df = ak.stock_news_em()  # 获取个股新闻
            if isinstance(news_sentiment_df, pd.DataFrame) and not news_sentiment_df.empty:
                news_sentiment_df = news_sentiment_df.copy()
                # 将新闻与股票关联
                for _, news_row in news_sentiment_df.iterrows():
                    news_code = _normalize_code(news_row.get('代码', ''))
                    if news_code in df['code'].values:
                        # 这里可以根据新闻标题计算情绪分数
                        title = str(news_row.get('新闻标题', '')).lower()
                        positive_keywords = ['利好', '上涨', '业绩', '增长', '突破', '创新高', '收购', '重组', '盈利']
                        negative_keywords = ['利空', '下跌', '亏损', '处罚', '减持', '诉讼', '风险', '违约', '爆雷']
                        
                        pos_score = sum(1 for kw in positive_keywords if kw in title)
                        neg_score = sum(1 for kw in negative_keywords if kw in title)
                        news_sentiment = pos_score - neg_score
                        market_sentiment_factors[news_code] = news_sentiment
        except Exception as e:
            logger.warning(f"news sentiment unavailable: {e}")

        results: List[Dict[str, Any]] = []
        for i, row in df.reset_index(drop=True).iterrows():
            code = str(row.get("code") or "")
            name = str(row.get("name") or "")
            change_percent = float(row.get("change_percent") or 0.0)
            amount = float(row.get("amount") or 0.0)
            turnover = float(row.get("turnover") or 0.0)

            # 基础情绪得分
            base = 50.0
            base += 20.0 * _clamp(float(z_change.iloc[i]), -2.0, 2.0) / 2.0
            base += 15.0 * _clamp(float(z_amount.iloc[i]), -2.0, 2.0) / 2.0
            base += 15.0 * _clamp(float(z_turnover.iloc[i]), -2.0, 2.0) / 2.0

            # 根据交易所和股票类型调整
            exchange = _get_exchange_from_code(code)
            is_st = _is_st_stock(name)
            
            # ST股票通常风险较高，降低分数
            st_adj = -5.0 if is_st else 0.0
            
            # 不同交易所的波动性调整
            exchange_adj = 0.0
            if exchange in ["STAR", "CHINEXT"]:
                # 科创板和创业板波动更大，适度调整
                exchange_adj = 2.0 * (_clamp(change_percent, -10.0, 20.0) / 20.0)
            elif exchange == "BJ":
                # 北交所调整
                exchange_adj = 1.0 * (_clamp(change_percent, -5.0, 30.0) / 30.0)

            # 涨跌停板相关加分
            limit_bonus = 0.0
            lianban = limit_map.get(code, 0)
            if lianban > 0:
                limit_bonus = min(35.0, 15.0 + 5.0 * max(lianban - 1, 0))

            # 热度相关加分
            hot_bonus = 0.0
            hot_rank = hot_rank_map.get(code)
            if hot_rank is not None and hot_rank > 0:
                hot_bonus = _clamp((200.0 - float(hot_rank)) / 20.0, 0.0, 10.0)

            # 新闻情绪因子
            news_sentiment = market_sentiment_factors.get(code, 0)
            news_adj = news_sentiment * 2.0  # 每个正负面关键词影响2分

            # 计算最终得分
            score = _clamp(base + limit_bonus + hot_bonus + market_adj + st_adj + exchange_adj + news_adj, 0.0, 100.0)
            level = "热" if score >= 70.0 else ("中" if score >= 40.0 else "冷")

            results.append(
                {
                    "code": code,
                    "name": name,
                    "date": _to_date_str_ymd(date),
                    "score": round(score, 2),
                    "level": level,
                    "components": {
                        "change_percent": round(change_percent, 4),
                        "amount": round(amount, 4),
                        "turnover": round(turnover, 4),
                        "lianban": int(lianban),
                        "hot_rank": int(hot_rank) if hot_rank is not None else None,
                        "market_adj": round(market_adj, 4),
                        "st_adj": round(st_adj, 4),
                        "exchange_adj": round(exchange_adj, 4),
                        "news_adj": round(news_adj, 4),
                        "limit_bonus": round(limit_bonus, 4),
                        "hot_bonus": round(hot_bonus, 4),
                        "base_score": round(base, 4),
                    },
                }
            )

        results.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
        for idx, item in enumerate(results, start=1):
            item["rank"] = idx

        return {"date": date or datetime.now().strftime("%Y%m%d"), "results": results, "message": "ok"}

    @staticmethod
    def store_sentiment(results: List[Dict[str, Any]]) -> Tuple[int, Optional[str]]:
        if not results:
            return 0, "no data"

        try:
            # 使用本地数据库
            chunk_size = 500
            written = 0
            for i in range(0, len(results), chunk_size):
                chunk = results[i : i + chunk_size]
                payload = [
                    {
                        "code": r["code"],
                        "name": r.get("name"),
                        "date": r.get("date"),
                        "score": r.get("score"),
                        "level": r.get("level"),
                        "components": r.get("components"),
                    }
                    for r in chunk
                ]
                # db.insert_stock_sentiment_batch(payload)
                pass
                written += len(payload)
            return written, None
        except Exception as e:
            logger.error(f"store sentiment failed: {e}")
            return 0, str(e)

    @staticmethod
    def query_sentiment(date: Optional[str], limit: int = 200, order: Literal["asc", "desc"] = "desc") -> List[Dict[str, Any]]:
        try:
            limit = max(1, min(int(limit), 1000))
            date_str = _to_date_str_ymd(date)
            # 使用本地数据库
            # res = db.get_stock_sentiment_for_date(date_str, limit, order)
            res = type('obj', (object,), {'data': []})()  # 模拟空结果
            data = res.data or []
            for idx, item in enumerate(data, start=1):
                item["rank"] = idx
            return data
        except Exception as e:
            logger.error(f"query sentiment failed: {e}")
            return []
