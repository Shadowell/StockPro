"""Isolated worker for StockPro Strategy API v1.

The parent process validates source and owns persistence. This worker receives one
JSON payload on stdin and emits one JSON result on stdout.
"""
from __future__ import annotations

import json
import math
import resource
import sys
import traceback
from datetime import datetime
from types import SimpleNamespace


class HistorySeries(list):
    def mean(self):
        values = [float(item) for item in self if item is not None]
        return sum(values) / len(values) if values else float("nan")


class Runtime:
    def __init__(self, payload):
        self.payload = payload
        self.events = payload.get("events") or []
        self.intents = []
        self.records = []
        self.logs = []
        self.schedules = []
        self.current_event = None
        self.current_ordinal = -1
        self.context = SimpleNamespace(
            current_dt=None,
            previous_date=None,
            parameters=payload.get("parameters") or {},
            universe=list(payload.get("symbols") or []),
            knowledge_cutoff_at=payload.get("knowledge_cutoff_at"),
            dataset_snapshot_id=payload.get("dataset_snapshot_id"),
            factor_snapshot_id=payload.get("factor_snapshot_id"),
            portfolio=SimpleNamespace(cash=float((payload.get("parameters") or {}).get("initial_cash", 1000000)), positions={}),
        )
        self.options = {"avoid_future_data": True}
        self.benchmark = None

    def _append_intent(self, intent_type, symbol, value=None, **extra):
        if len(self.intents) >= int(self.payload["limits"]["max_intents"]):
            raise RuntimeError("INTENT_LIMIT_EXCEEDED")
        event = self.current_event or {}
        item = {
            "event_ordinal": self.current_ordinal,
            "simulated_at": event.get("simulated_at"),
            "available_at": event.get("available_at"),
            "symbol": str(symbol),
            "intent_type": intent_type,
            "value": value,
            **extra,
        }
        try:
            json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("INTENT_NOT_SERIALIZABLE") from exc
        self.intents.append(item)
        return SimpleNamespace(id=len(self.intents), status="created", **item)

    def order(self, symbol, amount, **kwargs):
        return self._append_intent("order", symbol, float(amount), **kwargs)

    def order_value(self, symbol, value, **kwargs):
        return self._append_intent("order_value", symbol, float(value), **kwargs)

    def order_target(self, symbol, amount, **kwargs):
        return self._append_intent("order_target", symbol, float(amount), **kwargs)

    def order_target_value(self, symbol, value, **kwargs):
        return self._append_intent("order_target_value", symbol, float(value), **kwargs)

    def order_target_percent(self, symbol, target, **kwargs):
        return self._append_intent("order_target_percent", symbol, float(target), **kwargs)

    def cancel_order(self, order):
        return self._append_intent("cancel_order", getattr(order, "symbol", ""), getattr(order, "id", order))

    def history(self, symbol, count, unit="1d", field="close"):
        if unit != "1d":
            raise ValueError("UNSUPPORTED_FREQUENCY")
        series = self.payload.get("series") or {}
        values = ((series.get(str(symbol)) or {}).get(str(field)) or [])[: self.current_ordinal + 1]
        values = values[-max(1, int(count)):]
        return HistorySeries(values)

    def get_price(self, symbol, count=1, unit="1d", fields="close"):
        if isinstance(fields, (list, tuple)):
            return {field: self.history(symbol, count, unit, field) for field in fields}
        return self.history(symbol, count, unit, fields)

    def get_current_data(self):
        return {symbol: SimpleNamespace(**values) for symbol, values in ((self.current_event or {}).get("bars") or {}).items()}

    def get_security_info(self, symbol):
        return SimpleNamespace(code=str(symbol), display_name=str(symbol), start_date=None, end_date=None)

    def get_factor_values(self, factor_code, symbols=None):
        values = ((self.current_event or {}).get("factors") or {}).get(str(factor_code)) or {}
        selected = symbols or self.context.universe
        return {symbol: values.get(symbol) for symbol in selected}

    def get_factor_snapshot_info(self):
        return self.payload.get("factor_snapshot_info") or {
            "factor_snapshot_id": self.payload.get("factor_snapshot_id"),
            "knowledge_cutoff_at": self.payload.get("knowledge_cutoff_at"),
        }

    def record(self, **values):
        if len(self.records) >= int(self.payload["limits"]["max_records"]):
            raise RuntimeError("RECORD_LIMIT_EXCEEDED")
        try:
            json.dumps(values, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("RECORD_NOT_SERIALIZABLE") from exc
        event = self.current_event or {}
        self.records.append({
            "event_ordinal": self.current_ordinal,
            "simulated_at": event.get("simulated_at"),
            "available_at": event.get("available_at"),
            "payload": values,
        })

    def assert_serializable_context(self):
        state = dict(self.context.__dict__)
        state["current_dt"] = state["current_dt"].isoformat() if state.get("current_dt") else None
        state["portfolio"] = dict(self.context.portfolio.__dict__)
        try:
            json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("CONTEXT_NOT_SERIALIZABLE") from exc

    def run_daily(self, callback, time="open"):
        self.schedules.append(("daily", callback, {"time": time}))

    def run_weekly(self, callback, weekday=1, time="open"):
        self.schedules.append(("weekly", callback, {"weekday": int(weekday), "time": time}))

    def run_monthly(self, callback, trading_day=1, time="open"):
        self.schedules.append(("monthly", callback, {"trading_day": int(trading_day), "time": time}))

    def set_benchmark(self, symbol):
        self.benchmark = str(symbol)

    def set_option(self, key, value):
        if key == "avoid_future_data" and value is not True:
            raise ValueError("FUTURE_DATA_OPTION_REQUIRED")
        self.options[str(key)] = value

    def set_order_cost(self, value=None, **kwargs):
        self.options["order_cost"] = ({"value": value} if value is not None else {}) | kwargs

    def set_slippage(self, value=None, **kwargs):
        self.options["slippage"] = ({"value": value} if value is not None else {}) | kwargs

    def log(self, level, message):
        text = str(message)
        used = sum(len(item["message"].encode("utf-8")) for item in self.logs)
        if used + len(text.encode("utf-8")) > int(self.payload["limits"]["log_bytes"]):
            raise RuntimeError("LOG_LIMIT_EXCEEDED")
        self.logs.append({"level": level, "message": text, "event_ordinal": self.current_ordinal})

    def bindings(self):
        safe_builtins = {
            "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
            "enumerate": enumerate, "float": float, "int": int, "len": len,
            "list": list, "max": max, "min": min, "range": range, "round": round,
            "set": set, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple,
            "zip": zip, "Exception": Exception, "ValueError": ValueError,
        }
        logger = SimpleNamespace(
            debug=lambda message: self.log("debug", message),
            info=lambda message: self.log("info", message),
            warning=lambda message: self.log("warning", message),
            error=lambda message: self.log("error", message),
        )
        return {
            "__builtins__": safe_builtins,
            "math": math,
            "log": logger,
            "set_benchmark": self.set_benchmark,
            "set_option": self.set_option,
            "set_order_cost": self.set_order_cost,
            "set_slippage": self.set_slippage,
            "run_daily": self.run_daily,
            "run_weekly": self.run_weekly,
            "run_monthly": self.run_monthly,
            "history": self.history,
            "get_price": self.get_price,
            "get_current_data": self.get_current_data,
            "get_security_info": self.get_security_info,
            "get_factor_values": self.get_factor_values,
            "get_factor_snapshot_info": self.get_factor_snapshot_info,
            "order": self.order,
            "order_value": self.order_value,
            "order_target": self.order_target,
            "order_target_value": self.order_target_value,
            "order_target_percent": self.order_target_percent,
            "cancel_order": self.cancel_order,
            "record": self.record,
        }

    def execute(self):
        namespace = self.bindings()
        exec(compile(self.payload["code"], "<strategy-version>", "exec"), namespace, namespace)
        namespace["initialize"](self.context)
        month_counts = {}
        for ordinal, event in enumerate(self.events):
            self.current_event = event
            self.current_ordinal = ordinal
            current_dt = datetime.fromisoformat(event["simulated_at"])
            self.context.current_dt = current_dt
            self.context.previous_date = event.get("previous_date")
            data = self.get_current_data()
            if namespace.get("before_trading_start"):
                namespace["before_trading_start"](self.context)
            month_key = current_dt.strftime("%Y-%m")
            month_counts[month_key] = month_counts.get(month_key, 0) + 1
            for frequency, callback, config in self.schedules:
                due = frequency == "daily"
                if frequency == "weekly":
                    due = current_dt.isoweekday() == config["weekday"]
                if frequency == "monthly":
                    due = month_counts[month_key] == config["trading_day"]
                if due:
                    callback(self.context)
            namespace["handle_data"](self.context, data)
            if namespace.get("after_trading_end"):
                namespace["after_trading_end"](self.context)
        if namespace.get("on_strategy_end"):
            namespace["on_strategy_end"](self.context)
        self.assert_serializable_context()
        return {
            "success": True,
            "intents": self.intents,
            "records": self.records,
            "logs": self.logs,
            "benchmark": self.benchmark,
            "options": self.options,
        }


def apply_limits(limits):
    memory = int(limits.get("memory_mb", 512)) * 1024 * 1024
    _, memory_hard = resource.getrlimit(resource.RLIMIT_AS)
    try:
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory_hard))
    except (ValueError, OSError):
        # macOS may reject RLIMIT_AS lowering; the parent process enforces RSS.
        pass

    def _set_safe(which: int, value: int) -> None:
        """Lower the soft limit only; never exceed the inherited hard limit."""
        soft, hard = resource.getrlimit(which)
        if hard != resource.RLIM_INFINITY:
            value = min(value, hard)
        try:
            resource.setrlimit(which, (value, hard))
        except (ValueError, OSError):
            # Parent still enforces wall clock and RSS; limits are best effort.
            pass

    _set_safe(resource.RLIMIT_CPU, max(1, int(limits.get("cpu_seconds", 2))))
    _set_safe(resource.RLIMIT_NOFILE, max(8, int(limits.get("open_files", 32))))


def main():
    payload = json.loads(sys.stdin.buffer.read())
    try:
        apply_limits(payload.get("limits") or {})
        result = Runtime(payload).execute()
    except BaseException as exc:
        error_code = str(exc) if str(exc) in {
            "INTENT_LIMIT_EXCEEDED", "RECORD_LIMIT_EXCEEDED", "LOG_LIMIT_EXCEEDED",
            "CONTEXT_NOT_SERIALIZABLE", "INTENT_NOT_SERIALIZABLE", "RECORD_NOT_SERIALIZABLE",
        } else "WORKER_RUNTIME_ERROR"
        result = {
            "success": False,
            "error_code": error_code,
            "error_message": str(exc)[:1000],
            "diagnostic": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[:2000],
        }
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    if len(encoded) > int((payload.get("limits") or {}).get("output_bytes", 1048576)):
        encoded = json.dumps({"success": False, "resource_failure": True, "error_code": "OUTPUT_LIMIT_EXCEEDED", "error_message": "worker output exceeded limit"}).encode("utf-8")
    sys.stdout.buffer.write(encoded)


if __name__ == "__main__":
    main()
