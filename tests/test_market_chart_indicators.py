import sys
import asyncio
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain.market.service import MarketDomainService
from app.domain.market.repository import MarketRepository
from app.domain.market.akshare_intraday import AkshareIntradayProvider
from app.domain.market.akshare_symbols import AkshareSymbolProvider


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


def test_akshare_intraday_provider_maps_eastmoney_minute_rows() -> None:
    provider = AkshareIntradayProvider(
        fetcher=lambda **_kwargs: [
            {
                "时间": "2026-08-27 09:31:00",
                "开盘": 12.3,
                "收盘": 12.4,
                "最高": 12.5,
                "最低": 12.2,
                "成交量": 321,
                "成交额": 398040,
            }
        ]
    )

    payload = provider.fetch("SSE", "600519.SH", "1m", 10)

    assert payload["data_status"] == "ok"
    assert payload["provider_source"] == "akshare.stock_zh_a_hist_min_em"
    assert payload["external_fetch"] is True
    assert payload["items"][0]["source"] == "akshare.stock_zh_a_hist_min_em"
    assert payload["items"][0]["volume"] == 32100.0
    assert payload["items"][0]["quote_volume"] == 398040.0
    assert payload["items"][0]["trade_date"] == "2026-08-27"


def test_market_domain_fetches_akshare_intraday_when_minute_cache_empty() -> None:
    class EmptyMinuteRepo:
        def get_klines_with_status(self, exchange, symbol, timeframe, limit, start=None, end=None):
            return {
                "exchange": exchange,
                "symbol": symbol,
                "timeframe": timeframe,
                "items": [],
                "data_status": "empty",
                "unavailable_reason": "no A-share 1m minute bar cache for 600519.SH",
            }

    class FakeIntradayProvider:
        def fetch(self, exchange, symbol, timeframe, limit, start=None, end=None):
            return {
                "exchange": exchange,
                "symbol": symbol,
                "timeframe": timeframe,
                "items": [
                    {
                        "timestamp": 1_000,
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10.5,
                        "volume": 100,
                        "quote_volume": 1050,
                        "source": "akshare.stock_zh_a_hist_min_em",
                    }
                ],
                "data_status": "ok",
                "provider_source": "akshare.stock_zh_a_hist_min_em",
                "external_fetch": True,
            }

    service = MarketDomainService(repo=EmptyMinuteRepo(), intraday_provider=FakeIntradayProvider())

    payload = asyncio.run(service.get_klines_payload("SSE", "600519.SH", "1m", 50))
    indicators = asyncio.run(service.get_technical_indicators("SSE", "600519.SH", "1m", 50, ema_periods=[1]))

    assert payload["items"][0]["close"] == 10.5
    assert payload["provider_source"] == "akshare.stock_zh_a_hist_min_em"
    assert payload["fallback_from"]["data_status"] == "empty"
    assert indicators["kline_source"] == "akshare.stock_zh_a_hist_min_em"
    assert indicators["timestamps"] == [1_000]


def test_market_domain_fetches_akshare_intraday_when_cache_is_unavailable() -> None:
    class UnavailableMinuteRepo:
        def get_klines_with_status(self, *_args, **_kwargs):
            raise RuntimeError("database temporarily unavailable")

    class FakeIntradayProvider:
        def fetch(self, exchange, symbol, timeframe, limit, start=None, end=None):
            return {
                "exchange": exchange,
                "symbol": symbol,
                "timeframe": timeframe,
                "items": [{"timestamp": 1_000, "close": 10.5}],
                "data_status": "ok",
                "provider_source": "akshare.stock_zh_a_minute",
                "external_fetch": True,
            }

    service = MarketDomainService(repo=UnavailableMinuteRepo(), intraday_provider=FakeIntradayProvider())

    payload = asyncio.run(service.get_klines_payload("SSE", "600519.SH", "1m", 50))

    assert payload["items"][0]["close"] == 10.5
    assert payload["provider_source"] == "akshare.stock_zh_a_minute"
    assert payload["fallback_from"]["data_status"] == "unavailable"
    assert "RuntimeError" in payload["fallback_from"]["unavailable_reason"]


