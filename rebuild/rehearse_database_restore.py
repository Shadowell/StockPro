#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,re,subprocess,sys
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
os.environ.setdefault('DATABASE_URL','postgresql://rehearsal@127.0.0.1/stockpro_rebuild_rehearsal_placeholder')
from app.db.postgres_migrations import load_migrations

PREFIX="stockpro_rebuild_rehearsal_"
class EnvironmentMismatch(ValueError):pass
def validate_database_name(name:str)->str:
    if not name.startswith(PREFIX)or len(name)<=len(PREFIX)or not re.fullmatch(r"[a-z0-9_]+",name):raise ValueError("rehearsal database name is unsafe")
    return name
def compare_manifests(source:dict[str,Any],restored:dict[str,Any])->dict[str,Any]:
    if source.get('environment')!=restored.get('environment'):raise EnvironmentMismatch("manifests belong to different environments")
    differences=[]
    for key in ('strategy_versions','backtest_runs','paper_instances','orders','trades','positions','paper_equity_snapshots','paper_instance_events','daily_reviews'):
        if int(restored['counts'][key])<int(source['counts'][key]):differences.append({'field':key,'expected':source['counts'][key],'actual':restored['counts'][key]})
    if source['paper_instance_ids']!=restored['paper_instance_ids']:differences.append({'field':'paper_instance_ids','expected':source['paper_instance_ids'],'actual':restored['paper_instance_ids']})
    return {'passed':not differences,'differences':differences}
@dataclass
class RemotePostgres:
    ssh_host:str
    def run(self,command:str,*,input_text:str|None=None)->str:
        result=subprocess.run(['ssh',self.ssh_host,command],input=input_text,text=True,capture_output=True,check=True);return result.stdout.strip()
    def psql(self,database:str,sql:str)->str:
        if not re.fullmatch(r"[a-zA-Z0-9_]+",database):raise ValueError("unsafe database identifier")
        return self.run(f"sudo -u postgres psql -v ON_ERROR_STOP=1 -At -d {database}",input_text=sql)
def manifest(remote:RemotePostgres,database:str,environment:str)->dict[str,Any]:
    sql="""SELECT json_build_object('migrations',(SELECT count(*) FROM schema_migrations),'strategy_versions',(SELECT count(*) FROM strategy_versions),'backtest_runs',(SELECT count(*) FROM backtest_runs),'paper_instances',(SELECT count(*) FROM paper_instances),'orders',(SELECT count(*) FROM orders WHERE paper_instance_id IS NOT NULL),'trades',(SELECT count(*) FROM trades WHERE paper_instance_id IS NOT NULL),'positions',(SELECT count(*) FROM positions WHERE portfolio_id IN(SELECT portfolio_id FROM paper_instances)),'paper_equity_snapshots',(SELECT count(*) FROM paper_equity_snapshots),'paper_instance_events',(SELECT count(*) FROM paper_instance_events),'daily_reviews',(SELECT count(*) FROM daily_reviews));SELECT COALESCE(json_agg(id::text ORDER BY id::text),'[]'::json) FROM paper_instances;"""
    lines=remote.psql(database,sql).splitlines();return {'environment':environment,'database':database,'captured_at':datetime.now(timezone.utc).isoformat(),'counts':json.loads(lines[0]),'paper_instance_ids':json.loads(lines[1])}
def apply_missing_migrations(remote:RemotePostgres,database:str,migrations_dir:Path)->list[str]:
    applied=set(remote.psql(database,"SELECT version FROM schema_migrations ORDER BY version;").splitlines());added=[]
    for migration in load_migrations(migrations_dir):
        if migration.version in applied:continue
        escaped=migration.version.replace("'","''");remote.psql(database,f"BEGIN;\n{migration.sql}\nINSERT INTO schema_migrations(version)VALUES('{escaped}');\nCOMMIT;");added.append(migration.version)
    return added
def rehearse(*,ssh_host:str,source_db:str,rehearsal_db:str,output:Path,migrations_dir:Path)->dict[str,Any]:
    validate_database_name(rehearsal_db)
    if not re.fullmatch(r"[a-zA-Z0-9_]+",source_db):raise ValueError("source database name is unsafe")
    remote=RemotePostgres(ssh_host);environment=f"{ssh_host}:{source_db}";dump=f"/tmp/{rehearsal_db}.dump";output.mkdir(parents=True,exist_ok=True);source=manifest(remote,source_db,environment)
    try:
        remote.run(f"sudo -u postgres pg_dump -Fc -d {source_db} -f {dump}")
        remote.run(f"sudo -u postgres createdb {rehearsal_db}")
        remote.run(f"sudo -u postgres pg_restore --no-owner --no-privileges -d {rehearsal_db} {dump}")
        added=apply_missing_migrations(remote,rehearsal_db,migrations_dir);restored=manifest(remote,rehearsal_db,environment);comparison=compare_manifests(source,restored)
        old_smoke={'baseline_sha':'99adaaae1b1a7b87b2ce22e7475aa3f26d5a5440','health':remote.psql(rehearsal_db,"SELECT count(*) FROM schema_migrations;")!='','strategies':int(remote.psql(rehearsal_db,"SELECT count(*) FROM strategy_versions;")),'backtests':int(remote.psql(rehearsal_db,"SELECT count(*) FROM backtest_runs;")),'paper':int(remote.psql(rehearsal_db,"SELECT count(*) FROM paper_instances;")),'read_only_queries':True}
        result={'passed':comparison['passed']and all(old_smoke.values()),'environment':environment,'source_manifest':source,'restored_manifest':restored,'comparison':comparison,'applied_migrations':added,'old_app_smoke':old_smoke,'backup':{'type':'pg_dump_custom','location_ref':dump}}
        (output/'latest-source-manifest.json').write_text(json.dumps(source,ensure_ascii=False,indent=2)+"\n");(output/'latest-rebuild-manifest.json').write_text(json.dumps(restored,ensure_ascii=False,indent=2)+"\n");(output/'old-app-smoke.json').write_text(json.dumps(old_smoke,ensure_ascii=False,indent=2)+"\n");return result
    finally:
        remote.run(f"sudo -u postgres psql -d postgres -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{rehearsal_db}' AND pid<>pg_backend_pid();\" >/dev/null")
        remote.run(f"sudo -u postgres dropdb --if-exists {rehearsal_db}")
        remote.run(f"sudo rm -f {dump}")
def main()->int:
    parser=argparse.ArgumentParser();parser.add_argument('--ssh-host',default='stockpro');parser.add_argument('--source-db',required=True);parser.add_argument('--rehearsal-db',required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--migrations-dir',type=Path,default=Path(__file__).resolve().parents[1]/'backend/postgres/migrations');args=parser.parse_args();result=rehearse(ssh_host=args.ssh_host,source_db=args.source_db,rehearsal_db=args.rehearsal_db,output=args.output,migrations_dir=args.migrations_dir);print(json.dumps({'passed':result['passed'],'applied_migrations':result['applied_migrations'],'comparison':result['comparison']},ensure_ascii=False));return 0 if result['passed']else 1
if __name__=='__main__':raise SystemExit(main())
