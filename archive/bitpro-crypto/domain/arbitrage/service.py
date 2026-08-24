from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

from app.core.config import settings
from app.domain.funding.service import funding_domain_service
from app.domain.market.service import market_domain_service
from app.exchange.binance_usdm import BinanceUsdmPublicClient
from app.services.cross_exchange_paper_account import cross_exchange_paper_registry
from app.services.exchange_fee_model import market_order_fee_bps


DEFAULT_CANDIDATE_SYMBOLS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "XRP/USDT:USDT",
    "DOGE/USDT:USDT",
    "BNB/USDT:USDT",
    "ADA/USDT:USDT",
    "LINK/USDT:USDT",
    "AVAX/USDT:USDT",
    "LTC/USDT:USDT",
    "BCH/USDT:USDT",
    "DOT/USDT:USDT",
    "TRX/USDT:USDT",
    "UNI/USDT:USDT",
    "AAVE/USDT:USDT",
    "FIL/USDT:USDT",
    "ETC/USDT:USDT",
    "NEAR/USDT:USDT",
    "OP/USDT:USDT",
    "ARB/USDT:USDT",
    "SUI/USDT:USDT",
    "WLD/USDT:USDT",
    "INJ/USDT:USDT",
    "PEPE/USDT:USDT",
    "SHIB/USDT:USDT",
    "APT/USDT:USDT",
    "HBAR/USDT:USDT",
    "ICP/USDT:USDT",
    "ATOM/USDT:USDT",
    "SEI/USDT:USDT",
    "TIA/USDT:USDT",
    "LDO/USDT:USDT",
    "CRV/USDT:USDT",
    "TON/USDT:USDT",
    "TAO/USDT:USDT",
    "ENA/USDT:USDT",
    "JUP/USDT:USDT",
    "ORDI/USDT:USDT",
    "BONK/USDT:USDT",
    "FLOKI/USDT:USDT",
    "GALA/USDT:USDT",
    "MKR/USDT:USDT",
    "COMP/USDT:USDT",
    "SAND/USDT:USDT",
    "APE/USDT:USDT",
    "AXS/USDT:USDT",
    "DYDX/USDT:USDT",
    "RUNE/USDT:USDT",
    "EIGEN/USDT:USDT",
    "PENDLE/USDT:USDT",
    "ONDO/USDT:USDT",
    "WIF/USDT:USDT",
    "JTO/USDT:USDT",
]


