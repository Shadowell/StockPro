import dashscope
from app.core.config import settings
from typing import Any, Dict, List, Optional
import logging
import json
from app.models.schemas import AIAnalysisResponse, StockBase
import pandas as pd
from app.services.chart_service import ChartService
from app.db import get_database
from app.db.local_db import db_instance as local_db
from datetime import datetime, timedelta
from app.utils.dashscope_utils import retry_on_dns_error
import time
import akshare as ak

logger = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        dashscope.api_key = settings.QWEN_API_KEY
        self.max_retries = 3
        self.retry_delay = 1.0

    def analyze_stocks(self, stocks: List[StockBase]) -> List[AIAnalysisResponse]:
        if not stocks:
            return []
            
        # Construct prompt
        stocks_info = "\n".join([f"{s.code} {s.name}: 现价 {s.current_price}, 涨幅 {s.change_percent}%, 市值 {s.market_cap/100000000:.2f}亿, 换手率(量) {s.volume}" for s in stocks])
        
        prompt = f"""
        作为一位资深的A股量化交易员，请分析以下通过"打板策略"（关注资金突破和趋势向上）筛选出来的股票，并给出买入评分（1-10分，10分最推荐）。
        
        评分标准：
        1. 趋势强度：涨幅适中（未过度透支），均线多头排列。
        2. 资金活跃度：成交量有效放大。
        3. 概念题材：结合当前市场热点（如果有）。
        
        股票列表：
        {stocks_info}
        
        请严格按照以下JSON格式返回结果，不要包含任何markdown格式或额外文字：
        [
            {{
                "stock_code": "股票代码",
                "score": 评分(整数),
                "analysis_text": "简短分析理由(50字以内)"
            }}
        ]
        """

        # 使用重试机制调用 API
        return self._call_dashscope_with_retry(
            model='qwen-turbo',
            prompt=prompt,
            on_success=self._parse_analysis_response
        )
    
    def _call_dashscope_with_retry(self, model: str, prompt: str, on_success=None) -> Any:
        """
        带重试机制的 DashScope API 调用
        
        Args:
            model: 模型名称
            prompt: 提示词
            on_success: 成功时的回调函数
            
        Returns:
            API 响应或处理后的结果
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"调用 DashScope API (尝试 {attempt + 1}/{self.max_retries})")
                
                response = dashscope.Generation.call(
                    model=model,
                    prompt=prompt,
                    result_format='message',
                )
                
                if response.status_code == 200:
                    if on_success:
                        return on_success(response.output.choices[0].message.content)
                    return response
                else:
                    logger.warning(f"API 返回错误: {response.code} - {response.message}")
                    if attempt < self.max_retries - 1:
                        wait_time = self.retry_delay * (2 ** attempt)  # 指数退避
                        logger.info(f"{wait_time:.1f}秒后重试...")
                        time.sleep(wait_time)
                    continue
            
            except Exception as e:
                last_exception = e
                logger.warning(f"API 调用异常: {str(e)}")
                
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.info(f"{wait_time:.1f}秒后重试...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"所有重试都失败: {str(e)}")
        
        # 所有重试都失败
        if last_exception:
            logger.error(f"无法完成 API 调用: {str(last_exception)}")
        
        # 返回默认值
        if on_success is self._parse_analysis_response:
            return []
        return None
    
    def _parse_analysis_response(self, content: str) -> List[AIAnalysisResponse]:
        """
        解析分析响应
        """
        try:
            # Clean up markdown if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            results = json.loads(content.strip())
            
            analysis_responses = []
            for res in results:
                analysis_responses.append(AIAnalysisResponse(
                    stock_code=res['stock_code'],
                    score=res['score'],
                    analysis_text=res['analysis_text']
                ))
            return analysis_responses
        except Exception as e:
            logger.error(f"解析响应失败: {e}")
            return []
    
    def _parse_stock_analysis_response(self, content: str) -> tuple:
        """
        解析个股分析响应
        
        Returns:
            (raw_text, parsed_dict) 的元组
        """
        try:
            raw_text = content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            parsed = json.loads(content.strip())
            return (raw_text, parsed)
        except Exception as e:
            logger.error(f"解析个股分析响应失败: {e}")
            return (content, {"error": "解析失败"})

    def _fetch_stock_data(self, code: str) -> Dict[str, Any]:
        """
        从数据库和API获取股票的全面数据
        包括：实时行情、历史K线、基本面、均线、技术指标等
        """
        data = {
            "realtime": None,        # 实时行情
            "kline_60d": [],         # 60日K线数据
            "fundamentals": None,    # 基本面数据
            "ma_data": {},           # 均线数据
            "volume_analysis": {},   # 量能分析
            "indicators": {},        # 技术指标
            "concepts": [],          # 所属概念板块
        }
        
        # 1. 获取实时行情
        try:
            spot_df = ak.stock_zh_a_spot_em()
            if spot_df is not None and not spot_df.empty:
                stock_row = spot_df[spot_df['代码'] == code]
                if not stock_row.empty:
                    row = stock_row.iloc[0]
                    data["realtime"] = {
                        "code": code,
                        "name": str(row.get('名称', '')),
                        "price": float(row.get('最新价', 0) or 0),
                        "open": float(row.get('今开', 0) or 0),
                        "high": float(row.get('最高', 0) or 0),
                        "low": float(row.get('最低', 0) or 0),
                        "pre_close": float(row.get('昨收', 0) or 0),
                        "change_pct": float(row.get('涨跌幅', 0) or 0),
                        "change_amt": float(row.get('涨跌额', 0) or 0),
                        "volume": float(row.get('成交量', 0) or 0),
                        "amount": float(row.get('成交额', 0) or 0),
                        "turnover": float(row.get('换手率', 0) or 0),
                        "market_cap": float(row.get('总市值', 0) or 0),
                        "float_cap": float(row.get('流通市值', 0) or 0),
                        "pe": float(row.get('市盈率-动态', 0) or 0),
                        "pb": float(row.get('市净率', 0) or 0),
                    }
        except Exception as e:
            logger.warning(f"获取实时行情失败: {e}")
        
        # 2. 获取历史K线（60日）
        try:
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=120)).strftime('%Y%m%d')
            
            hist_df = ak.stock_zh_a_hist(symbol=code, period='daily', 
                                          start_date=start_date, end_date=end_date, adjust='qfq')
            if hist_df is not None and not hist_df.empty:
                # 取最近60个交易日
                hist_df = hist_df.tail(60)
                data["kline_60d"] = [
                    {
                        "date": str(row.get('日期', '')),
                        "open": float(row.get('开盘', 0) or 0),
                        "close": float(row.get('收盘', 0) or 0),
                        "high": float(row.get('最高', 0) or 0),
                        "low": float(row.get('最低', 0) or 0),
                        "volume": float(row.get('成交量', 0) or 0),
                        "amount": float(row.get('成交额', 0) or 0),
                        "change_pct": float(row.get('涨跌幅', 0) or 0),
                        "turnover": float(row.get('换手率', 0) or 0),
                    }
                    for _, row in hist_df.iterrows()
                ]
                
                # 3. 计算均线数据
                closes = [k['close'] for k in data["kline_60d"]]
                if len(closes) >= 5:
                    data["ma_data"]["ma5"] = round(sum(closes[-5:]) / 5, 2)
                if len(closes) >= 10:
                    data["ma_data"]["ma10"] = round(sum(closes[-10:]) / 10, 2)
                if len(closes) >= 20:
                    data["ma_data"]["ma20"] = round(sum(closes[-20:]) / 20, 2)
                if len(closes) >= 60:
                    data["ma_data"]["ma60"] = round(sum(closes[-60:]) / 60, 2)
                
                # 判断均线排列
                if data["ma_data"]:
                    mas = data["ma_data"]
                    if all(k in mas for k in ['ma5', 'ma10', 'ma20']):
                        if mas['ma5'] > mas['ma10'] > mas['ma20']:
                            data["ma_data"]["trend"] = "多头排列"
                        elif mas['ma5'] < mas['ma10'] < mas['ma20']:
                            data["ma_data"]["trend"] = "空头排列"
                        else:
                            data["ma_data"]["trend"] = "交叉震荡"
                
                # 4. 量能分析
                volumes = [k['volume'] for k in data["kline_60d"]]
                if len(volumes) >= 5:
                    avg_vol_5 = sum(volumes[-5:]) / 5
                    avg_vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else avg_vol_5
                    latest_vol = volumes[-1] if volumes else 0
                    
                    data["volume_analysis"] = {
                        "latest": latest_vol,
                        "avg_5d": round(avg_vol_5, 0),
                        "avg_20d": round(avg_vol_20, 0),
                        "vol_ratio_5d": round(latest_vol / avg_vol_5, 2) if avg_vol_5 > 0 else 0,
                        "vol_ratio_20d": round(latest_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 0,
                    }
                    
                    # 判断量能状态
                    if data["volume_analysis"]["vol_ratio_5d"] > 1.5:
                        data["volume_analysis"]["status"] = "明显放量"
                    elif data["volume_analysis"]["vol_ratio_5d"] > 1.0:
                        data["volume_analysis"]["status"] = "温和放量"
                    elif data["volume_analysis"]["vol_ratio_5d"] < 0.7:
                        data["volume_analysis"]["status"] = "明显缩量"
                    else:
                        data["volume_analysis"]["status"] = "量能平稳"
                
        except Exception as e:
            logger.warning(f"获取历史K线失败: {e}")
        
        # 5. 从本地数据库获取基本面数据
        try:
            fundamentals = local_db.get_stock_fundamentals(code)
            if fundamentals:
                data["fundamentals"] = fundamentals
        except Exception as e:
            logger.warning(f"获取基本面数据失败: {e}")
        
        return data

    def analyze_stock(self, symbol: str, date: Optional[str] = None) -> Dict[str, Any]:
        """
        综合分析单只股票
        从数据库获取历史数据、基本面数据、K线、均线数据等进行融合分析
        """
        def normalize_code(value: str) -> str:
            text = str(value or "").strip().upper()
            if text.startswith(("SH", "SZ", "BJ")) and len(text) >= 8:
                return text[-6:]
            digits = "".join(ch for ch in text if ch.isdigit())
            return digits[-6:] if len(digits) >= 6 else digits

        code = normalize_code(symbol)
        if len(code) != 6:
            return {
                "symbol": symbol,
                "name": None,
                "model": settings.QWEN_STOCK_MODEL,
                "result": {"error": "invalid symbol"},
                "raw_text": None,
            }

        # 获取全面的股票数据
        stock_data = self._fetch_stock_data(code)
        
        name = stock_data.get("realtime", {}).get("name") or "未知"
        realtime = stock_data.get("realtime") or {}
        kline = stock_data.get("kline_60d", [])
        ma_data = stock_data.get("ma_data", {})
        volume_analysis = stock_data.get("volume_analysis", {})
        fundamentals = stock_data.get("fundamentals") or {}

        # 构建提供给AI的数据摘要
        data_summary = {
            "实时行情": {
                "最新价": realtime.get("price"),
                "涨跌幅": f"{realtime.get('change_pct', 0):.2f}%",
                "成交量": f"{realtime.get('volume', 0)/10000:.0f}万手",
                "成交额": f"{realtime.get('amount', 0)/100000000:.2f}亿",
                "换手率": f"{realtime.get('turnover', 0):.2f}%",
                "总市值": f"{realtime.get('market_cap', 0)/100000000:.0f}亿",
                "市盈率PE": realtime.get("pe"),
                "市净率PB": realtime.get("pb"),
            } if realtime else None,
            "均线系统": {
                "MA5": ma_data.get("ma5"),
                "MA10": ma_data.get("ma10"),
                "MA20": ma_data.get("ma20"),
                "MA60": ma_data.get("ma60"),
                "均线形态": ma_data.get("trend"),
            } if ma_data else None,
            "量能分析": {
                "今日成交量": volume_analysis.get("latest"),
                "5日均量": volume_analysis.get("avg_5d"),
                "20日均量": volume_analysis.get("avg_20d"),
                "量比(vs5日)": volume_analysis.get("vol_ratio_5d"),
                "量比(vs20日)": volume_analysis.get("vol_ratio_20d"),
                "量能状态": volume_analysis.get("status"),
            } if volume_analysis else None,
            "近10日K线": [
                {
                    "日期": k.get("date"),
                    "开盘": k.get("open"),
                    "收盘": k.get("close"),
                    "最高": k.get("high"),
                    "最低": k.get("low"),
                    "涨跌幅": f"{k.get('change_pct', 0):.2f}%",
                }
                for k in kline[-10:]
            ] if kline else None,
        }

        prompt = f"""
