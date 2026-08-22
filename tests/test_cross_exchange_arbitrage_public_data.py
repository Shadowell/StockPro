import asyncio
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.arbitrage.service import ArbitrageDomainService, PublicArbitrageSnapshotProvider  # noqa: E402
from app.services.cross_exchange_paper_account import CrossExchangePaperPortfolio  # noqa: E402


class StaticArbitrageProvider:
    def __init__(self, okx=None, binance=None, depth=None):
        self.okx = okx or {}
        self.binance = binance or {}
        self.depth = depth or {}

    async def get_okx_snapshots(self, symbols):
        return {symbol: self.okx[symbol] for symbol in symbols if symbol in self.okx}

    async def get_binance_snapshots(self):
        return dict(self.binance)

    async def get_depth_usdt(self, exchange, symbol, side, limit=20):
        return self.depth.get((exchange, symbol, side))


class StaticPortfolioProvider:
    def summary(self):
        return {
            "portfolio_positions": [
                {
                    "symbol": "BTC/USDT:USDT",
                    "long_exchange": "binanceusdm",
                    "short_exchange": "okx",
                    "net_exposure_usdt": 1.25,
                    "unrealized_pnl_usdt": 0.8,
                }
            ],
            "leg_status": [
                {
                    "symbol": "BTC/USDT:USDT",
                    "exchange": "binanceusdm",
                    "side": "long",
                    "status": "open",
                    "notional_usdt": 30.0,
                    "price": 100.1,
                },
                {
                    "symbol": "BTC/USDT:USDT",
                    "exchange": "okx",
                    "side": "short",
                    "status": "open",
                    "notional_usdt": 30.0,
                    "price": 100.3,
                },
            ],
            "net_exposure": {
                "total_usdt": 1.25,
                "by_symbol": [{"symbol": "BTC/USDT:USDT", "net_exposure_usdt": 1.25}],
            },
            "pnl": {
                "estimated_usdt": 0.0,
                "actual_usdt": 0.8,
                "funding_usdt": 0.3,
                "spread_usdt": 0.5,
                "fee_usdt": 0.2,
            },
        }


def snapshot(symbol, *, last, bid, ask, funding_rate, quote_volume=1_000_000, mark_price=None):
    return {
        "symbol": symbol,
        "last": last,
        "bid": bid,
        "ask": ask,
        "mark_price": mark_price or last,
        "index_price": last,
        "funding_rate": funding_rate,
        "next_funding_time": 1_800_000_000_000,
        "quote_volume": quote_volume,
    }


def test_public_data_summary_builds_ranked_opportunities_without_binance_secret(monkeypatch):
    symbol_btc = "BTC/USDT:USDT"
    symbol_eth = "ETH/USDT:USDT"
    provider = StaticArbitrageProvider(
        okx={
            symbol_btc: snapshot(symbol_btc, last=100.4, bid=100.3, ask=100.5, funding_rate=0.0024),
            symbol_eth: snapshot(symbol_eth, last=50.0, bid=49.9, ask=50.1, funding_rate=-0.0025),
        },
        binance={
            symbol_btc: snapshot(symbol_btc, last=100.0, bid=99.9, ask=100.1, funding_rate=-0.0002),
            symbol_eth: snapshot(symbol_eth, last=50.5, bid=50.4, ask=50.6, funding_rate=0.0018),
        },
        depth={
            ("binanceusdm", symbol_btc, "ask"): 260_000,
            ("okx", symbol_btc, "bid"): 280_000,
            ("okx", symbol_eth, "ask"): 180_000,
            ("binanceusdm", symbol_eth, "bid"): 190_000,
        },
    )
    service = ArbitrageDomainService(provider=provider, top_n=30)
    monkeypatch.setattr("app.domain.arbitrage.service.settings.BINANCE_API_KEY", "", raising=False)
    monkeypatch.setattr("app.domain.arbitrage.service.settings.BINANCE_API_SECRET", "", raising=False)

    summary = asyncio.run(service.summary())

    assert summary["status"] == "ready"
    assert summary["configured_exchanges"][1]["readiness"] == "public_only"
    assert [row["symbol"] for row in summary["funding_rankings"]] == [symbol_eth, symbol_btc]
    assert [row["symbol"] for row in summary["opportunities"]] == [symbol_eth, symbol_btc]

    eth_opportunity = summary["opportunities"][0]
    assert eth_opportunity["long_leg"]["exchange"] == "okx"
    assert eth_opportunity["short_leg"]["exchange"] == "binanceusdm"
    assert eth_opportunity["fee_bps"] == pytest.approx(19.0)
    assert eth_opportunity["funding_edge_bps"] > eth_opportunity["fee_bps"]
    assert eth_opportunity["depth_usdt"] == 180_000
    assert eth_opportunity["net_edge_bps"] > summary["opportunities"][1]["net_edge_bps"]

    spread_symbols = {row["symbol"] for row in summary["spread_matrix"]}
    assert {symbol_btc, symbol_eth}.issubset(spread_symbols)


