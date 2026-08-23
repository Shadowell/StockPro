import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.execution.base_strategy import BarData
from app.strategies.dynamic_cta_selector import (
    DynamicCtaConfig,
    DynamicCtaSelector,
    MarketSnapshot,
)


BASE_TS = 1_800_000_000_000
TF_MS = 15 * 60 * 1000


def _snapshot(symbol: str, volume: float, last: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        quote_volume_24h=volume,
        bid=last * 0.9995,
        ask=last * 1.0005,
        last=last,
        funding_rate=0.0001,
        open_interest_usdt=volume * 0.25,
        active=True,
    )


def _bars(symbol: str, *, start: float = 100.0, step: float = 0.05, count: int = 3000) -> list[BarData]:
    bars: list[BarData] = []
    price = start
    for idx in range(count):
        open_price = price
        close_price = max(0.01, open_price + step)
        high = max(open_price, close_price) * 1.002
        low = min(open_price, close_price) * 0.998
        bars.append(
            BarData(
                exchange="okx",
                symbol=symbol,
                timeframe="15m",
                timestamp=BASE_TS + idx * TF_MS,
                open=open_price,
                high=high,
                low=low,
                close=close_price,
                volume=1000.0,
            )
        )
        price = close_price
    return bars


def _copy_bar_with_timestamp(bar: BarData, timestamp: int) -> BarData:
    return BarData(
        exchange=bar.exchange,
        symbol=bar.symbol,
        timeframe=bar.timeframe,
        timestamp=timestamp,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
    )


