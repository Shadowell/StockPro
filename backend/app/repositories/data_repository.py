from __future__ import annotations
import hashlib,json,uuid
from typing import Any,Sequence
import psycopg2.extras

class PostgresDataRepository:
    def __init__(self,database:Any)->None:self.database=database
    def status(self)->dict[str,Any]:
        row=self._row("""SELECT (SELECT count(*) FROM dataset_definitions)::integer datasets,(SELECT count(*) FROM dataset_partitions WHERE status='published')::integer published_partitions,(SELECT COALESCE(sum(row_count),0) FROM dataset_partitions WHERE status='published')::bigint published_rows,(SELECT count(*) FROM dataset_snapshots WHERE status='sealed')::integer sealed_snapshots,(SELECT count(*) FROM sync_jobs)::integer sync_jobs,(SELECT count(*) FROM data_quality_issues)::integer quality_issues,(SELECT count(*) FROM extension_data_imports)::integer staged_imports""") or {}
        return {"storage":"postgresql",**row}
    def datasets(self):return self._rows("""SELECT d.*,w.last_published_trade_date,w.updated_at AS watermark_updated_at,(SELECT count(*) FROM dataset_partitions p WHERE p.dataset_id=d.id)::integer partition_count,(SELECT COALESCE(sum(row_count),0) FROM dataset_partitions p WHERE p.dataset_id=d.id)::bigint row_count FROM dataset_definitions d LEFT JOIN dataset_watermarks w ON w.dataset_id=d.id ORDER BY d.code""")
    def snapshots(self,limit:int):return self._rows("SELECT s.*,(SELECT count(*) FROM dataset_snapshot_items i WHERE i.snapshot_id=s.id)::integer item_count FROM dataset_snapshots s ORDER BY created_at DESC LIMIT %s",(limit,))
    def providers(self):return self._rows("SELECT * FROM source_entitlements ORDER BY dataset_code,source")
    def schedules(self):return self._rows("SELECT * FROM dataset_sync_schedules ORDER BY code")
    def jobs(self,limit:int):return self._rows("SELECT * FROM sync_jobs ORDER BY created_at DESC LIMIT %s",(limit,))
    def quality(self,limit:int):return self._rows("""SELECT q.*,d.code AS dataset_code,p.partition_key FROM data_quality_issues q JOIN dataset_partitions p ON p.id=q.partition_id JOIN dataset_definitions d ON d.id=p.dataset_id ORDER BY q.created_at DESC LIMIT %s""",(limit,))
    def imports(self,limit:int):return self._rows("SELECT * FROM extension_data_imports ORDER BY created_at DESC LIMIT %s",(limit,))
    def import_records(self,import_id:str):return self._rows("SELECT ordinal,payload FROM extension_data_records WHERE import_id=%s ORDER BY ordinal",(import_id,))
    def stage(self,*,name:str,filename:str,file_format:str,content_hash:str,size_bytes:int,columns:list[str],rows:list[dict[str,Any]],actor:str,source_type:str="file",source_uri:str|None=None)->dict[str,Any]:
        import_id=str(uuid.uuid4())
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("""INSERT INTO extension_data_imports(id,name,source_type,source_uri,file_format,original_filename,status,row_count,column_names,content_hash,size_bytes,created_by) VALUES (%s,%s,%s,%s,%s,%s,'staged',%s,%s,%s,%s,%s) RETURNING *""",(import_id,name,source_type,source_uri,file_format,filename,len(rows),psycopg2.extras.Json(columns),content_hash,size_bytes,actor))
                result=dict(cursor.fetchone())
                if rows:
                    values=[]
                    for index,row in enumerate(rows,1):values.append((import_id,index,psycopg2.extras.Json(row),hashlib.sha256(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()))
                    psycopg2.extras.execute_values(cursor,"INSERT INTO extension_data_records(import_id,ordinal,payload,row_hash) VALUES %s",values)
        return result
    def create_job(self,job_name:str,source:str,start_date:str|None,end_date:str|None)->dict[str,Any]:
        active=self._row("SELECT * FROM sync_jobs WHERE job_name=%s AND status IN ('pending','running') ORDER BY created_at DESC LIMIT 1",(job_name,))
        if active:raise ValueError("相同范围已有进行中的任务")
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:cursor.execute("INSERT INTO sync_jobs(job_name,source,start_date,end_date,status,message) VALUES (%s,%s,%s,%s,'pending','等待受控 worker') RETURNING *",(job_name,source,start_date,end_date));return dict(cursor.fetchone())
    def update_schedule(self,code:str,payload:dict[str,Any])->dict[str,Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:cursor.execute("UPDATE dataset_sync_schedules SET cron=COALESCE(%s,cron),timezone=COALESCE(%s,timezone),enabled=COALESCE(%s,enabled),catchup_days=COALESCE(%s,catchup_days),max_retries=COALESCE(%s,max_retries),updated_at=NOW() WHERE code=%s RETURNING *",(payload.get('cron'),payload.get('timezone'),payload.get('enabled'),payload.get('catchup_days'),payload.get('max_retries'),code));row=cursor.fetchone()
        if not row:raise ValueError("同步计划不存在")
        return dict(row)
    def _rows(self,query:str,params:Sequence[Any]=())->list[dict[str,Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:cursor.execute(query,params);return [dict(row) for row in cursor.fetchall()]
    def _row(self,query:str,params:Sequence[Any]=())->dict[str,Any]|None:
        rows=self._rows(query,params);return rows[0] if rows else None
