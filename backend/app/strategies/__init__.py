"""StockPro strategy package.

Crypto contract, OKX funding, and cross-exchange arbitrage modules were moved
out of the product tree. A-share research uses sealed-snapshot Strategy API v1
code, not this BitPro registry.
"""

STRATEGY_CLASSES: dict[str, type] = {}

__all__ = ["STRATEGY_CLASSES"]
