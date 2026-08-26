import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain.market.service import MarketDomainService
from app.domain.market.repository import MarketRepository


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=()):
        self.query = query
        self.params = params

    def fetchall(self):
        return self.rows


class _FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def set_session(self, **kwargs):
        self.session_kwargs = kwargs

    def cursor(self):
        return _FakeCursor(self.rows)


def test_market_repository_daily_klines_return_status_payload_and_items() -> None:
    repo = MarketRepository(
        "postgresql://example.invalid/db",
        connection_factory=lambda *_args, **_kwargs: _FakeConnection(
            [(date(2026, 8, 26), 10, 11, 9, 10.5, 1000, 2000)]
        ),
    )

    payload = repo.get_klines_with_status("SSE", "600519.SH", "1d", 100)

    assert payload["data_status"] == "ok"
    assert payload["unavailable_reason"] is None
    assert payload["symbol"] == "600519.SH"
    assert payload["items"][0]["trade_date"] == "2026-08-26"
    assert repo.get_klines("SSE", "600519.SH", "1d", 100) == payload["items"]


def test_market_domain_builds_timestamp_aligned_ema_series() -> None:
    klines = [
        {"timestamp": 1_000, "close": 10},
        {"timestamp": 2_000, "close": 20},
        {"timestamp": 3_000, "close": 10},
        {"timestamp": 4_000, "close": 40},
    ]

    payload = MarketDomainService.build_technical_indicators(klines, ema_periods=[2, 3])

    assert payload["source"] == "backend_derived_from_ohlcv"
    assert payload["timestamps"] == [1_000, 2_000, 3_000, 4_000]
    assert payload["series"]["EMA2"] == [None, 15.0, 11.66666667, 30.55555556]
    assert payload["series"]["EMA3"] == [None, None, 13.33333333, 26.66666667]
    assert "MA2" not in payload["series"]


def test_market_domain_builds_rsi_and_macd_series_from_ohlcv() -> None:
    closes = [100 + ((i % 5) - 2) * 1.5 for i in range(60)]
    klines = [{"timestamp": (i + 1) * 1_000, "close": close} for i, close in enumerate(closes)]

    payload = MarketDomainService.build_technical_indicators(klines, ema_periods=[5])

    assert "RSI14" in payload["series"]
    assert "MACD" in payload["series"]
    assert "MACD_signal" in payload["series"]
    assert "MACD_hist" in payload["series"]
    assert len(payload["series"]["RSI14"]) == 60
    assert len(payload["series"]["MACD"]) == 60
    assert any(value is not None for value in payload["series"]["RSI14"])
    assert any(value is not None for value in payload["series"]["MACD"])
    assert any(value is not None for value in payload["series"]["MACD_signal"])
    assert any(value is not None for value in payload["series"]["MACD_hist"])
    for value in payload["series"]["RSI14"]:
        if value is None:
            continue
        assert 0.0 <= value <= 100.0


def test_market_chart_uses_backend_ema_indicator_api_not_local_ma_calculation() -> None:
    market_source = open("frontend/src/pages/Market.tsx", encoding="utf-8").read()
    chart_source = open("frontend/src/components/KlineChart.tsx", encoding="utf-8").read()
    client_source = open("frontend/src/api/client.ts", encoding="utf-8").read()
    backend_source = open("backend/app/api/v2/endpoints/market.py", encoding="utf-8").read()
    domain_source = open("backend/app/domain/market/service.py", encoding="utf-8").read()

    assert "getTechnicalIndicators" in client_source
    assert "getReq('/market/indicators'" in client_source
    assert "emaPeriods" in client_source
    assert "ema_periods" in backend_source
    assert "marketApi.getTechnicalIndicators" in market_source
    assert "indicatorSeries={marketIndicators}" in market_source
    assert "MARKET_EMA_PERIODS" in market_source
    assert "MARKET_MA_PERIODS" not in market_source

    assert "indicatorSeries" in chart_source
    assert "EMA${period}" in chart_source
    assert "calculateFallbackEma" in chart_source
    assert "legendData.push({ name: `EMA${p}`, icon: 'path://M1,5 L18,5' })" in chart_source
    assert "legendData.push(`MA${p}`)" not in chart_source
    assert "calculateMA" not in chart_source
    assert "sum += items[i - j].close" not in chart_source
    assert "SMA(closes" not in domain_source
    assert "EMA(closes" in domain_source
    assert "RSI(closes" in domain_source
    assert "MACD(closes" in domain_source
    assert 'series["RSI14"]' in domain_source
    assert 'series["MACD"]' in domain_source

    assert '@router.get("/indicators")' in backend_source
    assert "get_technical_indicators" in backend_source


