from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime

class StockBase(BaseModel):
    code: str
    name: str
    current_price: float
    change_percent: float
    volume: int
    market_cap: int
    is_short: bool = False

class Stock(StockBase):
    updated_at: datetime

    class Config:
        from_attributes = True

class SectorBase(BaseModel):
    name: str
    change_percent: float
    up_count: int
    down_count: int
    leader_stock: Optional[str] = None

class Sector(SectorBase):
    id: str
    updated_at: datetime

    class Config:
        from_attributes = True

class StockFilterResponse(BaseModel):
    stocks: List[StockBase]
    total_count: int
    filter_time: datetime

class StockFundamentals(BaseModel):
    code: str
    name: Optional[str] = None
    current_price: Optional[float] = None
    change_percent: Optional[float] = None
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None
    pe_dynamic: Optional[float] = None
    pb: Optional[float] = None
    total_market_cap: Optional[float] = None
    float_market_cap: Optional[float] = None
    amplitude: Optional[float] = None
    updated_at: Optional[datetime] = None

class AIAnalysisRequest(BaseModel):
    stocks: List[StockBase]

class AIAnalysisResponse(BaseModel):
    stock_code: str
    score: int
    analysis_text: str


class AIStockAnalyzeRequest(BaseModel):
    symbol: str
    date: Optional[str] = None


class AIStockAnalyzeResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    model: str
    result: Dict[str, Any]
    raw_text: Optional[str] = None
