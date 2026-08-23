"""Explicit A-share trade-date review assembly over immutable evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import psycopg2.extras

from app.services.dataset_snapshot_service import canonical_hash


class DailyReviewService:
    def __init__(self, database: Any) -> None: self.database = database

    def available_dates(self, limit: int = 120) -> list[str]:
        rows = self._rows("""SELECT DISTINCT trade_date FROM (SELECT trade_date FROM market_evidence_snapshots UNION SELECT trade_date FROM stock_pool_snapshots UNION SELECT signal_time::date FROM strategy_signals WHERE paper_instance_id IS NOT NULL UNION SELECT traded_at::date FROM trades WHERE paper_instance_id IS NOT NULL UNION SELECT trade_date FROM paper_equity_snapshots UNION SELECT trade_date FROM daily_reviews) dates WHERE trade_date IS NOT NULL ORDER BY trade_date DESC LIMIT %s""", (max(1,min(limit,500)),))
        return [str(row["trade_date"])[:10] for row in rows]

    def list_reviews(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._rows("""SELECT r.*,(SELECT COUNT(*) FROM daily_review_items i WHERE i.daily_review_id=r.id)::INTEGER AS item_count,(SELECT COUNT(*) FROM daily_review_metrics m WHERE m.daily_review_id=r.id)::INTEGER AS metric_count FROM daily_reviews r ORDER BY trade_date DESC LIMIT %s""", (max(1,min(limit,500)),))

    def get(self, trade_date: str) -> dict[str, Any]:
        target = self._date(trade_date); review = self._row("SELECT * FROM daily_reviews WHERE trade_date=%s", (target,))
        if not review: return {"review": None, "trade_date": target, "status": "missing", "items": [], "metrics": [], "counts": {}, "writes_performed": False}
        return self._stored(review, writes=False)

    def assemble(self, trade_date: str) -> dict[str, Any]:
        target = self._date(trade_date); review = self._row("SELECT * FROM daily_reviews WHERE trade_date=%s", (target,))
        if review and review["status"] == "sealed": return {**self._stored(review, writes=False), "reused": True}
        items = self._assemble_items(target); metrics = self._assemble_metrics(target); manifest = canonical_hash({"trade_date": target, "items": items, "metrics": metrics})
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                if review:
                    review_id=str(review["id"]); cursor.execute("UPDATE daily_reviews SET source_manifest_hash=%s,updated_at=NOW() WHERE id=%s",(manifest,review_id)); cursor.execute("DELETE FROM daily_review_items WHERE daily_review_id=%s",(review_id,)); cursor.execute("DELETE FROM daily_review_metrics WHERE daily_review_id=%s",(review_id,))
                else:
                    cursor.execute("INSERT INTO daily_reviews(trade_date,source_manifest_hash) VALUES (%s,%s) RETURNING id",(target,manifest)); review_id=str(cursor.fetchone()["id"])
                if items:
                    psycopg2.extras.execute_values(cursor,"""INSERT INTO daily_review_items(daily_review_id,item_key,occurred_at,category,title,summary,source_object_type,source_object_id,source_route,resolution_status,evidence,evidence_hash) VALUES %s""",[(review_id,item["item_key"],item["occurred_at"],item["category"],item["title"],item.get("summary"),item["source_object_type"],item["source_object_id"],item["source_route"],"resolved",psycopg2.extras.Json(item["evidence"],dumps=lambda value:__import__('json').dumps(value,default=str)),item["evidence_hash"]) for item in items])
                if metrics:
                    psycopg2.extras.execute_values(cursor,"""INSERT INTO daily_review_metrics(daily_review_id,metric_code,metric_value,unit,comparison_window,source_object_type,source_object_id,calculation_version,evidence) VALUES %s""",[(review_id,item["metric_code"],item["metric_value"],item["unit"],"1d",item["source_object_type"],item["source_object_id"],item["calculation_version"],psycopg2.extras.Json(item["evidence"])) for item in metrics])
        stored=self.get(target); stored["writes_performed"]=True; return stored

    def save(self, trade_date: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        target=self._date(trade_date); review=self._row("SELECT * FROM daily_reviews WHERE trade_date=%s",(target,))
        if review and review["status"]=="sealed": raise ValueError("已封存复盘不可修改")
        if not review: self.assemble(target)
        self._execute("UPDATE daily_reviews SET author_name=%s,summary=%s,next_day_plan=%s,updated_at=NOW() WHERE trade_date=%s",(str(payload.get("author_name") or "admin"),payload.get("summary"),payload.get("next_day_plan"),target))
        result=self.get(target); result["writes_performed"]=True; return result

    def seal(self, trade_date: str) -> dict[str, Any]:
        target=self._date(trade_date); current=self.get(target)
        if current["review"] is None: current=self.assemble(target)
        if current["review"]["status"]=="sealed": return {**current,"reused":True}
        self._execute("UPDATE daily_reviews SET status='sealed',sealed_at=NOW(),updated_at=NOW() WHERE trade_date=%s",(target,))
        result=self.get(target); result["writes_performed"]=True; return result

    def resolve(self, object_type: str, object_id: str) -> dict[str, Any]:
        targets={"market_evidence_snapshot":("market_evidence_snapshots","id",int),"stock_pool_snapshot":("stock_pool_snapshots","id",int),"strategy_signal":("strategy_signals","id",str),"risk_event":("risk_events","id",str),"order":("orders","id",str),"trade":("trades","id",str),"paper_equity_snapshot":("paper_equity_snapshots","id",int),"paper_instance":("paper_instances","id",str)}
        target=targets.get(object_type)
        if not target:return {"status":"unavailable","object_type":object_type,"object_id":object_id}
        table,column,convert=target
        try: value=convert(object_id)
        except (TypeError,ValueError): return {"status":"unavailable","object_type":object_type,"object_id":object_id}
        row=self._row(f"SELECT * FROM {table} WHERE {column}=%s",(value,)); return {"status":"resolved" if row else "archived","object_type":object_type,"object_id":object_id,"object":row}

    def _assemble_items(self,target:str)->list[dict[str,Any]]:
        specs=[("strategy","strategy_signals","signal_time","策略信号","strategy_signal","/signals","paper_instance_id IS NOT NULL"),("order","orders","COALESCE(filled_at,earliest_fill_at,created_at)","模拟订单","order","/paper","paper_instance_id IS NOT NULL"),("trade","trades","traded_at","模拟成交","trade","/paper","paper_instance_id IS NOT NULL"),("performance","paper_equity_snapshots","created_at","Paper 权益","paper_equity_snapshot","/paper","TRUE")]
        items=[]
        for category,table,time_col,title_prefix,object_type,route,guard in specs:
            date_col="trade_date" if table=="paper_equity_snapshots" else f"({time_col})::date"
            for row in self._rows(f"SELECT * FROM {table} WHERE {guard} AND {date_col}=%s ORDER BY {time_col},id",(target,)):
                occurred=row.get("signal_time") or row.get("filled_at") or row.get("earliest_fill_at") or row.get("traded_at") or row.get("created_at") or datetime.now(timezone.utc); object_id=str(row["id"]); symbol=row.get("symbol") or ""; title=f"{title_prefix} · {symbol}".rstrip(" ·"); evidence={key:row.get(key) for key in ("paper_instance_id","strategy_version_id","order_id","signal_id","equity","nav","drawdown") if row.get(key) is not None}; normalized={"occurred_at":occurred,"category":category,"title":title,"summary":row.get("reason") or row.get("status"),"source_object_type":object_type,"source_object_id":object_id,"source_route":route,"evidence":evidence}; normalized["item_key"]=canonical_hash({"type":object_type,"id":object_id}); normalized["evidence_hash"]=canonical_hash(normalized); items.append(normalized)
        return sorted(items,key=lambda item:(str(item["occurred_at"]),item["item_key"]))

    def _assemble_metrics(self,target:str)->list[dict[str,Any]]:
        output=[]
        for row in self._rows("SELECT id,paper_instance_id,equity,nav,drawdown,ledger_difference FROM paper_equity_snapshots WHERE trade_date=%s ORDER BY id",(target,)):
            for code,value,unit in (("paper_equity",row["equity"],"CNY"),("paper_nav",row["nav"],"ratio"),("paper_drawdown",row["drawdown"],"ratio"),("ledger_difference",row["ledger_difference"],"CNY")):
                output.append({"metric_code":f"{code}:{row['paper_instance_id']}","metric_value":float(value),"unit":unit,"source_object_type":"paper_equity_snapshot","source_object_id":str(row["id"]),"calculation_version":"paper-runtime","evidence":{"paper_instance_id":str(row["paper_instance_id"])}})
        return output

    def _stored(self,review:Mapping[str,Any],*,writes:bool)->dict[str,Any]:
        items=self._rows("SELECT * FROM daily_review_items WHERE daily_review_id=%s ORDER BY occurred_at,id",(review["id"],)); metrics=self._rows("SELECT * FROM daily_review_metrics WHERE daily_review_id=%s ORDER BY metric_code,id",(review["id"],)); counts={}
        for item in items: counts[item["category"]]=counts.get(item["category"],0)+1
        return {"review":dict(review),"trade_date":str(review["trade_date"])[:10],"status":review["status"],"items":items,"metrics":metrics,"counts":counts,"source_manifest_hash":review.get("source_manifest_hash"),"writes_performed":writes}
    @staticmethod
    def _date(value:str)->str: return datetime.strptime(str(value or "")[:10],"%Y-%m-%d").date().isoformat()
    def _rows(self,query:str,params:Sequence[Any]=())->list[dict[str,Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor: cursor.execute(query,params); return [dict(row) for row in cursor.fetchall()]
    def _row(self,query:str,params:Sequence[Any]=())->dict[str,Any]|None:
        rows=self._rows(query,params); return rows[0] if rows else None
    def _execute(self,query:str,params:Sequence[Any]=())->None:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor: cursor.execute(query,params)