def test_market_page_shows_ticker_stats_recent_trades_and_subchart_indicators() -> None:
    market_source = open("frontend/src/pages/Market.tsx", encoding="utf-8").read()
    chart_source = open("frontend/src/components/KlineChart.tsx", encoding="utf-8").read()
    client_source = open("frontend/src/api/client.ts", encoding="utf-8").read()

    assert "当日高" in market_source
    assert "当日低" in market_source
    assert "成交量" in market_source
    assert "成交额" in market_source
    assert "fundingApi.getRate" not in market_source
    assert "最近成交" in market_source
    assert "marketApi.getTrades" in market_source
    assert "getTrades:" in client_source
    assert "getReq('/market/trades'" in client_source

    assert "showRSI" in chart_source
    assert "showMACD" in chart_source
    assert "showRSI={true}" in market_source
    assert "showMACD={true}" in market_source
    assert "indicatorSeries?.RSI14" in chart_source or 'indicatorSeries?.["RSI14"]' in chart_source or "RSI14" in chart_source
    assert "MACD_hist" in chart_source


def test_market_ai_prediction_does_not_extend_ema_into_future_bars() -> None:
    chart_source = open("frontend/src/components/KlineChart.tsx", encoding="utf-8").read()

    assert "function projectNextEma" not in chart_source
    assert "previousEma = projectNextEma" not in chart_source
    assert "predBar && showPredCandles && previousEma != null" not in chart_source
    assert "const fallbackEmaValues = calculateFallbackEma(realCloseValues, period)" in chart_source
    assert "if (realMap.has(ts))" in chart_source
    assert "fallbackEmaValues[realIdx]" in chart_source
    assert "else {\n            padded.push('-');\n          }" in chart_source


def test_market_no_longer_fetches_kairos_prediction_comparison() -> None:
    market_source = open("frontend/src/pages/Market.tsx", encoding="utf-8").read()
    client_source = open("frontend/src/api/client.ts", encoding="utf-8").read()
    backend_source = open("backend/app/api/v2/endpoints/market.py", encoding="utf-8").read()

    assert "getPredictionsCompare" not in market_source
    assert "getPredictionsCompare" not in client_source
    assert '"/predictions/compare"' not in backend_source
    assert "marketApi.getKlines" in market_source


def test_market_kline_chart_shows_visible_ema_value_labels_above_chart() -> None:
    chart_source = open("frontend/src/components/KlineChart.tsx", encoding="utf-8").read()

    assert "const EMA_COLORS = ['#FFD700', '#00BFFF', '#FF69B4', '#00E676']" in chart_source
    assert "function latestFiniteLineValue" in chart_source
    assert "const emaValueLabels = useMemo" in chart_source
    assert "kline-ema-value-strip" in chart_source
    assert "EMA{item.period}:" in chart_source
    assert "style={{ color: item.color }}" in chart_source


def test_kline_charts_keep_ema_markers_aligned_with_line_colors_and_precision() -> None:
    market_chart = open("frontend/src/components/KlineChart.tsx", encoding="utf-8").read()
    watch_chart = open("frontend/src/components/WatchKlineChart.tsx", encoding="utf-8").read()

    assert "function emaSeriesColor(index: number): string" in market_chart
    assert "const color = emaSeriesColor(index)" in market_chart
    assert "lineStyle: { width: 1, color }" in market_chart
    assert "itemStyle: { color }" in market_chart
    assert "formatEmaTooltipValue(param.value)" in market_chart
    assert "minimumFractionDigits: 5" in market_chart
    assert "maximumFractionDigits: 5" in market_chart

    assert "const WATCH_EMA_COLORS" in watch_chart
    assert "function createEmaSeries" in watch_chart
    assert "lineStyle: { color, width: 1.4 }" in watch_chart
    assert "itemStyle: { color }" in watch_chart
    assert "formatEmaTooltipValue(param.value)" in watch_chart
    assert "minimumFractionDigits: 5" in watch_chart
    assert "maximumFractionDigits: 5" in watch_chart