class ArbitrageSnapshotProvider(Protocol):
    async def get_okx_snapshots(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        ...

    async def get_binance_snapshots(self) -> Dict[str, Dict[str, Any]]:
        ...

    async def get_depth_usdt(self, exchange: str, symbol: str, side: str, limit: int = 20) -> Optional[float]:
        ...


class PublicArbitrageSnapshotProvider:
    """Loads public OKX and Binance USD-M market/funding snapshots."""

    def __init__(self, binance_client: Optional[BinanceUsdmPublicClient] = None):
        self.binance_client = binance_client or BinanceUsdmPublicClient()

    async def get_okx_snapshots(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        tickers_task = market_domain_service.get_tickers("okx", symbols)
        funding_task = funding_domain_service.get_funding_rates("okx", symbols)
        tickers, rates = await asyncio.gather(tickers_task, funding_task)

        by_symbol = {str(row.get("symbol")): row for row in tickers if row.get("symbol")}
        funding_by_symbol = {str(row.get("symbol")): row for row in rates if row.get("symbol")}
        snapshots: Dict[str, Dict[str, Any]] = {}
        for symbol in symbols:
            ticker = by_symbol.get(symbol)
            if not ticker:
                continue
            funding = funding_by_symbol.get(symbol, {})
            snapshots[symbol] = self._merge_snapshot("okx", symbol, ticker, funding)
        return snapshots

    async def get_binance_snapshots(self) -> Dict[str, Dict[str, Any]]:
        return await self.binance_client.fetch_snapshots()

    async def get_depth_usdt(self, exchange: str, symbol: str, side: str, limit: int = 20) -> Optional[float]:
        try:
            if exchange == "okx":
                book = await market_domain_service.get_orderbook("okx", symbol, limit)
            elif exchange == "binanceusdm":
                book = await self.binance_client.fetch_orderbook(symbol, limit)
            else:
                return None
        except Exception:
            return None
        return orderbook_depth_usdt(book, side)

    @classmethod
    def _merge_snapshot(
        cls,
        exchange: str,
        symbol: str,
        ticker: Dict[str, Any],
        funding: Dict[str, Any],
    ) -> Dict[str, Any]:
        last = finite_float(ticker.get("last"))
        mark_price = first_finite_float(
            ticker.get("mark_price"),
            ticker.get("markPrice"),
            funding.get("mark_price"),
            funding.get("markPrice"),
        )
        return {
            "exchange": exchange,
            "symbol": symbol,
            "last": last,
            "bid": finite_float(ticker.get("bid")),
            "ask": finite_float(ticker.get("ask")),
            "mark_price": mark_price or last,
            "index_price": first_finite_float(funding.get("index_price"), funding.get("indexPrice")),
            "funding_rate": first_finite_float(funding.get("current_rate"), funding.get("funding_rate")),
            "next_funding_time": funding.get("next_funding_time"),
            "quote_volume": first_finite_float(ticker.get("quote_volume"), ticker.get("quoteVolume")),
            "timestamp": ticker.get("timestamp"),
        }


class ArbitrageDomainService:
    """Read-only cross-exchange arbitrage research facade."""

    def __init__(
        self,
        provider: Optional[ArbitrageSnapshotProvider] = None,
        portfolio_provider: Optional[Any] = None,
        *,
        top_n: int = 30,
        min_net_edge_bps: float = 6.0,
        taker_fee_bps: Optional[float] = None,
        slippage_bps: float = 4.0,
        min_depth_usdt: float = 50_000.0,
    ):
        self.provider = provider or PublicArbitrageSnapshotProvider()
        self.portfolio_provider = portfolio_provider or cross_exchange_paper_registry
        self.top_n = max(1, int(top_n))
        self.min_net_edge_bps = float(min_net_edge_bps)
        self.taker_fee_bps = float(taker_fee_bps) if taker_fee_bps is not None else None
        self.slippage_bps = float(slippage_bps)
        self.min_depth_usdt = float(min_depth_usdt)

    async def summary(
        self,
        *,
        expected_funding_events: int = 1,
        min_net_edge_bps: Optional[float] = None,
        edge_filter_field: str = "net_edge_bps",
        basis_credit_ratio: float = 1.0,
        max_basis_credit_bps: Optional[float] = None,
        strategy_type: str = "funding_spread",
        min_depth_usdt: Optional[float] = None,
        top_n: Optional[int] = None,
    ) -> Dict[str, Any]:
        scan_top_n = max(1, int(top_n or self.top_n))
        expected_events = max(1, int(expected_funding_events or 1))
        min_edge = float(self.min_net_edge_bps if min_net_edge_bps is None else min_net_edge_bps)
        filter_field = str(edge_filter_field or "net_edge_bps")
        depth_floor = float(self.min_depth_usdt if min_depth_usdt is None else min_depth_usdt)
        warnings: List[str] = []
        okx_snapshots: Dict[str, Dict[str, Any]] = {}
        binance_snapshots: Dict[str, Dict[str, Any]] = {}

        try:
            okx_snapshots, binance_snapshots = await asyncio.gather(
                self.provider.get_okx_snapshots(DEFAULT_CANDIDATE_SYMBOLS),
                self.provider.get_binance_snapshots(),
            )
        except Exception as exc:
            warnings.append(f"公开行情读取失败: {exc}")

        universe = self._rank_common_universe(okx_snapshots, binance_snapshots, top_n=scan_top_n)
        if not universe:
            return self._with_portfolio_summary(
                self._base_summary(
                    status="waiting_for_data",
                    empty_reason="缺少 OKX 与 Binance USD-M 双交易所共同标的的公开行情/资金费率数据",
                    warnings=warnings,
                )
            )

        spread_matrix = [self._spread_row(symbol, okx_snapshots[symbol], binance_snapshots[symbol]) for symbol in universe]
        spread_matrix.sort(key=lambda row: abs(row.get("basis_bps") or 0.0), reverse=True)

        funding_rankings = [
            self._funding_row(symbol, okx_snapshots[symbol], binance_snapshots[symbol])
            for symbol in universe
            if self._has_funding(okx_snapshots[symbol]) and self._has_funding(binance_snapshots[symbol])
        ]
        funding_rankings.sort(key=lambda row: abs(row.get("spread_bps") or 0.0), reverse=True)

        opportunities = await self._build_opportunities(
            universe,
            okx_snapshots,
            binance_snapshots,
            spread_matrix,
            expected_funding_events=expected_events,
            min_net_edge_bps=min_edge,
            edge_filter_field=filter_field,
            basis_credit_ratio=basis_credit_ratio,
            max_basis_credit_bps=max_basis_credit_bps,
            strategy_type=strategy_type,
            min_depth_usdt=depth_floor,
        )
        opportunities.sort(
            key=lambda row: row.get(filter_field) or row.get("net_edge_bps") or 0.0,
            reverse=True,
        )

        empty_reason = ""
        if not opportunities:
            if funding_rankings:
                empty_reason = "当前 Top30 双交易所候选的净优势未同时覆盖手续费、滑点和盘口深度要求"
            else:
                empty_reason = "等待 OKX 与 Binance USD-M 同步真实资金费率后生成跨所套利机会"

        pnl_estimated = sum(max(0.0, (row.get("net_edge_bps") or 0.0) / 10_000.0 * 100.0) for row in opportunities[:2])
        summary = {
            **self._base_summary(
                status="ready",
                empty_reason=empty_reason,
                warnings=warnings,
            ),
            "opportunities": opportunities[:10],
            "spread_matrix": spread_matrix[: self.top_n],
            "funding_rankings": funding_rankings[: self.top_n],
            "pnl": {
                "estimated_usdt": round(pnl_estimated, 4),
                "actual_usdt": 0.0,
                "funding_usdt": 0.0,
                "spread_usdt": 0.0,
                "fee_usdt": 0.0,
            },
        }
        return self._with_portfolio_summary(summary, estimated_usdt=round(pnl_estimated, 4))

    def _base_summary(self, *, status: str, empty_reason: str, warnings: Optional[List[str]] = None) -> Dict[str, Any]:
        binance_key = bool(settings.BINANCE_API_KEY)
        binance_secret = bool(settings.BINANCE_API_SECRET)
        binance_readiness = "configured" if binance_key and binance_secret else "display_only" if binance_key else "public_only"
        return {
            "status": status,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "configured_exchanges": [
                {
                    "exchange": "okx",
                    "label": "OKX",
                    "configured": bool(settings.OKX_API_KEY and settings.OKX_API_SECRET),
                    "readiness": "configured" if settings.OKX_API_KEY and settings.OKX_API_SECRET else "public_only",
                },
                {
                    "exchange": "binanceusdm",
                    "label": "Binance USD-M",
                    "configured": bool(binance_key and binance_secret),
                    "display_only": bool(binance_key and not binance_secret),
                    "readiness": binance_readiness,
                },
            ],
            "opportunities": [],
            "spread_matrix": [],
            "funding_rankings": [],
            "portfolio_positions": [],
            "leg_status": [],
            "net_exposure": {"total_usdt": 0.0, "by_symbol": []},
            "pnl": {
                "estimated_usdt": 0.0,
                "actual_usdt": 0.0,
                "funding_usdt": 0.0,
                "spread_usdt": 0.0,
                "fee_usdt": 0.0,
            },
            "warnings": warnings or [],
            "empty_reason": empty_reason,
        }

    def _with_portfolio_summary(
        self,
        summary: Dict[str, Any],
        *,
        estimated_usdt: Optional[float] = None,
    ) -> Dict[str, Any]:
        provider = self.portfolio_provider
        if provider is None or not hasattr(provider, "summary"):
            return summary
        try:
            portfolio = provider.summary()
        except Exception as exc:
            warnings = summary.setdefault("warnings", [])
            if isinstance(warnings, list):
                warnings.append(f"跨所模拟组合读取失败: {exc}")
            return summary
        if not isinstance(portfolio, dict):
            return summary

        summary["portfolio_positions"] = list(portfolio.get("portfolio_positions") or [])
        summary["leg_status"] = list(portfolio.get("leg_status") or [])
        net_exposure = portfolio.get("net_exposure")
        if isinstance(net_exposure, dict):
            summary["net_exposure"] = net_exposure
        portfolio_pnl = portfolio.get("pnl")
        if isinstance(portfolio_pnl, dict):
            merged_pnl = dict(summary.get("pnl") or {})
            merged_pnl.update(portfolio_pnl)
            if estimated_usdt is not None:
                merged_pnl["estimated_usdt"] = estimated_usdt
            summary["pnl"] = merged_pnl
        elif estimated_usdt is not None:
            summary.setdefault("pnl", {})["estimated_usdt"] = estimated_usdt
        return summary

    def _rank_common_universe(
        self,
        okx_snapshots: Dict[str, Dict[str, Any]],
        binance_snapshots: Dict[str, Dict[str, Any]],
        *,
        top_n: Optional[int] = None,
    ) -> List[str]:
        common = [symbol for symbol in DEFAULT_CANDIDATE_SYMBOLS if symbol in okx_snapshots and symbol in binance_snapshots]
        common.sort(
            key=lambda symbol: min(
                positive_float(okx_snapshots[symbol].get("quote_volume")),
                positive_float(binance_snapshots[symbol].get("quote_volume")),
            ),
            reverse=True,
        )
        return common[: max(1, int(top_n or self.top_n))]

    async def _build_opportunities(
        self,
        universe: List[str],
        okx_snapshots: Dict[str, Dict[str, Any]],
        binance_snapshots: Dict[str, Dict[str, Any]],
        spread_rows: List[Dict[str, Any]],
        *,
        expected_funding_events: int = 1,
        min_net_edge_bps: Optional[float] = None,
        edge_filter_field: str = "net_edge_bps",
        basis_credit_ratio: float = 1.0,
        max_basis_credit_bps: Optional[float] = None,
        strategy_type: str = "funding_spread",
        min_depth_usdt: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        spread_by_symbol = {row["symbol"]: row for row in spread_rows}
        expected_events = max(1, int(expected_funding_events or 1))
        min_edge = float(self.min_net_edge_bps if min_net_edge_bps is None else min_net_edge_bps)
        filter_field = str(edge_filter_field or "net_edge_bps")
        depth_floor = float(self.min_depth_usdt if min_depth_usdt is None else min_depth_usdt)
        strategy_label = str(strategy_type or "funding_spread")
        candidates: List[Dict[str, Any]] = []
        for symbol in universe:
            okx = okx_snapshots[symbol]
            binance = binance_snapshots[symbol]
            if not self._has_funding(okx) or not self._has_funding(binance):
                continue

            direction = self._direction(symbol, okx, binance)
            if not direction:
                continue

            funding_edge_bps = direction["funding_edge_bps"]
            long_price = positive_float(direction["long_leg"].get("price"))
            short_price = positive_float(direction["short_leg"].get("price"))
            mid = (long_price + short_price) / 2.0 if long_price > 0 and short_price > 0 else 0.0
            basis_edge_bps = (short_price - long_price) / mid * 10_000.0 if mid > 0 else 0.0
            gross_edge_bps = funding_edge_bps + basis_edge_bps
            entry_fee_bps = self._entry_fee_bps(direction)
            fee_bps = entry_fee_bps * 2.0
            net_edge_without_depth = gross_edge_bps - fee_bps - self.slippage_bps
            basis_credit_bps = self._carry_basis_component(
                basis_edge_bps,
                ratio=basis_credit_ratio,
                max_credit_bps=max_basis_credit_bps,
            )
            projected_funding_edge_bps = funding_edge_bps * expected_events
            carry_gross_edge_bps = projected_funding_edge_bps + basis_credit_bps
            carry_net_edge_without_depth = carry_gross_edge_bps - fee_bps - self.slippage_bps
            filter_edge_without_depth = (
                carry_net_edge_without_depth
                if filter_field == "carry_net_edge_bps"
                else net_edge_without_depth
            )
            if filter_edge_without_depth < min_edge:
                continue

            candidates.append(
                {
                    "symbol": symbol,
                    "direction": direction,
                    "basis_edge_bps": basis_edge_bps,
                    "gross_edge_bps": gross_edge_bps,
                    "carry_gross_edge_bps": carry_gross_edge_bps,
                    "basis_credit_bps": basis_credit_bps,
                    "projected_funding_edge_bps": projected_funding_edge_bps,
                    "fee_bps": fee_bps,
                    "entry_fee_bps": entry_fee_bps,
                    "spread_row": spread_by_symbol.get(symbol, {}),
                }
            )

        depth_tasks = [self._depth_for_candidate(candidate) for candidate in candidates]
        depths = await asyncio.gather(*depth_tasks) if depth_tasks else []
        opportunities: List[Dict[str, Any]] = []
        for candidate, depth_usdt in zip(candidates, depths):
            if depth_usdt is None or depth_usdt < depth_floor:
                continue
            direction = candidate["direction"]
            net_edge_bps = candidate["gross_edge_bps"] - candidate["fee_bps"] - self.slippage_bps
            carry_net_edge_bps = candidate["carry_gross_edge_bps"] - candidate["fee_bps"] - self.slippage_bps
            filter_edge = carry_net_edge_bps if filter_field == "carry_net_edge_bps" else net_edge_bps
            if filter_edge < min_edge:
                continue
            reason = "资金费率差在扣除公开行情、手续费、滑点和盘口深度后仍为正"
            if strategy_label == "funding_basis_carry":
                reason = "低换手多周期 funding carry 与基差信用在扣除成本和深度后仍有净优势"
            opportunities.append(
                {
                    "symbol": candidate["symbol"],
                    "strategy_type": strategy_label,
                    "long_leg": direction["long_leg"],
                    "short_leg": direction["short_leg"],
                    "gross_edge_bps": round(candidate["gross_edge_bps"], 4),
                    "carry_gross_edge_bps": round(candidate["carry_gross_edge_bps"], 4),
                    "fee_bps": round(candidate["fee_bps"], 4),
                    "entry_fee_bps": round(candidate["entry_fee_bps"], 4),
                    "exit_fee_bps": round(candidate["entry_fee_bps"], 4),
                    "slippage_bps": round(self.slippage_bps, 4),
                    "funding_edge_bps": round(direction["funding_edge_bps"], 4),
                    "projected_funding_edge_bps": round(candidate["projected_funding_edge_bps"], 4),
                    "basis_edge_bps": round(candidate["basis_edge_bps"], 4),
                    "basis_credit_bps": round(candidate["basis_credit_bps"], 4),
                    "net_edge_bps": round(net_edge_bps, 4),
                    "carry_net_edge_bps": round(carry_net_edge_bps, 4),
                    "expected_funding_events": expected_events,
                    "depth_usdt": round(depth_usdt, 4),
                    "estimated_margin_usdt": 20.0,
                    "reason": reason,
                }
            )
        return opportunities

    async def _depth_for_candidate(self, candidate: Dict[str, Any]) -> Optional[float]:
        direction = candidate["direction"]
        long_leg = direction["long_leg"]
        short_leg = direction["short_leg"]
        long_depth, short_depth = await asyncio.gather(
            self.provider.get_depth_usdt(long_leg["exchange"], candidate["symbol"], "ask", 20),
            self.provider.get_depth_usdt(short_leg["exchange"], candidate["symbol"], "bid", 20),
        )
        if long_depth is None or short_depth is None:
            return None
        return min(float(long_depth), float(short_depth))

    def _entry_fee_bps(self, direction: Dict[str, Any]) -> float:
        if self.taker_fee_bps is not None:
            return self.taker_fee_bps * 2.0
        return market_order_fee_bps(direction["long_leg"]["exchange"], "swap") + market_order_fee_bps(
            direction["short_leg"]["exchange"],
            "swap",
        )

    @staticmethod
    def _carry_basis_component(
        basis_edge_bps: float,
        *,
        ratio: float,
        max_credit_bps: Optional[float],
    ) -> float:
        component = float(basis_edge_bps or 0.0) * max(0.0, float(ratio or 0.0))
        if max_basis := max_credit_bps:
            cap = abs(float(max_basis))
            if cap > 0:
                return max(-cap, min(cap, component))
        return component

    @staticmethod
    def _direction(symbol: str, okx: Dict[str, Any], binance: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        okx_rate = finite_float(okx.get("funding_rate"))
        binance_rate = finite_float(binance.get("funding_rate"))
        if okx_rate is None or binance_rate is None or abs(okx_rate - binance_rate) <= 1e-12:
            return None
        high_exchange, high_snapshot, high_rate = ("okx", okx, okx_rate)
        low_exchange, low_snapshot, low_rate = ("binanceusdm", binance, binance_rate)
        if binance_rate > okx_rate:
            high_exchange, high_snapshot, high_rate = ("binanceusdm", binance, binance_rate)
            low_exchange, low_snapshot, low_rate = ("okx", okx, okx_rate)
        return {
            "funding_edge_bps": (high_rate - low_rate) * 10_000.0,
            "long_leg": {
                "exchange": low_exchange,
                "side": "long",
                "price": best_entry_price(low_snapshot, "long"),
                "funding_rate": low_rate,
            },
            "short_leg": {
                "exchange": high_exchange,
                "side": "short",
                "price": best_entry_price(high_snapshot, "short"),
                "funding_rate": high_rate,
            },
        }

    @staticmethod
    def _spread_row(symbol: str, okx: Dict[str, Any], binance: Dict[str, Any]) -> Dict[str, Any]:
        okx_price = best_reference_price(okx)
        binance_price = best_reference_price(binance)
        mid = (okx_price + binance_price) / 2.0 if okx_price > 0 and binance_price > 0 else 0.0
        basis_bps = (okx_price - binance_price) / mid * 10_000.0 if mid > 0 else 0.0
        return {
            "symbol": symbol,
            "okx_mark_price": round(okx_price, 10),
            "binance_mark_price": round(binance_price, 10),
            "okx_bid": finite_float(okx.get("bid")),
            "okx_ask": finite_float(okx.get("ask")),
            "binance_bid": finite_float(binance.get("bid")),
            "binance_ask": finite_float(binance.get("ask")),
            "basis_bps": round(basis_bps, 4),
        }

    @staticmethod
    def _funding_row(symbol: str, okx: Dict[str, Any], binance: Dict[str, Any]) -> Dict[str, Any]:
        okx_rate = finite_float(okx.get("funding_rate")) or 0.0
        binance_rate = finite_float(binance.get("funding_rate")) or 0.0
        spread_bps = (okx_rate - binance_rate) * 10_000.0
        return {
            "symbol": symbol,
            "okx_funding_rate": okx_rate,
            "binance_funding_rate": binance_rate,
            "spread_bps": round(spread_bps, 4),
            "annualized_spread_pct": round(spread_bps / 10_000.0 * 3 * 365 * 100, 4),
            "next_funding_time": okx.get("next_funding_time") or binance.get("next_funding_time"),
        }

    @staticmethod
    def _has_funding(snapshot: Dict[str, Any]) -> bool:
        return finite_float(snapshot.get("funding_rate")) is not None


def orderbook_depth_usdt(book: Dict[str, Any], side: str) -> Optional[float]:
    levels = book.get("asks") if side == "ask" else book.get("bids")
    if not isinstance(levels, list):
        return None
    total = 0.0
    for level in levels[:20]:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        price = positive_float(level[0])
        amount = positive_float(level[1])
        total += price * amount
    return total if total > 0 else None


def best_reference_price(snapshot: Dict[str, Any]) -> float:
    return positive_float(snapshot.get("mark_price")) or positive_float(snapshot.get("last"))


def best_entry_price(snapshot: Dict[str, Any], side: str) -> float:
    if side == "long":
        return positive_float(snapshot.get("ask")) or best_reference_price(snapshot)
    return positive_float(snapshot.get("bid")) or best_reference_price(snapshot)


def positive_float(value: Any) -> float:
    out = finite_float(value)
    return out if out is not None and out > 0 else 0.0


def finite_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def first_finite_float(*values: Any) -> Optional[float]:
    for value in values:
        out = finite_float(value)
        if out is not None:
            return out
    return None


arbitrage_domain_service = ArbitrageDomainService()