def test_public_data_summary_refuses_opportunity_when_depth_is_missing():
    symbol = "BTC/USDT:USDT"
    provider = StaticArbitrageProvider(
        okx={symbol: snapshot(symbol, last=100.4, bid=100.3, ask=100.5, funding_rate=0.003)},
        binance={symbol: snapshot(symbol, last=100.0, bid=99.9, ask=100.1, funding_rate=-0.0004)},
        depth={},
    )
    service = ArbitrageDomainService(provider=provider, top_n=30)

    summary = asyncio.run(service.summary())

    assert summary["status"] == "ready"
    assert summary["funding_rankings"]
    assert summary["opportunities"] == []
    assert "盘口深度" in summary["empty_reason"]


def test_public_data_summary_projects_low_turnover_funding_basis_carry():
    symbol = "BTC/USDT:USDT"
    provider = StaticArbitrageProvider(
        okx={symbol: snapshot(symbol, last=100.1, bid=100.1, ask=100.2, funding_rate=0.0004)},
        binance={symbol: snapshot(symbol, last=100.0, bid=99.95, ask=100.05, funding_rate=0.0)},
        depth={
            ("binanceusdm", symbol, "ask"): 260_000,
            ("okx", symbol, "bid"): 280_000,
        },
    )
    service = ArbitrageDomainService(provider=provider, top_n=30)

    summary = asyncio.run(
        service.summary(
            expected_funding_events=8,
            min_net_edge_bps=6,
            edge_filter_field="carry_net_edge_bps",
            basis_credit_ratio=0.5,
            max_basis_credit_bps=12,
            strategy_type="funding_basis_carry",
        )
    )

    assert summary["status"] == "ready"
    assert [row["symbol"] for row in summary["opportunities"]] == [symbol]
    opportunity = summary["opportunities"][0]
    assert opportunity["strategy_type"] == "funding_basis_carry"
    assert opportunity["expected_funding_events"] == 8
    assert opportunity["funding_edge_bps"] == pytest.approx(4.0)
    assert opportunity["projected_funding_edge_bps"] == pytest.approx(32.0)
    assert opportunity["net_edge_bps"] < 0
    assert opportunity["carry_net_edge_bps"] >= 6
    assert "低换手" in opportunity["reason"]


def test_public_data_summary_sorts_carry_by_projected_edge_field():
    symbol_btc = "BTC/USDT:USDT"
    symbol_eth = "ETH/USDT:USDT"
    provider = StaticArbitrageProvider(
        okx={
            symbol_btc: snapshot(symbol_btc, last=100.1, bid=100.1, ask=100.2, funding_rate=0.0004),
            symbol_eth: snapshot(symbol_eth, last=100.5, bid=100.5, ask=100.6, funding_rate=0.00025),
        },
        binance={
            symbol_btc: snapshot(symbol_btc, last=100.0, bid=99.95, ask=100.05, funding_rate=0.0),
            symbol_eth: snapshot(symbol_eth, last=100.0, bid=99.95, ask=100.05, funding_rate=0.0),
        },
        depth={
            ("binanceusdm", symbol_btc, "ask"): 260_000,
            ("okx", symbol_btc, "bid"): 280_000,
            ("binanceusdm", symbol_eth, "ask"): 260_000,
            ("okx", symbol_eth, "bid"): 280_000,
        },
    )
    service = ArbitrageDomainService(provider=provider, top_n=30)

    summary = asyncio.run(
        service.summary(
            expected_funding_events=8,
            min_net_edge_bps=6,
            edge_filter_field="carry_net_edge_bps",
            basis_credit_ratio=0.5,
            max_basis_credit_bps=12,
            strategy_type="funding_basis_carry",
        )
    )

    assert [row["symbol"] for row in summary["opportunities"]] == [symbol_btc, symbol_eth]
    assert summary["opportunities"][0]["carry_net_edge_bps"] > summary["opportunities"][1]["carry_net_edge_bps"]
    assert summary["opportunities"][0]["net_edge_bps"] < summary["opportunities"][1]["net_edge_bps"]


