#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

if __package__ in {None, ""}: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rebuild.capture_baseline import capture_baseline
from rebuild.verify_paper_continuity import compare_continuity

BITPRO_SOURCE_SHA="00517963e90f463e608289b0277fe598bd82d9bf"
REQUIRED_ROUTES={"/","/market","/pools","/factors","/strategy","/backtest","/paper","/watch","/signals","/monitor","/review","/data","/ai-lab"}

@dataclass(frozen=True)
class CompletionAuditResult:
    passed:bool
    requirements:tuple[dict[str,object],...]
    blockers:tuple[str,...]
    evidence:Mapping[str,Mapping[str,object]]

def audit(requirements:list[dict[str,object]],evidence:Mapping[str,Mapping[str,object]],*,mode:str="pre-deploy")->CompletionAuditResult:
    blockers=[];rows=[]
    for requirement in requirements:
        item=dict(requirement);proof=dict(evidence.get(str(item["id"]),{}));status=str(proof.get("status")or"missing");item["status"]=status;rows.append(item)
        allowed_pending=mode=="pre-deploy"and item["id"]=="DEPLOY-001"and status=="pending_final_confirmation"
        if bool(item.get("required"))and status!="passed"and not allowed_pending:blockers.append(str(item["id"]))
    return CompletionAuditResult(not blockers,tuple(rows),tuple(blockers),evidence)

def _sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def _pytest_evidence(path:Path)->dict[str,object]:
    if not path.exists():return {"status":"missing","reason":"backend junit missing"}
    root=ET.parse(path).getroot();suites=[root]if root.tag=="testsuite"else list(root.findall("testsuite"));tests=sum(int(suite.attrib.get("tests",0))for suite in suites);failures=sum(int(suite.attrib.get("failures",0))+int(suite.attrib.get("errors",0))for suite in suites)
    return {"status":"passed"if tests>0 and failures==0 else"failed","tests":tests,"failures":failures,"sha256":_sha(path)}
def _e2e_evidence(path:Path)->dict[str,object]:
    if not path.exists():return {"status":"missing","reason":"Playwright JSON missing"}
    payload=json.loads(path.read_text());stats=payload.get("stats",{});failed=int(stats.get("unexpected",0));expected=int(stats.get("expected",0))
    return {"status":"passed"if expected>0 and failed==0 else"failed","expected":expected,"failed":failed,"sha256":_sha(path)}

def collect(root:Path,mode:str)->dict[str,dict[str,object]]:
    artifacts=root/".codex-artifacts/rebuild";safety_path=artifacts/"safety.json";junit=artifacts/"backend-tests.xml";e2e=root/"frontend/test-results/e2e-results.json"
    safety=json.loads(safety_path.read_text())if safety_path.exists()else{};pytest_ev=_pytest_evidence(junit);e2e_ev=_e2e_evidence(e2e)
    source_manifest_path=root/"docs/reference/bitpro-baseline/source.json";source_manifest=json.loads(source_manifest_path.read_text())if source_manifest_path.exists()else{};source_repo=Path(str(source_manifest.get("source_repo")or""));source_fields_ok=source_manifest.get("source_sha")==BITPRO_SOURCE_SHA and set(source_manifest.get("copied_roots")or[])=={"backend","frontend","packages","scripts","tests"}
    try:subprocess.run(["git","cat-file","-e",f"{BITPRO_SOURCE_SHA}^{{commit}}"],cwd=source_repo,check=True,capture_output=True);base_status="passed"if source_fields_ok else"failed"
    except (subprocess.CalledProcessError,OSError):base_status="failed"
    database_url=os.environ.get("DATABASE_URL","");db_ok=database_url.startswith("postgresql://")and database_url.endswith("/stockpro_bitpro_rebase_dev")
    db_evidence:dict[str,object]={"status":"failed"if not db_ok else"passed","target":"stockpro_bitpro_rebase_dev"if db_ok else"invalid"}
    paper_ev:dict[str,object]={"status":"missing"}
    if db_ok:
        try:
            import psycopg
            with psycopg.connect(database_url,options="-c default_transaction_read_only=on")as connection:
                with connection.cursor()as cursor:cursor.execute("SELECT count(*) FROM schema_migrations");migrations=int(cursor.fetchone()[0]);cursor.execute("SELECT count(*) FROM instrument_definitions WHERE asset_class='future'");future_count=int(cursor.fetchone()[0])
            db_evidence.update({"status":"passed"if migrations==38 else"failed","migrations":migrations})
            baseline=json.loads((artifacts/"baseline.json").read_text());current=capture_baseline(database_url,root);continuity=compare_continuity(baseline,current);paper_ev={"status":"passed"if continuity.passed else"failed","differences":[asdict(item)for item in continuity.differences],"counts":current["paper"]}
        except Exception as error:db_evidence={"status":"failed","error":str(error)};future_count=-1
    else:future_count=-1
    captures=[]
    for path in sorted((root/"docs/screenshots").glob("rebuild-wave-*-capture.json")):
        payload=json.loads(path.read_text());captures.extend(payload.get("pages",[]))
    routes={str(item.get("route")or"").split("?",1)[0]for item in captures};ui_ok=REQUIRED_ROUTES.issubset(routes)and e2e_ev["status"]=="passed"
    active_total=sum(int(safety.get(key,0))for key in("registered_private_exchange_routes","active_sqlite_repository","active_versioned_api_routes","registered_live_routes","registered_crypto_jobs"))
    return {
        "BASE-001":{"status":base_status,"source_sha":BITPRO_SOURCE_SHA,"manifest_sha256":_sha(source_manifest_path)if source_manifest_path.exists()else None},
        "API-001":{"status":"passed"if safety.get("passed")and int(safety.get("active_versioned_api_routes",1))==0 else"failed","safety_sha256":_sha(safety_path)if safety_path.exists()else None},
        "DB-001":db_evidence,
        "PAPER-001":paper_ev,
        "SAFE-001":{"status":"passed"if safety.get("passed")and active_total==0 else"failed","active_findings":active_total},
        "UI-001":{"status":"passed"if ui_ok else"failed","routes":sorted(routes),"e2e":e2e_ev},
        "ASHARE-001":{"status":"passed"if pytest_ev["status"]=="passed"else"failed","backend_tests":pytest_ev},
        "FUTURE-001":{"status":"passed"if future_count==0 and e2e_ev["status"]=="passed"else"failed","future_records":future_count,"routes_hidden":True},
        "DEPLOY-001":{"status":"pending_final_confirmation"if mode=="pre-deploy"else"missing"},
    }

def main()->int:
    parser=argparse.ArgumentParser();parser.add_argument("--mode",choices=("pre-deploy","post-deploy"),default="pre-deploy");parser.add_argument("--output",type=Path,required=True);parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1]);args=parser.parse_args()
    requirements=json.loads((args.root/"rebuild/contracts/rebuild-requirements.json").read_text());result=audit(requirements,collect(args.root,args.mode),mode=args.mode);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(asdict(result),ensure_ascii=False,indent=2,default=str)+"\n");print(json.dumps({"passed":result.passed,"blockers":result.blockers},ensure_ascii=False));return 0 if result.passed else 1
if __name__=="__main__":raise SystemExit(main())
