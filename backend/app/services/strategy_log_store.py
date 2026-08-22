"""In-memory recent strategy diagnostic log store."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Deque, Dict, List


class StrategyLogStore:
    def __init__(self, maxlen: int = 500) -> None:
        self._items: Dict[int, Deque[Dict[str, Any]]] = defaultdict(lambda: deque(maxlen=maxlen))

    @staticmethod
    def _format_time(ts_ms: int) -> str:
        dt = datetime.fromtimestamp(ts_ms / 1000)
        return f"{dt.strftime('%Y-%m-%d %H:%M:%S')}.{dt.microsecond // 100000}"

    def append(self, strategy_id: int, payload: Dict[str, Any], *, level: str = "info") -> None:
        sid = int(strategy_id)
        ts = int(datetime.now().timestamp() * 1000)
        data = dict(payload)
        data.setdefault("timestamp", ts)
        data.setdefault("time", self._format_time(ts))
        data.setdefault("level", level)
        data.setdefault("type", "log")
        self._items[sid].appendleft(data)

    def get(self, strategy_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        sid = int(strategy_id)
        return list(self._items.get(sid, []))[: max(1, int(limit))]

    def clear(self, strategy_id: int) -> None:
        sid = int(strategy_id)
        self._items.pop(sid, None)


strategy_log_store = StrategyLogStore()
