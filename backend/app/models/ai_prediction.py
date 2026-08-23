"""AI 预测复盘 / 对比 API 的 Pydantic 模型（文档与校验）。"""

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class PredictionCompareBar(BaseModel):
    """单根 K 线或预测柱（与前端 Kline 结构兼容的松散字典亦可）。"""

    model_config = {"extra": "allow"}

    timestamp: int
    open: float
    high: float
    low: float
    close: float


class PredictionCompareResponse(BaseModel):
    """GET /market/predictions/compare 响应体。"""

    klines: List[Dict[str, Any]] = Field(default_factory=list, description="时间窗内真实 K 线")
    historical_predicted_bars: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="与历史真实时间重叠的已落库预测（每 target 取最新 predicted_at）",
    )
    future_predicted_bars: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="当前模型生成的最新未来预测 K 线",
    )