def test_public_data_summary_reports_waiting_state_when_dual_exchange_data_is_missing():
    symbol = "BTC/USDT:USDT"
    provider = StaticArbitrageProvider(
        okx={symbol: snapshot(symbol, last=100.4, bid=100.3, ask=100.5, funding_rate=0.003)},
        binance={},
    )
    service = ArbitrageDomainService(provider=provider, top_n=30)

    summary = asyncio.run(service.summary())

    assert summary["status"] == "waiting_for_data"
    assert summary["opportunities"] == []
    assert summary["spread_matrix"] == []
    assert summary["funding_rankings"] == []
    assert "双交易所" in summary["empty_reason"]


def test_public_okx_snapshot_keeps_zero_funding_rate_as_real_data():
    merged = PublicArbitrageSnapshotProvider._merge_snapshot(
        "okx",
        "BTC/USDT:USDT",
        {"last": 100.0, "bid": 99.9, "ask": 100.1, "quote_volume": 1_000_000},
        {"current_rate": 0.0, "next_funding_time": 1_800_000_000_000},
    )

    assert merged["funding_rate"] == 0.0


def test_summary_includes_cross_exchange_paper_portfolio_state():
    symbol = "BTC/USDT:USDT"
    provider = StaticArbitrageProvider(
        okx={symbol: snapshot(symbol, last=100.4, bid=100.3, ask=100.5, funding_rate=0.0024)},
        binance={symbol: snapshot(symbol, last=100.0, bid=99.9, ask=100.1, funding_rate=-0.0002)},
        depth={
            ("binanceusdm", symbol, "ask"): 260_000,
            ("okx", symbol, "bid"): 280_000,
        },
    )
    service = ArbitrageDomainService(
        provider=provider,
        portfolio_provider=StaticPortfolioProvider(),
        top_n=30,
    )

    summary = asyncio.run(service.summary())

    assert summary["portfolio_positions"][0]["symbol"] == symbol
    assert summary["leg_status"][0]["exchange"] == "binanceusdm"
    assert summary["net_exposure"]["total_usdt"] == pytest.approx(1.25)
    assert summary["pnl"]["actual_usdt"] == pytest.approx(0.8)


def test_cross_exchange_paper_portfolio_tracks_two_leg_summary():
    portfolio = CrossExchangePaperPortfolio(initial_capital=100, leverage=3, slippage_bps=5)

    result = portfolio.open_pair(
        symbol="BTC/USDT:USDT",
        long_leg={"exchange": "binanceusdm", "price": 100.1, "funding_rate": -0.0002},
        short_leg={"exchange": "okx", "price": 100.3, "funding_rate": 0.0024},
        notional_usdt=30,
        leverage=3,
        net_edge_bps=12.0,
        funding_edge_bps=26.0,
    )
    portfolio.update_leg_mark("BTC/USDT:USDT", "binanceusdm", 100.4)
    portfolio.update_leg_mark("BTC/USDT:USDT", "okx", 100.2)

    summary = portfolio.summary()

    assert result["status"] == "filled"
    assert len(summary["portfolio_positions"]) == 1
    assert len(summary["leg_status"]) == 2
    assert summary["portfolio_positions"][0]["long_exchange"] == "binanceusdm"
    assert summary["portfolio_positions"][0]["short_exchange"] == "okx"
    assert summary["pnl"]["fee_usdt"] == pytest.approx(0.0285)
