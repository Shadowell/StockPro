"""
策略代码安全沙箱
AST 静态分析 + 动态加载 + 执行隔离
"""
import ast
import inspect
import logging
from typing import Any, Dict, Sequence, Type

from app.core.execution.base_strategy import BarData, BaseStrategy, OrderResult, StrategyState

logger = logging.getLogger(__name__)

FORBIDDEN_MODULES = frozenset({
    "os", "sys", "subprocess", "shutil", "pathlib",
    "socket", "http", "urllib", "requests", "httpx", "aiohttp",
    "ctypes", "importlib", "builtins", "code", "codeop",
    "pickle", "shelve", "marshal", "signal", "multiprocessing",
    "threading", "asyncio", "io", "tempfile", "glob",
})

FORBIDDEN_NAMES = frozenset({
    "eval", "exec", "compile", "__import__", "open",
    "globals", "locals", "getattr", "setattr", "delattr",
    "breakpoint", "exit", "quit",
})

ALLOWED_IMPORTS = {
    "numpy": {"np"},
    "math": {"math"},
    "collections": {"deque"},
}

ALLOWED_FROM_IMPORTS = {
    "app.services.indicators": {
        "SMA", "EMA", "RSI", "MACD", "BBANDS", "ATR", "KDJ", "OBV",
        "CROSS_ABOVE", "CROSS_BELOW", "HIGHEST", "LOWEST",
        "STOCH_RSI", "VOLATILITY", "VWAP", "WMA", "PERCENT_RANK",
    },
    "app.core.execution.base_strategy": {
        "BaseStrategy", "BarData",
    },
    "collections": {
        "deque",
    },
    "typing": {
        "Optional", "List", "Dict", "Tuple", "Union",
    },
}

FORBIDDEN_BASE_STRATEGY_METHODS = {
    "open_long": '合约开多请使用 await self.open_contract(symbol, "long", notional_usdt, leverage=..., price=...)',
    "open_short": '合约开空请使用 await self.open_contract(symbol, "short", notional_usdt, leverage=..., price=...)',
    "close_long": '合约平多请使用 await self.close_contract(symbol, "long", ratio=..., contracts=None, price=...)',
    "close_short": '合约平空请使用 await self.close_contract(symbol, "short", ratio=..., contracts=None, price=...)',
}


class CodeSafetyError(Exception):
    """代码安全检查未通过"""