你是一位资深的A股量化交易分析师，精通技术分析、量价分析和趋势研判。请基于提供的多维度数据，对该股票进行全面深入的专业分析。

## 分析股票
- **股票代码**：{code}
- **股票名称**：{name}

## 数据来源
以下是从数据库和实时API获取的股票数据：
{json.dumps(data_summary, ensure_ascii=False, indent=2)}

## 分析要求
请从以下维度进行专业分析：

### 1. 核心观点 (Summary)
用2-3句话总结该股票当前状态和操作建议，直接给出你的判断。

### 2. 趋势研判 (Trend Analysis)
- **短线趋势**（1-5天）：明确给出偏多/偏空/震荡判断
- **中线趋势**（1-4周）：明确给出偏多/偏空/震荡判断
- **判断依据**：列出3-5个支撑你判断的关键因素

### 3. 技术分析 (Technical Analysis)
- **均线分析**：根据MA5/MA10/MA20/MA60的位置关系，分析均线系统状态
- **量价分析**：结合成交量变化，分析量价配合情况
- **K线形态**：识别近期K线是否形成特殊形态（如启明星、乌云盖顶、吞没形态等）
- **支撑压力**：根据近期高低点，给出关键支撑位和压力位

### 4. 操作建议 (Trading Plan)
- **短线策略**：明确的买入/卖出条件和仓位建议
- **止损位置**：明确的止损价位
- **目标位置**：短期和中期目标价位
- **策略失效**：什么情况下该策略需要调整

