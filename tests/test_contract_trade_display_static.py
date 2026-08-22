from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
INSTANCE_MONITOR = ROOT / "frontend" / "src" / "pages" / "liveTrading" / "InstanceMonitor.tsx"
TRADE_METRICS = ROOT / "frontend" / "src" / "utils" / "tradeMetrics.ts"


def test_instance_monitor_uses_contract_notional_helper_for_trade_amount():
    monitor = INSTANCE_MONITOR.read_text(encoding="utf-8")
    metrics = TRADE_METRICS.read_text(encoding="utf-8")

    assert "getTradeNotionalUsdt(t)" in monitor
    assert "Number(t.price) * Number(t.quantity)" not in monitor
    assert "meta?.notional_usdt" in metrics
    assert "isContractTradeSide(trade.side)" in metrics
    assert re.search(r"if \(metaMarketType === 'swap'.*return null", metrics, re.S)


def test_contract_open_trades_do_not_show_realized_pnl():
    monitor = INSTANCE_MONITOR.read_text(encoding="utf-8")
    metrics = TRADE_METRICS.read_text(encoding="utf-8")

    assert "getRealizedTradePnl(t)" in monitor
    realized_block = re.search(
        r"export function isRealizedPnlTradeSide\(side: unknown\): boolean \{(?P<body>.*?)\n\}",
        metrics,
        re.S,
    )
    assert realized_block, "missing realized PnL side helper"
    body = realized_block.group("body")

    assert "normalized === 'close_long'" in body
    assert "normalized === 'close_short'" in body
    assert "normalized === 'sell'" in body
    assert "normalized === 'open_long'" not in body
    assert "normalized === 'open_short'" not in body


def test_instance_monitor_displays_contract_trade_leverage():
    monitor = INSTANCE_MONITOR.read_text(encoding="utf-8")
    metrics = TRADE_METRICS.read_text(encoding="utf-8")

    assert "getTradeLeverage(t)" in monitor
    assert ">杠杆<" in monitor
    assert "export function getTradeLeverage" in metrics
    assert "meta?.leverage" in metrics
    assert "trade.leverage" in metrics


def test_instance_monitor_uses_contract_position_notional_for_position_amount():
    monitor = INSTANCE_MONITOR.read_text(encoding="utf-8")
    metrics = TRADE_METRICS.read_text(encoding="utf-8")

    assert "getPositionNotionalUsdt(row)" in monitor
    assert "positionNotional.toFixed(2)" in monitor
    assert "`${positionNotional.toFixed(2)} USDT`" not in monitor
    assert "Number(row.size) * markPrice" not in monitor
    assert "position.notionalUsdt" in metrics
    assert "position.notional_usdt" in metrics


def test_instance_monitor_labels_contract_notional_and_trade_margin_separately():
    monitor = INSTANCE_MONITOR.read_text(encoding="utf-8")
    metrics = TRADE_METRICS.read_text(encoding="utf-8")

    assert "getPositionMarginUsdt(row)" not in monitor
    assert "getTradeMarginUsdt(t)" in monitor
    assert "tradeNotional.toFixed(2)" in monitor
    assert "tradeMargin.toFixed(2)" in monitor
    assert "`${tradeNotional.toFixed(2)} USDT`" not in monitor
    assert "`${tradeMargin.toFixed(2)} USDT`" not in monitor
    assert "const hasContractPositions = positions.some(isContractPosition);" in monitor
    assert "const hasContractTrades = trades.some((trade) => (" in monitor
    assert "hasContractPositions ? '持仓名义' : '持仓金额'" in monitor
    assert "hasContractTrades ? '成交名义' : '交易金额'" in monitor
    assert "hasContractPositions &&" in monitor
    assert "hasContractTrades &&" in monitor
    header_rows = re.findall(r"<thead.*?>.*?</thead>", monitor, re.S)
    position_headers = [row for row in header_rows if "持仓名义" in row]
    trade_headers = [row for row in header_rows if "成交名义" in row]
    assert position_headers
    assert trade_headers
    assert "保证金" not in position_headers[0]
    assert "保证金" in trade_headers[0]

    assert "export function getTradeMarginUsdt" in metrics
    assert "meta?.margin" in metrics


def test_instance_monitor_displays_contract_unit_size_for_positions_and_trades():
    monitor = INSTANCE_MONITOR.read_text(encoding="utf-8")
    metrics = TRADE_METRICS.read_text(encoding="utf-8")

    assert "getPositionContractUnitSize(row)" in monitor
    assert "getTradeContractUnitSize(t)" in monitor
    assert ">每张数量<" in monitor
    assert "formatContractUnitSize(positionContractUnitSize)" in monitor
    assert "formatContractUnitSize(tradeContractUnitSize)" in monitor
    assert "function contractBaseCurrency" not in monitor

    assert "export function getPositionContractUnitSize" in metrics
    assert "export function getTradeContractUnitSize" in metrics
    assert "position.baseQty" in metrics
    assert "position.base_qty" in metrics
    assert "meta?.base_qty" in metrics
    assert "meta?.contracts" in metrics


def test_instance_monitor_aligns_position_and_trade_table_headers_with_cells():
    monitor = INSTANCE_MONITOR.read_text(encoding="utf-8")

    header_rows = re.findall(r"<thead.*?>.*?</thead>", monitor, re.S)
    table_headers = "\n".join(
        row for row in header_rows if "持仓名义" in row or "成交名义" in row
    )

    assert table_headers
    assert 'font-medium">交易对</th>' not in table_headers
    assert 'font-medium">时间</th>' not in table_headers
    assert '<th className="py-2 pr-2 font-medium text-left">交易对</th>' in table_headers
    assert '<th className="py-2 pr-2 font-medium text-left">时间</th>' in table_headers
    assert '<th className="py-2 pr-2 font-medium text-center">杠杆</th>' in table_headers
    assert '<th className="py-2 pr-2 font-medium text-center">方向</th>' in table_headers
    assert "const positionQuantityLabel = '张数/数量';" in monitor
    assert "const tradeQuantityLabel = '张数/数量';" in monitor
    assert '<th className="py-2 pr-2 font-medium text-right">每张数量</th>' in table_headers
    assert '<th className="py-2 pr-2 font-medium text-right">持仓均价</th>' in table_headers
    assert '<th className="py-2 pr-2 font-medium text-right">手续费</th>' in table_headers
    assert "text-center font-semibold" in monitor
    assert "text-center tabular-nums text-gray-300" in monitor


def test_instance_monitor_formats_position_entry_and_mark_prices_with_shared_precision():
    monitor = INSTANCE_MONITOR.read_text(encoding="utf-8")

    assert "function getPositionPriceDigits(...rawValues: unknown[]): number" in monitor
    assert "const positionPriceDigits = getPositionPriceDigits(row.entryPrice, row.markPrice)" in monitor
    assert "formatPositionPrice(row.entryPrice, positionPriceDigits)" in monitor
    assert "formatPositionPrice(row.markPrice, positionPriceDigits)" in monitor
    assert "minimumFractionDigits: digits" in monitor
    assert "maximumFractionDigits: digits" in monitor
    assert "Number(row.entryPrice).toLocaleString()" not in monitor
    assert "markPrice.toLocaleString()" not in monitor
