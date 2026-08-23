"""BitPro 可维护的市场板块分类。

板块只描述标的所属主题，不参与策略、风控或交易执行。未知或新上线标的
统一进入 ``其他``，确保批量行情里的每一行始终只有一个分类。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable


MARKET_TAXONOMY_VERSION = "2026-08-04"


def _symbols(raw: str) -> tuple[str, ...]:
    return tuple(part for part in raw.split() if part)


# 顺序即优先级；同一标的只取首次出现的板块。
SECTOR_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("blue-chip", "主流资产", _symbols("BTC ETH XRP SOL BNB ADA BCH LTC OKB TRX XLM ETC")),
    ("layer1", "公链生态", _symbols(
        "SUI AVAX DOT NEAR APT ATOM TON ICP ALGO HBAR SEI INJ TIA CELO CFX CORE EGLD FLOW FOGO "
        "IOTA KSM MINA MON MOVE NEO ONE ONT PI QTUM RVN SONIC STX VET XTZ ZETA ZIL"
    )),
    ("layer2", "Layer2 / 扩容", _symbols(
        "ARB OP POL STRK ZK ZRO LINEA METIS IMX MANTA MERL MNT MORPH ZORA ZKP"
    )),
    ("defi", "DeFi", _symbols(
        "1INCH AAVE AERO AEVO AUCTION COMP CRV CVX DYDX ENA ETHFI EIGEN GMX GRVT JTO JUP KMNO "
        "LDO LQTY MORPHO ONDO PENDLE RAY RESOLV SKY SNX SSV SUSHI SYRUP UNI UMA WOO YFI ZRX"
    )),
    ("ai-data", "AI / 数据", _symbols(
        "0G AI AIXBT ARKM BREV COAI FET GLM GRT GRASS KAITO RENDER ROBO SAPIEN SENT TAO VANA "
        "VIRTUAL WLD ZAMA"
    )),
    ("meme", "Meme", _symbols(
        "DOGE SHIB PEPE WIF BONK FLOKI BRETT BOME FARTCOIN GIGGLE JELLYJELLY MEW MOODENG "
        "MUBARAK NEIRO PEOPLE PENGU PIPPIN PNUT POPCAT TRUMP TURBO USELESS MEME ANIME DOOD"
    )),
    ("gaming", "游戏 / 元宇宙", _symbols(
        "APE AXS BIGTIME CHZ ENJ GALA GMT HMSTR MAGIC MANA SAND THETA YGG"
    )),
    ("infrastructure", "基础设施", _symbols(
        "2Z API3 AR BAND BAT BICO BLUR DATA ENS FIL GAS ICX IOST IO LINK LPT MASK NMR ORDI "
        "ORDER PYTH RECALL RIVER RSR SATS SIGN TWT WCT"
    )),
    ("payments-rwa", "支付 / RWA", _symbols(
        "A ACH ALLO CRO HUMA RLS STABLE USDC WAL WLFI XDC"
    )),
    ("privacy", "隐私计算", _symbols("DASH ROSE SCRT XMR ZEC ZEN")),
    ("tradfi-commodity", "TradFi · 大宗商品", _symbols("BZ CL NG XAG XAU XCU XPD XPT USO")),
    ("tradfi-semiconductor", "TradFi · 半导体", _symbols(
        "AAOI AEHR ALAB AMAT AMD ARM ASML AVGO AXTI COHR CRDO DRAM INTC KIOXIA KLAC LITE LRCX "
        "MRVL MU NVDA ON QCOM SIMO SKHYNIX SKHY SMCI SMH SNDK SOXL SOXS TER TSEM TSM TTMI WDC"
    )),
    ("tradfi-tech", "TradFi · 科技", _symbols(
        "AAPL ADBE AMZN APP CRM CRWD CSCO DELL GOOGL HPE IBM META MSFT NFLX NOK NOW OKTA ORCL "
        "PLTR RDDT SNOW TWLO ZM"
    )),
    ("tradfi-index", "TradFi · 指数 ETF", _symbols(
        "EWJ EWY EWZ EWT IWM KORU KR200 QQQ SPY SQQQ TMF TQQQ URNM UVXY XBI XLE"
    )),
    ("tradfi-theme", "TradFi · 新兴主题", _symbols(
        "ANTHROPIC OPENAI SPCX BOT BSP BX CBRS FLY FWDI INFQ INTW MINIMAX MUU MVLL PENG QNT RAM "
        "SHAZ SHLD SNXX ZHIPU"
    )),
    ("tradfi-equity", "TradFi · 其他股票", _symbols(
        "BE BMNR COIN COST CRCL CRWV DKNG FLNC GEV GLW GME HIMS HOOD HYUNDAI IREN ISRG JNJ LLY "
        "LUNR MSTR NBIS O OSCR POET RDW RIVN RKLB ROK SAMSUNG SOFTBANK SONY STRC TSLA TTWO UNH "
        "USAR VRT WEN APLD ASTS BB CGNX CIEN CRDO CRCL GEV ONDS"
    )),
)


def _build_symbol_index(definitions: Iterable[tuple[str, str, tuple[str, ...]]]) -> Dict[str, tuple[str, str]]:
    index: Dict[str, tuple[str, str]] = {}
    for key, name, symbols in definitions:
        for symbol in symbols:
            index.setdefault(symbol, (key, name))
    return index


_SYMBOL_TO_SECTOR = _build_symbol_index(SECTOR_DEFINITIONS)


def market_symbol_base(symbol: str) -> str:
    """从 CCXT 现货/合约 symbol 提取基础标的代码。"""
    return str(symbol or "").split("/", 1)[0].strip().upper()


def classify_market_symbol(symbol: str) -> Dict[str, str]:
    """返回稳定、唯一且始终存在的板块元数据。"""
    sector_key, sector_name = _SYMBOL_TO_SECTOR.get(market_symbol_base(symbol), ("other", "其他"))
    return {
        "sector_key": sector_key,
        "sector_name": sector_name,
        "taxonomy_version": MARKET_TAXONOMY_VERSION,
    }


def enrich_market_ticker(ticker: Dict[str, Any]) -> Dict[str, Any]:
    """以新增字段方式丰富 ticker，不修改行情服务缓存中的原对象。"""
    return {**ticker, **classify_market_symbol(str(ticker.get("symbol") or ""))}