### 5. 风险提示 (Risk Warning)
列出当前需要警惕的主要风险点（技术面、资金面、市场面等）

## 输出格式
只输出严格JSON格式，不要markdown标记：
{{
  "stock_code": "{code}",
  "stock_name": "{name}",
  "summary": "核心观点：2-3句话概括当前状态和操作建议",
  "trend": {{
    "bias": "偏多/偏空/震荡",
    "short_term": "短线(1-5天)趋势判断及依据",
    "mid_term": "中线(1-4周)趋势判断及依据",
    "evidence": ["判断依据1", "判断依据2", "判断依据3"]
  }},
  "technical_analysis": {{
    "ma_analysis": "均线系统详细分析",
    "volume_analysis": "量价关系分析",
    "pattern": "K线形态分析",
    "key_observation": "最值得关注的技术信号"
  }},
  "key_levels": {{
    "support": ["支撑位1", "支撑位2"],
    "resistance": ["压力位1", "压力位2"],
    "stop_loss": "建议止损位"
  }},
  "plan": {{
    "action": "建议操作：买入/持有/减仓/观望",
    "entry_condition": "买入条件",
    "position": "建议仓位比例",
    "target_short": "短期目标位",
    "target_mid": "中期目标位",
    "stop_loss": "止损价位",
    "invalid_condition": "策略失效条件"
  }},
  "risks": ["风险点1", "风险点2", "风险点3"],
  "confidence": "高/中/低（对本次分析的置信度）",
  "data_quality": "数据充足/数据有限（说明数据质量）"
}}
"""

        model = settings.QWEN_STOCK_MODEL
        raw_text: Optional[str] = None
        parsed: Dict[str, Any] = {}

        # 使用重试机制调用 API
        response = self._call_dashscope_with_retry(
            model=model,
            prompt=prompt,
            on_success=self._parse_stock_analysis_response
        )
        
        if response is None:
            parsed = {"error": "无法完成 API 调用，请检查网络连接或 API 密钥"}
        else:
            raw_text, parsed = response

        if not isinstance(parsed, dict):
            parsed = {"result": parsed}

        return {
            "symbol": code,
            "name": name,
            "model": model,
            "result": parsed,
            "raw_text": raw_text,
            "data_used": data_summary,  # 返回使用的数据，便于调试
        }