def test_market_symbols_fall_back_to_akshare_when_repository_is_empty() -> None:
    class EmptyInstrumentRepo:
        def list_instruments(self, asset_class, limit):
            assert asset_class == "stock"
            assert limit == 10000
            return []

    provider = AkshareSymbolProvider(
        fetcher=lambda: [
            {"代码": "920061", "名称": "华阳变速"},
            {"代码": "600519", "名称": "贵州茅台"},
        ]
    )
    service = MarketDomainService(repo=EmptyInstrumentRepo(), symbol_provider=provider)

    payload = asyncio.run(service.get_instruments("SSE", "CNY", "stock"))
    symbols = asyncio.run(service.get_symbols("SSE", "CNY", "stock"))

    assert symbols == ["920061.BJ", "600519.SH"]
    assert payload[0]["name"] == "华阳变速"
    assert payload[0]["exchange"] == "BSE"
    assert payload[1]["name"] == "贵州茅台"
    assert payload[1]["source"] == "akshare.stock_zh_a_spot_em"


def test_market_symbols_fall_back_to_akshare_when_repository_is_unavailable() -> None:
    class UnavailableInstrumentRepo:
        def list_symbols(self, *_args, **_kwargs):
            raise RuntimeError("database temporarily unavailable")

        def list_instruments(self, *_args, **_kwargs):
            raise RuntimeError("database temporarily unavailable")

    provider = AkshareSymbolProvider(fetcher=lambda: [{"code": "000001", "name": "平安银行"}])
    service = MarketDomainService(repo=UnavailableInstrumentRepo(), symbol_provider=provider)

    symbols = asyncio.run(service.get_symbols("SSE", "CNY", "stock"))
    payload = asyncio.run(service.get_instruments("SSE", "CNY", "stock"))

    assert symbols == ["000001.SZ"]
    assert payload == [
        {
            "symbol": "000001.SZ",
            "name": "平安银行",
            "display_name": "平安银行 000001.SZ",
            "exchange": "SZSE",
            "asset_class": "stock",
            "industry": None,
            "board": None,
            "list_status": "L",
            "source": "akshare.stock_zh_a_spot_em",
            "source_code": "000001",
        }
    ]


def test_market_summary_widgets_return_unavailable_when_repository_is_unavailable() -> None:
    class UnavailableMetricsRepo:
        def get_market_phase(self, *_args, **_kwargs):
            raise RuntimeError("database temporarily unavailable")

        def list_sector_rps(self, *_args, **_kwargs):
            raise RuntimeError("database temporarily unavailable")

        def list_symbol_abnormalities(self, *_args, **_kwargs):
            raise RuntimeError("database temporarily unavailable")

    service = MarketDomainService(repo=UnavailableMetricsRepo())

    phase = asyncio.run(service.get_market_phase())
    rps = asyncio.run(service.list_sector_rps(limit=5))
    movers = asyncio.run(service.list_symbol_abnormalities(limit=5))

    assert phase["status"] == "unavailable"
    assert phase["phase"] == "unknown"
    assert "RuntimeError" in phase["missing_inputs"][0]
    assert rps["data_status"] == "unavailable"
    assert rps["items"] == []
    assert movers["data_status"] == "unavailable"
    assert movers["items"] == []


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


def test_market_page_uses_intraday_during_cn_session_and_daily_history_after_close() -> None:
    market_source = open("frontend/src/pages/Market.tsx", encoding="utf-8").read()
    client_source = open("frontend/src/api/client.ts", encoding="utf-8").read()

    assert "const TIMEFRAMES = ['1m', '5m', '15m', '30m', '60m', '1d']" in market_source
    assert "function defaultMarketTimeframe" in market_source
    assert "? '1m' : '1d'" in market_source
    assert "useState<string>(() => defaultMarketTimeframe())" in market_source
    assert "marketApi.getKlinesPayload" in market_source
    assert "AKShare 分时" in market_source
    assert "实时拉取" in market_source
    assert "getKlinesPayload: getMarketKlinesPayload" in client_source


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