def test_duplicate_timestamp_history_is_blocked_from_openable_symbols() -> None:
    symbol = "DUP/USDT:USDT"
    bars = _bars(symbol, step=0.25, count=2880)
    bars = [
        BarData(
            exchange=bar.exchange,
            symbol=bar.symbol,
            timeframe=bar.timeframe,
            timestamp=BASE_TS,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        for bar in bars
    ]

    selector = DynamicCtaSelector(DynamicCtaConfig(min_entry_score=0.0))
    result = selector.select(
        [_snapshot(symbol, 3000)],
        {symbol: bars},
        open_positions=[],
        now_ms=BASE_TS + 2880 * TF_MS,
    )

    row = result.row_by_symbol[symbol]
    assert row.blocked_reason == "insufficient_history"
    assert symbol not in result.openable_symbols


def test_stale_but_continuous_history_is_blocked_from_openable_symbols() -> None:
    symbol = "STALE-HISTORY/USDT:USDT"
    bars = _bars(symbol, step=0.25, count=2880)
    now_ms = bars[-1].timestamp + 60 * 24 * 60 * 60 * 1000

    selector = DynamicCtaSelector(DynamicCtaConfig(min_entry_score=0.0))
    result = selector.select(
        [_snapshot(symbol, 3000)],
        {symbol: bars},
        open_positions=[],
        now_ms=now_ms,
    )

    row = result.row_by_symbol[symbol]
    assert row.blocked_reason == "insufficient_history"
    assert row.eligible is False
    assert "insufficient_history" in row.reasons
    assert symbol not in result.openable_symbols


def test_gapped_or_unsorted_history_is_blocked_from_openable_symbols() -> None:
    gapped = "GAPPED/USDT:USDT"
    unsorted = "UNSORTED/USDT:USDT"
    gapped_bars = _bars(gapped, step=0.25, count=2880)
    gapped_bars[200] = BarData(
        exchange=gapped_bars[200].exchange,
        symbol=gapped_bars[200].symbol,
        timeframe=gapped_bars[200].timeframe,
        timestamp=gapped_bars[199].timestamp + TF_MS * 4,
        open=gapped_bars[200].open,
        high=gapped_bars[200].high,
        low=gapped_bars[200].low,
        close=gapped_bars[200].close,
        volume=gapped_bars[200].volume,
    )
    unsorted_bars = _bars(unsorted, step=0.25, count=2880)
    unsorted_bars[100], unsorted_bars[101] = unsorted_bars[101], unsorted_bars[100]

    selector = DynamicCtaSelector(DynamicCtaConfig(min_entry_score=0.0))
    result = selector.select(
        [_snapshot(gapped, 3000), _snapshot(unsorted, 2900)],
        {gapped: gapped_bars, unsorted: unsorted_bars},
        open_positions=[],
        now_ms=BASE_TS + 2880 * TF_MS,
    )

    assert result.row_by_symbol[gapped].blocked_reason == "insufficient_history"
    assert result.row_by_symbol[unsorted].blocked_reason == "insufficient_history"
    assert gapped not in result.openable_symbols
    assert unsorted not in result.openable_symbols


def test_empty_required_history_windows_disables_history_gate() -> None:
    symbol = "LIGHT/USDT:USDT"
    selector = DynamicCtaSelector(
        DynamicCtaConfig(min_entry_score=0.0, required_history_windows=())
    )

    result = selector.select(
        [_snapshot(symbol, 3000)],
        {symbol: _bars(symbol, step=5.0, count=40)},
        open_positions=[],
        now_ms=BASE_TS + 40 * TF_MS,
    )

    row = result.row_by_symbol[symbol]
    assert row.blocked_reason is None
    assert symbol in result.openable_symbols


def test_required_history_windows_empty_disables_staleness_gate_too() -> None:
    symbol = "LIGHT-STALE/USDT:USDT"
    bars = _bars(symbol, step=5.0, count=40)
    selector = DynamicCtaSelector(
        DynamicCtaConfig(min_entry_score=0.0, required_history_windows=())
    )

    result = selector.select(
        [_snapshot(symbol, 3000)],
        {symbol: bars},
        open_positions=[],
        now_ms=bars[-1].timestamp + 60 * 24 * 60 * 60 * 1000,
    )

    row = result.row_by_symbol[symbol]
    assert row.blocked_reason is None
    assert row.eligible is True
    assert row.reasons == ()
    assert symbol in result.openable_symbols


def test_hour_window_history_requirement_is_supported() -> None:
    symbol = "HOUR/USDT:USDT"
    selector = DynamicCtaSelector(
        DynamicCtaConfig(
            min_entry_score=0.0,
            window_weights={"12h": 1.0},
            required_history_windows=("12h",),
        )
    )

    result = selector.select(
        [_snapshot(symbol, 3000)],
        {symbol: _bars(symbol, step=0.25, count=48)},
        open_positions=[],
        now_ms=BASE_TS + 48 * TF_MS,
    )

    assert result.row_by_symbol[symbol].blocked_reason is None
    assert symbol in result.openable_symbols


def test_market_hard_filters_run_before_liquidity_and_candidates() -> None:
    crossed = replace(_snapshot("CROSSED/USDT:USDT", 10_000), bid=101.0, ask=100.0)
    wide = replace(_snapshot("WIDE/USDT:USDT", 9_900), bid=95.0, ask=105.0)
    funded = replace(_snapshot("FUNDED/USDT:USDT", 9_800), funding_rate=0.01)
    invalid_last = replace(_snapshot("BADLAST/USDT:USDT", 9_700), last=0.0)
    inactive = replace(_snapshot("INACTIVE/USDT:USDT", 9_600), active=False)
    good = _snapshot("GOOD/USDT:USDT", 1000)
    selector = DynamicCtaSelector(DynamicCtaConfig(min_entry_score=0.0, liquidity_top_n=10))

    result = selector.select(
        [crossed, wide, funded, invalid_last, inactive, good],
        {
            snap.symbol: _bars(snap.symbol, step=0.25, count=3000)
            for snap in [crossed, wide, funded, invalid_last, inactive, good]
        },
        open_positions=[],
        now_ms=BASE_TS + 3000 * TF_MS,
    )

    assert result.liquidity_symbols == [good.symbol]
    assert result.candidate_symbols == [good.symbol]
    assert result.openable_symbols == [good.symbol]
    assert result.row_by_symbol[crossed.symbol].blocked_reason == "invalid_market_quote"
    assert result.row_by_symbol[wide.symbol].blocked_reason == "spread_too_wide"
    assert result.row_by_symbol[funded.symbol].blocked_reason == "funding_rate_too_high"
    assert result.row_by_symbol[invalid_last.symbol].blocked_reason == "invalid_market_quote"
    assert result.row_by_symbol[inactive.symbol].blocked_reason == "inactive_market"
    assert result.row_by_symbol[crossed.symbol].eligible is False
    assert "invalid_market_quote" in result.row_by_symbol[crossed.symbol].reasons


def test_hard_filtered_high_score_symbols_do_not_displace_top15_candidates() -> None:
    blocked = [
        replace(_snapshot(f"BLOCKED{i:02d}/USDT:USDT", 30_000 - i), bid=101.0, ask=100.0)
        for i in range(20)
    ]
    valid = [_snapshot(f"VALID{i:02d}/USDT:USDT", 10_000 - i) for i in range(20)]
    snapshots = blocked + valid
    histories = {
        snap.symbol: _bars(
            snap.symbol,
            start=100.0,
            step=0.8 if snap.symbol.startswith("BLOCKED") else 0.2,
            count=3000,
        )
        for snap in snapshots
    }

    selector = DynamicCtaSelector(DynamicCtaConfig(min_entry_score=0.0, liquidity_top_n=50))
    result = selector.select(
        snapshots,
        histories,
        open_positions=[],
        now_ms=BASE_TS + 3000 * TF_MS,
    )

    assert result.candidate_symbols == [snap.symbol for snap in valid[:15]]
    assert all(not symbol.startswith("BLOCKED") for symbol in result.liquidity_symbols)
    assert all(not symbol.startswith("BLOCKED") for symbol in result.openable_symbols)
    assert all(result.row_by_symbol[snap.symbol].blocked_reason == "invalid_market_quote" for snap in blocked)


def test_public_liquidity_universe_matches_selector_liquidity_scope() -> None:
    snapshots = [_snapshot(f"SYM{i:02d}/USDT:USDT", 10_000 - i) for i in range(60)]
    selector = DynamicCtaSelector(DynamicCtaConfig(min_entry_score=0.0, liquidity_top_n=10))

    liquidity = selector.liquidity_universe(snapshots)

    assert [snap.symbol for snap in liquidity] == [snap.symbol for snap in snapshots[:10]]


def test_liquidity_top50_is_scored_before_returning_top15_candidates() -> None:
    snapshots = [_snapshot(f"SYM{i:02d}/USDT:USDT", 10_000 - i) for i in range(60)]
    histories = {
        snap.symbol: _bars(snap.symbol, step=(0.25 if idx >= 50 else 0.05 + idx * 0.001))
        for idx, snap in enumerate(snapshots)
    }

    selector = DynamicCtaSelector(DynamicCtaConfig(min_entry_score=0.0))
    result = selector.select(snapshots, histories, open_positions=[], now_ms=BASE_TS + 3000 * TF_MS)

    expected_liquidity = [f"SYM{i:02d}/USDT:USDT" for i in range(50)]
    assert result.liquidity_symbols == expected_liquidity
    assert len(result.candidate_symbols) == 15
    assert all(symbol in expected_liquidity for symbol in result.candidate_symbols)
    assert "SYM55/USDT:USDT" not in result.candidate_symbols
    assert result.candidate_symbols == [row.symbol for row in result.rows if row.is_candidate]


def test_recent_3d_trend_weight_beats_stale_history() -> None:
    fast = "FAST/USDT:USDT"
    stale = "STALE/USDT:USDT"
    histories = {
        fast: _bars(fast, step=0.0, count=3000),
        stale: _bars(stale, step=0.14, count=3000),
    }
    fast_tail = _bars(fast, start=100.0, step=0.22, count=288)
    stale_tail = _bars(stale, start=500.0, step=0.01, count=288)
    histories[fast][-288:] = [
        _copy_bar_with_timestamp(bar, histories[fast][-288 + idx].timestamp)
        for idx, bar in enumerate(fast_tail)
    ]
    histories[stale][-288:] = [
        _copy_bar_with_timestamp(bar, histories[stale][-288 + idx].timestamp)
        for idx, bar in enumerate(stale_tail)
    ]

    selector = DynamicCtaSelector(DynamicCtaConfig(min_entry_score=0.0))
    result = selector.select(
        [_snapshot(fast, 2000), _snapshot(stale, 1900)],
        histories,
        open_positions=[],
        now_ms=BASE_TS + 3000 * TF_MS,
    )

    assert result.row_by_symbol[fast].score > result.row_by_symbol[stale].score
    assert result.row_by_symbol[fast].window_scores["3d"] > result.row_by_symbol[stale].window_scores["3d"]
    assert result.candidate_symbols.index(fast) < result.candidate_symbols.index(stale)


def test_short_history_strong_trend_is_blocked_from_openable_symbols() -> None:
    symbol = "NEW/USDT:USDT"
    selector = DynamicCtaSelector(DynamicCtaConfig(min_entry_score=70.0))

    result = selector.select(
        [_snapshot(symbol, 3000)],
        {symbol: _bars(symbol, step=5.0, count=40)},
        open_positions=[],
        now_ms=BASE_TS + 40 * TF_MS,
    )

    row = result.row_by_symbol[symbol]
    assert row.blocked_reason == "insufficient_history"
    assert row.score == 0.0
    assert symbol not in result.openable_symbols


def test_low_score_and_cooldown_symbols_are_blocked() -> None:
    low = "LOW/USDT:USDT"
    cool = "COOL/USDT:USDT"
    now_ms = BASE_TS + 3000 * TF_MS
    selector = DynamicCtaSelector(DynamicCtaConfig(min_entry_score=70.0, cooldown_loss_count=2))
    selector.record_closed_trade(cool, -5.0, now_ms - 1000)
    selector.record_closed_trade(cool, -3.0, now_ms - 500)

    result = selector.select(
        [_snapshot(low, 2000), _snapshot(cool, 1900)],
        {
            low: _bars(low, step=0.0, count=3000),
            cool: _bars(cool, step=0.25, count=3000),
        },
        open_positions=[],
        now_ms=now_ms,
    )

    assert result.row_by_symbol[low].blocked_reason == "score_below_threshold"
    assert result.row_by_symbol[cool].blocked_reason == "symbol_cooldown"
    assert low not in result.openable_symbols
    assert cool not in result.openable_symbols


def test_crowded_direction_raises_required_score() -> None:
    fresh = "FRESH/USDT:USDT"
    config = DynamicCtaConfig(
        min_entry_score=70.0,
        crowded_direction_position_count=3,
        crowded_direction_score_addon=10.0,
    )
    selector = DynamicCtaSelector(config)

    result = selector.select(
        [_snapshot(fresh, 2000)],
        {fresh: _bars(fresh, step=0.12, count=3000)},
        open_positions=[
            {"symbol": "A/USDT:USDT", "side": "long"},
            {"symbol": "B/USDT:USDT", "side": "long"},
            {"symbol": "C/USDT:USDT", "side": "long"},
        ],
        now_ms=BASE_TS + 3000 * TF_MS,
        desired_directions={fresh: "long"},
    )

    row = result.row_by_symbol[fresh]
    assert row.required_score == 80.0
    assert row.score < row.required_score
    assert row.blocked_reason == "score_below_crowded_direction_threshold"
    assert fresh not in result.openable_symbols


def test_crowded_direction_accepts_symbol_to_side_mapping() -> None:
    fresh = "FRESH/USDT:USDT"
    config = DynamicCtaConfig(
        min_entry_score=70.0,
        crowded_direction_position_count=3,
        crowded_direction_score_addon=10.0,
    )
    selector = DynamicCtaSelector(config)

    result = selector.select(
        [_snapshot(fresh, 2000)],
        {fresh: _bars(fresh, step=0.12, count=3000)},
        open_positions={"A": "long", "B": "long", "C": "long"},
        now_ms=BASE_TS + 3000 * TF_MS,
        desired_directions={fresh: "long"},
    )

    row = result.row_by_symbol[fresh]
    assert row.required_score == config.min_entry_score + config.crowded_direction_score_addon


def test_snapshot_none_funding_and_open_interest_are_safe() -> None:
    symbol = "MISSING-OI/USDT:USDT"
    snapshot = MarketSnapshot(
        symbol=symbol,
        quote_volume_24h=2000.0,
        bid=99.95,
        ask=100.05,
        last=100.0,
        funding_rate=None,
        open_interest_usdt=None,
        active=True,
    )

    selector = DynamicCtaSelector(DynamicCtaConfig(min_entry_score=0.0))
    result = selector.select(
        [snapshot],
        {symbol: _bars(symbol, step=0.12, count=3000)},
        open_positions=[],
        now_ms=BASE_TS + 3000 * TF_MS,
    )

    row = result.row_by_symbol[symbol]
    assert row.symbol == symbol
    assert row.funding_rate == 0.0
    assert row.open_interest_usdt == 0.0

    strict_selector = DynamicCtaSelector(
        DynamicCtaConfig(min_entry_score=0.0, min_open_interest_usdt=1.0)
    )
    strict_result = strict_selector.select(
        [snapshot],
        {symbol: _bars(symbol, step=0.12, count=3000)},
        open_positions=[],
        now_ms=BASE_TS + 3000 * TF_MS,
    )

    assert symbol not in strict_result.liquidity_symbols
    assert strict_result.row_by_symbol[symbol].blocked_reason == "open_interest_too_low"
    assert "open_interest_too_low" in strict_result.row_by_symbol[symbol].reasons
