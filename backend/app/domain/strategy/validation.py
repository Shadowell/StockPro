"""Static safety validation for the StockPro A-share strategy contract."""
from __future__ import annotations

import ast
from collections import Counter
from typing import Any


STRATEGY_API_VERSION = "stockpro.v1"
FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input", "breakpoint",
    "globals", "locals", "vars", "getattr", "setattr", "delattr", "__builtins__",
}
FORBIDDEN_ROOTS = {
    "os", "sys", "subprocess", "socket", "requests", "httpx", "urllib",
    "pathlib", "psycopg", "psycopg2", "sqlalchemy", "builtins", "importlib",
    "shutil", "tempfile",
}
SUPPORTED_APIS = {
    "set_benchmark", "set_option", "set_order_cost", "set_slippage",
    "run_daily", "run_weekly", "run_monthly", "history", "get_price",
    "get_current_data", "get_security_info", "get_factor_values",
    "get_factor_snapshot_info", "order", "order_value", "order_target",
    "order_target_value", "order_target_percent", "cancel_order", "record",
}
SAFE_CALLS = {
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len",
    "list", "max", "min", "range", "round", "set", "sorted", "str", "sum",
    "tuple", "zip", "Exception", "ValueError",
}
SAFE_METHOD_CALLS = {
    "append", "copy", "count", "extend", "get", "index", "items", "keys",
    "pop", "remove", "reverse", "setdefault", "sort", "values",
}


def _attribute_path(node: ast.AST) -> str:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def _safe_local_containers(tree: ast.AST) -> set[str]:
    safe_initializers: set[str] = set()
    store_counts = Counter(
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    )
    literal_nodes = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        safe_value = isinstance(value, literal_nodes) or (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in {"dict", "list", "set"}
        ) or (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in {"get_current_data", "get_factor_values", "get_price"}
        )
        if not safe_value:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        safe_initializers.update(target.id for target in targets if isinstance(target, ast.Name))
    return {name for name in safe_initializers if store_counts[name] == 1}


def _is_safe_method_receiver(receiver: ast.AST, safe_local_containers: set[str], reassigned_names: set[str]) -> bool:
    if isinstance(receiver, ast.Name):
        return (receiver.id == "data" and "data" not in reassigned_names) or receiver.id in safe_local_containers
    path = _attribute_path(receiver)
    if path in {"context.portfolio.positions", "context.parameters"} and "context" not in reassigned_names:
        return True
    return (
        isinstance(receiver, ast.Call)
        and isinstance(receiver.func, ast.Name)
        and receiver.func.id in {"get_current_data", "get_factor_values", "get_price"}
    )


def validate_strategy_python(code: str) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    try:
        tree = ast.parse(str(code or ""), mode="exec")
    except SyntaxError as exc:
        return {
            "valid": False,
            "issues": [{"code": "SYNTAX_ERROR", "message": exc.msg, "line": exc.lineno}],
            "dependencies": [],
            "api_version": STRATEGY_API_VERSION,
        }

    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    safe_local_containers = _safe_local_containers(tree)
    reassigned_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    signatures = {"initialize": ["context"], "handle_data": ["context", "data"]}
    for name, expected in signatures.items():
        node = functions.get(name)
        if node is None:
            issues.append({"code": "MISSING_LIFECYCLE", "message": f"缺少 {name}", "line": None})
        elif [arg.arg for arg in node.args.args] != expected:
            issues.append({"code": "INVALID_SIGNATURE", "message": f"{name} 参数必须为 ({', '.join(expected)})", "line": node.lineno})

    for node in tree.body:
        allowed_assignment = isinstance(node, (ast.Assign, ast.AnnAssign))
        if allowed_assignment:
            try:
                ast.literal_eval(node.value)
            except (ValueError, TypeError):
                allowed_assignment = False
        if isinstance(node, ast.FunctionDef) or allowed_assignment:
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        issues.append({"code": "TOP_LEVEL_EXECUTION", "message": "顶层只允许函数、文档字符串和字面量常量", "line": getattr(node, "lineno", None)})

    dependencies: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
            issues.append({"code": "FORBIDDEN_CAPABILITY", "message": f"不允许 {type(node).__name__}", "line": getattr(node, "lineno", None)})
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES | FORBIDDEN_ROOTS:
            issues.append({"code": "FORBIDDEN_CAPABILITY", "message": f"不允许名称 {node.id}", "line": getattr(node, "lineno", None)})
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                issues.append({"code": "FORBIDDEN_CAPABILITY", "message": "不允许 dunder 属性", "line": getattr(node, "lineno", None)})
            if node.attr in {"now", "today", "utcnow"}:
                issues.append({"code": "WALL_CLOCK_ACCESS_FORBIDDEN", "message": "策略只能使用 context.current_dt 模拟时钟", "line": getattr(node, "lineno", None)})
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                name = node.func.id
                if name in SUPPORTED_APIS:
                    dependencies.add(name)
                elif name not in functions and name not in SAFE_CALLS:
                    issues.append({"code": "UNSUPPORTED_API", "message": f"未支持的 API: {name}", "line": node.lineno})
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr not in SAFE_METHOD_CALLS or not _is_safe_method_receiver(node.func.value, safe_local_containers, reassigned_names):
                    issues.append({"code": "FORBIDDEN_METHOD_CALL", "message": f"不允许方法调用: {node.func.attr}", "line": node.lineno})
            else:
                issues.append({"code": "FORBIDDEN_DYNAMIC_CALL", "message": "不允许动态或下标函数调用", "line": node.lineno})

    unique = {(item["code"], item["message"], item.get("line")): item for item in issues}
    ordered = sorted(unique.values(), key=lambda item: (item.get("line") or 0, item["code"], item["message"]))
    return {
        "valid": not ordered,
        "issues": ordered,
        "dependencies": sorted(dependencies),
        "api_version": STRATEGY_API_VERSION,
    }