class _SafetyVisitor(ast.NodeVisitor):
    """AST 遍历器，检查危险节点"""

    def __init__(self):
        self.errors: list[str] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            mod = alias.name.split(".")[0]
            if mod in FORBIDDEN_MODULES:
                self.errors.append(f"禁止导入模块: {alias.name}")
            elif mod not in ALLOWED_IMPORTS:
                self.errors.append(f"不允许的导入: {alias.name} (仅允许 numpy/math/collections)")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod = node.module or ""
        root = mod.split(".")[0]
        if root in FORBIDDEN_MODULES:
            self.errors.append(f"禁止从 {mod} 导入")
        elif mod not in ALLOWED_FROM_IMPORTS:
            self.errors.append(f"不允许的 from 导入: {mod}")
        else:
            allowed_names = ALLOWED_FROM_IMPORTS[mod]
            for alias in node.names:
                if alias.name != "*" and alias.name not in allowed_names:
                    self.errors.append(f"不允许从 {mod} 导入: {alias.name}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_NAMES:
            self.errors.append(f"禁止调用: {node.func.id}()")
        if isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_NAMES:
            self.errors.append(f"禁止调用: .{node.func.attr}()")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if node.id.startswith("__") and node.id.endswith("__") and node.id not in ("__name__",):
            self.errors.append(f"禁止访问 dunder 属性: {node.id}")
        self.generic_visit(node)


def _indicator_import_aliases(tree: ast.AST, indicator_name: str) -> set[str]:
    aliases = {indicator_name}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "app.services.indicators":
            continue
        for alias in node.names:
            if alias.name == indicator_name:
                aliases.add(alias.asname or alias.name)
    return aliases


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _identifier_text(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _identifier_text(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Subscript):
        return _identifier_text(node.value)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return _identifier_text(node.func)
    return ""


def _looks_like_period_argument(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return True
    text = _identifier_text(node).lower()
    if not text or "close" in text:
        return False
    return "period" in text


def _validate_indicator_call_contracts(tree: ast.AST) -> None:
    atr_aliases = _indicator_import_aliases(tree, "ATR")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node) not in atr_aliases:
            continue

        keyword_names = {kw.arg for kw in node.keywords if kw.arg}
        if len(node.args) < 3 and "close" not in keyword_names:
            raise CodeSafetyError(
                "ATR 调用必须传入 high, low, close, period，例如 "
                "ATR(high_arr, low_arr, close_arr, 14)，不能省略 close。"
            )
        if len(node.args) >= 3 and _looks_like_period_argument(node.args[2]):
            raise CodeSafetyError(
                "ATR 的第 3 个参数必须是 close 收盘价数组，不是 period。"
                "正确示例: ATR(high_arr, low_arr, close_arr, atr_period)。"
            )


def _attribute_root_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        root = _attribute_root_name(node.value)
        return f"{root}.{node.attr}" if root else node.attr
    return ""


def _validate_base_strategy_method_contracts(tree: ast.AST) -> None:
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr not in FORBIDDEN_BASE_STRATEGY_METHODS:
            continue
        root = _attribute_root_name(node.value)
        if root in {"self", "self.broker"}:
            violations.append(
                f"{root}.{node.attr} 不属于当前 BaseStrategy 合约；"
                f"{FORBIDDEN_BASE_STRATEGY_METHODS[node.attr]}"
            )

    if violations:
        unique = list(dict.fromkeys(violations))
        raise CodeSafetyError(
            "策略代码使用了已废弃/不存在的合约交易快捷方法:\n"
            + "\n".join(f"  - {item}" for item in unique)
        )


def _validate_contract_exit_protection(tree: ast.AST) -> None:
    calls = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (name := _call_name(node))
    }
    if "open_contract" not in calls:
        return

    identifiers = {
        text.lower()
        for node in ast.walk(tree)
        for text in (
            node.id if isinstance(node, ast.Name) else "",
            node.attr if isinstance(node, ast.Attribute) else "",
            node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else "",
        )
        if text
    }
    identifier_text = " ".join(sorted(identifiers))
    stop_markers = ("stop_loss", "stop_price", "atr_stop", "hard_stop", "trailing_stop", "stop_buffer")
    profit_markers = (
        "take_profit",
        "profit_target",
        "risk_reward",
        "profit_trailing",
        "trailing_profit",
        "profit_peak",
    )
    missing: list[str] = []
    if not any(marker in identifier_text for marker in stop_markers):
        missing.append("止损")
    if not any(marker in identifier_text for marker in profit_markers):
        missing.append("止盈/浮盈锁利")
    if "close_contract" not in calls:
        missing.append("平仓执行")
    if missing:
        raise CodeSafetyError(
            "合约策略必须同时实现明确的止损、止盈或浮盈锁利以及 close_contract 平仓路径；"
            f"当前缺少：{'、'.join(missing)}。"
        )


def validate_code(code: str, label: str = "strategy") -> None:
    """
    对代码进行 AST 安全检查。
    Raises CodeSafetyError if anything dangerous is found.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise CodeSafetyError(f"{label} 代码语法错误: {e}") from e

    try:
        compile(tree, f"<{label}>", "exec")
    except SyntaxError as e:
        raise CodeSafetyError(f"{label} 代码语义错误: {e}") from e

    visitor = _SafetyVisitor()
    visitor.visit(tree)
    if visitor.errors:
        raise CodeSafetyError(
            f"{label} 代码安全检查失败:\n" + "\n".join(f"  - {e}" for e in visitor.errors)
        )


def validate_base_strategy_contract(code: str) -> None:
    """
    校验 AI 策略必须符合 BitPro 的 BaseStrategy + 回测框架契约。

    这里不只检查安全性，还检查能否被当前回测/实盘同构框架加载：
    - 仅一个 BaseStrategy 子类
    - 必须实现 async on_bar(self, bar)
    - on_init 如存在必须为 async
    - 禁止旧函数式 strategy/setup API
    """
    validate_code(code, "strategy_class")
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise CodeSafetyError(f"strategy_class 代码语法错误: {e}") from e
    _validate_indicator_call_contracts(tree)
    _validate_base_strategy_method_contracts(tree)
    _validate_contract_exit_protection(tree)

    if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in {"strategy", "setup"} for n in tree.body):
        raise CodeSafetyError("禁止生成旧函数式 strategy/setup API，必须生成 BaseStrategy 子类")

    class_nodes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    subclasses = _collect_base_strategy_subclasses(tree)
    if not subclasses:
        raise CodeSafetyError("代码中必须包含一个继承 BaseStrategy 的策略类")
    if len(subclasses) > 1:
        raise CodeSafetyError(f"仅允许一个 BaseStrategy 子类，发现: {subclasses}")
    if len(class_nodes) != 1:
        raise CodeSafetyError("strategy_class_code 只能定义一个策略 class，不允许额外 class")

    cls_node = next(n for n in class_nodes if n.name == subclasses[0])
    methods = {n.name: n for n in cls_node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    on_bar = methods.get("on_bar")
    if not isinstance(on_bar, ast.AsyncFunctionDef):
        raise CodeSafetyError("策略类必须实现 async def on_bar(self, bar: BarData)")
    if len(on_bar.args.args) < 2:
        raise CodeSafetyError("on_bar 签名必须包含 self 和 bar 参数")
    on_init = methods.get("on_init")
    if on_init is not None and not isinstance(on_init, ast.AsyncFunctionDef):
        raise CodeSafetyError("on_init 如存在必须为 async def")


def _collect_base_strategy_subclasses(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == "BaseStrategy":
                names.append(node.name)
            elif isinstance(base, ast.Attribute) and base.attr == "BaseStrategy":
                names.append(node.name)
    return names


def _restricted_import(
    name: str,
    globals: Any = None,
    locals: Any = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    """只允许 AI 策略代码导入白名单模块。"""
    del globals, locals
    if level != 0:
        raise ImportError("禁止相对导入")

    root = name.split(".")[0]
    if root in FORBIDDEN_MODULES:
        raise ImportError(f"禁止导入模块: {name}")

    if name in ALLOWED_FROM_IMPORTS:
        allowed_names = ALLOWED_FROM_IMPORTS[name]
        for item in fromlist or ():
            if item != "*" and item not in allowed_names:
                raise ImportError(f"不允许从 {name} 导入: {item}")
        return __import__(name, fromlist=fromlist, level=level)

    if root in ALLOWED_IMPORTS and not fromlist:
        return __import__(name, fromlist=fromlist, level=level)

    raise ImportError(f"不允许导入模块: {name}")


def _safe_exec_globals() -> Dict[str, Any]:
    import numpy as np
    from app.core.execution.base_strategy import BaseStrategy, BarData
    from app.services import indicators

    return {
        "__builtins__": {
            "range": range,
            "len": len,
            "abs": abs,
            "max": max,
            "min": min,
            "round": round,
            "int": int,
            "float": float,
            "bool": bool,
            "str": str,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "enumerate": enumerate,
            "zip": zip,
            "sorted": sorted,
            "reversed": reversed,
            "sum": sum,
            "any": any,
            "all": all,
            "isinstance": isinstance,
            "hasattr": hasattr,
            "Exception": Exception,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "KeyError": KeyError,
            "IndexError": IndexError,
            "RuntimeError": RuntimeError,
            "ZeroDivisionError": ZeroDivisionError,
            "print": lambda *a, **kw: None,
            "__import__": _restricted_import,
            "__build_class__": __build_class__,
            "True": True,
            "False": False,
            "None": None,
        },
        "__name__": "agent_strategy",
        "np": np,
        "numpy": np,
        "math": __import__("math"),
        "BaseStrategy": BaseStrategy,
        "BarData": BarData,
        "SMA": indicators.SMA,
        "EMA": indicators.EMA,
        "RSI": indicators.RSI,
        "MACD": indicators.MACD,
        "BBANDS": indicators.BBANDS,
        "ATR": indicators.ATR,
        "KDJ": indicators.KDJ,
        "OBV": indicators.OBV,
        "CROSS_ABOVE": indicators.CROSS_ABOVE,
        "CROSS_BELOW": indicators.CROSS_BELOW,
        "HIGHEST": indicators.HIGHEST,
        "LOWEST": indicators.LOWEST,
        "STOCH_RSI": indicators.STOCH_RSI,
        "VOLATILITY": indicators.VOLATILITY,
        "VWAP": indicators.VWAP,
        "WMA": indicators.WMA,
        "PERCENT_RANK": indicators.PERCENT_RANK,
    }


def load_base_strategy_class(strategy_code: str) -> Type[BaseStrategy]:
    """
    安全加载 AI 生成的策略代码，返回单个 BaseStrategy 子类。
    """
    validate_base_strategy_contract(strategy_code)
    tree = ast.parse(strategy_code)
    subclasses = _collect_base_strategy_subclasses(tree)
    if not subclasses:
        raise CodeSafetyError("代码中必须包含至少一个继承 BaseStrategy 的 class")
    if len(subclasses) > 1:
        raise CodeSafetyError(f"仅允许一个 BaseStrategy 子类，发现: {subclasses}")

    safe_globals = _safe_exec_globals()
    ns: Dict[str, Any] = dict(safe_globals)
    exec(compile(strategy_code, "<agent-strategy>", "exec"), ns)

    cls = ns[subclasses[0]]
    base = safe_globals["BaseStrategy"]
    if not isinstance(cls, type) or not issubclass(cls, base):
        raise CodeSafetyError("加载的策略类未继承 BaseStrategy")
    if not inspect.iscoroutinefunction(getattr(cls, "on_bar", None)):
        raise CodeSafetyError("策略 on_bar 必须为 async def")

    return cls


class _SmokeBroker:
    """预运行检查用的轻量 broker，避免触发真实交易或外部依赖。"""

    def __init__(self, state: StrategyState):
        self.state = state
        self.orders: list[dict[str, Any]] = []

    async def buy(
        self,
        symbol: str,
        amount: float,
        price: float | None = None,
        *,
        order_type: str = "market",
    ) -> OrderResult:
        self.state.positions[symbol] = (
            float(self.state.positions.get(symbol, 0.0)) + float(amount or 0.0)
        )
        order = {"side": "buy", "symbol": symbol, "amount": amount, "price": price, "order_type": order_type}
        self.orders.append(order)
        return OrderResult({"status": "closed", **order})

    async def sell(
        self,
        symbol: str,
        amount: float,
        price: float | None = None,
        *,
        order_type: str = "market",
    ) -> OrderResult:
        self.state.positions[symbol] = max(
            0.0,
            float(self.state.positions.get(symbol, 0.0)) - float(amount or 0.0),
        )
        order = {"side": "sell", "symbol": symbol, "amount": amount, "price": price, "order_type": order_type}
        self.orders.append(order)
        return OrderResult({"status": "closed", **order})

    async def close_position(self, symbol: str) -> OrderResult:
        amount = float(self.state.positions.get(symbol, 0.0))
        self.state.positions[symbol] = 0.0
        order = {"side": "close", "symbol": symbol, "amount": amount, "price": None, "order_type": "market"}
        self.orders.append(order)
        return OrderResult({"status": "closed", **order})

    async def open_contract(
        self,
        symbol: str,
        side: str,
        notional_usdt: float,
        leverage: float | None = None,
        price: float | None = None,
    ) -> OrderResult:
        pos_side = "short" if str(side).lower() == "short" else "long"
        key = f"{symbol}:{pos_side}"
        self.state.positions[key] = {
            "symbol": symbol,
            "side": pos_side,
            "pos_side": pos_side,
            "contracts": abs(float(notional_usdt or 0.0)),
            "notional_usdt": abs(float(notional_usdt or 0.0)),
            "leverage": float(leverage or 1.0),
            "entry_price": float(price or 100.0),
        }
        order = {
            "side": pos_side,
            "symbol": symbol,
            "notional_usdt": notional_usdt,
            "leverage": leverage,
            "price": price,
            "order_type": "contract_open",
        }
        self.orders.append(order)
        return OrderResult({"status": "closed", **order})

    async def close_contract(
        self,
        symbol: str,
        side: str,
        ratio: float = 1.0,
        contracts: float | None = None,
        price: float | None = None,
    ) -> OrderResult:
        pos_side = "short" if str(side).lower() == "short" else "long"
        key = f"{symbol}:{pos_side}"
        self.state.positions.pop(key, None)
        order = {
            "side": pos_side,
            "symbol": symbol,
            "ratio": ratio,
            "contracts": contracts,
            "price": price,
            "order_type": "contract_close",
        }
        self.orders.append(order)
        return OrderResult({"status": "closed", **order})

    async def get_contract_position(self, symbol: str, side: str) -> Dict[str, Any] | None:
        pos_side = "short" if str(side).lower() == "short" else "long"
        value = self.state.positions.get(f"{symbol}:{pos_side}")
        return dict(value) if isinstance(value, dict) else None


def _smoke_symbols(symbols: Sequence[str] | str | None) -> list[str]:
    if isinstance(symbols, str):
        parsed = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        parsed = [str(s).strip() for s in symbols or [] if str(s).strip()]
    return parsed[:3] or ["BTC/USDT", "ETH/USDT"]


def _smoke_bar(symbol: str, index: int, timeframe: str) -> BarData:
    base = 80.0 + float(sum(ord(ch) for ch in symbol) % 70)
    drift = index * 0.18
    wave = ((index % 9) - 4) * 0.35
    open_price = base + drift + wave
    close = open_price + (((index % 5) - 2) * 0.22)
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe=timeframe,
        timestamp=index * 60_000,
        open=float(open_price),
        high=float(max(open_price, close) + 0.8),
        low=float(min(open_price, close) - 0.8),
        close=float(close),
        volume=float(1_000 + index * 13 + (sum(ord(ch) for ch in symbol) % 31)),
    )


def _runtime_smoke_error(exc: Exception) -> str:
    message = str(exc)
    if "truth value of an array" in message or "truth value of a Series" in message:
        return (
            "策略预运行检查失败: NumPy/Pandas 数组不能直接用于 if/while/and/or/not。"
            "请取最后一个标量值（如 array[-1]）或显式使用 np.any()/np.all()；"
            f"原始错误: {message}"
        )
    return f"策略预运行检查失败: {type(exc).__name__}: {message}"


async def validate_strategy_runtime_smoke(
    strategy_code: str,
    *,
    symbols: Sequence[str] | str | None = None,
    market_type: str = "spot",
    timeframe: str = "1m",
    bars_per_symbol: int = 120,
) -> None:
    """
    轻量预运行 AI 生成策略，提前暴露 NumPy 真值歧义等运行时错误。

    这不是回测，也不访问交易所；它只用确定性样本 K 线调用 on_init/on_bar，
    让 Strategist 在进入正式 Backtester 前就能拿到可修复的错误反馈。
    """
    strategy_class = load_base_strategy_class(strategy_code)
    smoke_symbols = _smoke_symbols(symbols)
    state = StrategyState(
        strategy_id=-1,
        name="agent-smoke-test",
        exchange="okx",
        symbols=smoke_symbols,
        positions={"_capital": 10000.0},
    )
    broker = _SmokeBroker(state)
    instance = strategy_class(state, broker)
    instance.set_config({
        "market_type": str(market_type or "spot").lower(),
        "is_paper_trading": True,
        "max_leverage": 5,
    })

    try:
        await instance.on_init()
        total_bars = max(1, int(bars_per_symbol))
        for i in range(total_bars):
            for symbol in smoke_symbols:
                await instance.on_bar(_smoke_bar(symbol, i, timeframe))
    except CodeSafetyError:
        raise
    except Exception as exc:
        raise CodeSafetyError(_runtime_smoke_error(exc)) from exc
