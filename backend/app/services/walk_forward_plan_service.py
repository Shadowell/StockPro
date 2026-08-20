"""Read-only walk-forward fold planning over sealed trading-date evidence."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

import psycopg2.extras


def generate_trading_folds(
    trading_dates: Sequence[str],
    *,
    train_sessions: int,
    test_sessions: int,
    step_sessions: int,
) -> List[Dict[str, Any]]:
    if train_sessions <= 0 or test_sessions <= 0 or step_sessions <= 0:
        raise ValueError("训练、测试和步进交易日必须为正数")
    dates = sorted({str(item)[:10] for item in trading_dates if item})
    folds: List[Dict[str, Any]] = []
    offset = 0
    while True:
        train_end_index = offset + train_sessions - 1
        test_start_index = train_end_index + 1
        test_end_index = test_start_index + test_sessions - 1
        if test_end_index >= len(dates):
            break
        folds.append({
            "index": len(folds) + 1,
            "train_start": dates[offset],
            "train_end": dates[train_end_index],
            "test_start": dates[test_start_index],
            "test_end": dates[test_end_index],
            "train_sessions": train_sessions,
            "test_sessions": test_sessions,
        })
        offset += step_sessions
    if not folds:
        raise ValueError(
            f"所选交易日不足以生成一折（至少需要 {train_sessions + test_sessions} 个交易日）"
        )
    return folds


class WalkForwardPlanService:
    planning_version = "walk-forward-plan.v1"

    def __init__(self, database):
        self.database = database

    def preview(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        snapshot_id = int(payload.get("dataset_snapshot_id") or 0)
        if snapshot_id <= 0:
            raise ValueError("数据快照必填")
        snapshots = self._rows(
            "SELECT id,status,manifest_hash FROM dataset_snapshots WHERE id=%s",
            (snapshot_id,),
        )
        if not snapshots:
            raise ValueError("数据快照不存在")
        snapshot = snapshots[0]
        if snapshot.get("status") != "sealed":
            raise ValueError("Walk-forward 只能读取已封存数据快照")

        start_date = str(payload.get("start_date") or "")[:10]
        end_date = str(payload.get("end_date") or "")[:10]
        if not start_date or not end_date or start_date > end_date:
            raise ValueError("开始/结束日期必填且顺序合法")
        date_rows = self._rows(
            """
            SELECT DISTINCT r.payload->>'trade_date' AS trade_date
            FROM dataset_partition_records r
            JOIN dataset_snapshot_items i ON i.partition_id=r.partition_id
            WHERE i.snapshot_id=%s AND i.dataset_code='daily_bars'
              AND r.payload->>'trade_date'>=%s AND r.payload->>'trade_date'<=%s
            ORDER BY trade_date
            """,
            (snapshot_id, start_date, end_date),
        )
        dates = [str(item.get("trade_date") or "")[:10] for item in date_rows if item.get("trade_date")]
        folds = generate_trading_folds(
            dates,
            train_sessions=int(payload.get("train_sessions") or 0),
            test_sessions=int(payload.get("test_sessions") or 0),
            step_sessions=int(payload.get("step_sessions") or 0),
        )
        return {
            "planning_version": self.planning_version,
            "dataset_snapshot_id": snapshot_id,
            "dataset_manifest_hash": snapshot.get("manifest_hash"),
            "start_date": start_date,
            "end_date": end_date,
            "date_count": len(dates),
            "n_folds": len(folds),
            "folds": folds,
            "promotion_eligible": False,
            "next_step": "每折训练区间参数优化与紧邻测试区间 OOS 执行尚未启动",
        }

    def _rows(self, query: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(item) for item in cursor.fetchall()]
