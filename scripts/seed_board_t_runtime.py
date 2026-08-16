#!/usr/bin/env python3
"""Register the 20 daily-bar strategies and submit sealed quick/full jobs."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "strategies"
API = "http://127.0.0.1:4445/api"
COST_MODEL_ID = "8d3c5ef8-39a8-4d84-80a6-f1c8fad913d7"
DATASET_ID = 10
UNIVERSE_ID = 1
FACTOR_ID = 4
POOL_ID = 5
START_DATE = "2023-01-03"
END_DATE = "2025-01-02"
FULL_START = "2024-10-08"

FILES = [
    "board_first_weak_to_strong.py",
    "board_consecutive_relay.py",
    "board_broken_reclaim.py",
    "board_space_avoid_yizi.py",
    "board_first_volume.py",
    "board_high_ladder.py",
    "board_limit_down_bounce.py",
    "board_seal_quality.py",
    "t_gap_down_recovery.py",
    "t_gap_up_hold.py",
    "t_lower_shadow.py",
    "t_close_strength.py",
    "t_amplitude_reversion.py",
    "t_volume_yang.py",
    "t_tight_breakout.py",
    "t_overnight_follow.py",
    "daily_reversal_3d.py",
    "daily_momentum_20d.py",
    "daily_ma_breakout.py",
    "daily_low_vol_defense.py",
]


def request_json(method: str, path: str, token: str | None = None, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail[:800]}") from exc


def login() -> str:
    result = request_json("POST", "/auth/admin/login", payload={"username": "admin", "password": "stockpro123"})
    return str(result["access_token"])


def strategy_meta(filename: str) -> tuple[str, str]:
    text = (STRATEGIES / filename).read_text(encoding="utf-8")
    doc = text.split('"""', 2)[1].strip()
    name = doc.split("。", 1)[0].strip()
    return name, " ".join(doc.split())


def register(token: str) -> list[dict]:
    registered = []
    for filename in FILES:
        name, description = strategy_meta(filename)
        code = (STRATEGIES / filename).read_text(encoding="utf-8")
        created = request_json(
            "POST",
            "/strategy",
            token,
            {
                "name": name,
                "script_content": code,
                "description": description,
                "data_dependencies": ["daily_bars"],
            },
        )
        version = created.get("strategy_version") or {}
        validation = created.get("validation") or {}
        if not validation.get("valid") and version.get("validation_status") != "valid":
            raise RuntimeError(f"{name} invalid: {validation}")
        print(f"registered {name} version={version.get('id')}", flush=True)
        registered.append({"name": name, "filename": filename, "version_id": version["id"], "reused": False})
    return registered


def pool_symbols(token: str) -> list[str]:
    snapshot = request_json("GET", f"/pool-snapshots/{POOL_ID}", token)
    return [str(item["symbol"]) for item in snapshot.get("members") or []]


def submit_jobs(token: str, registered: list[dict], mode: str, start_date: str) -> list[dict]:
    symbols = pool_symbols(token)
    if len(symbols) != 20:
        raise RuntimeError(f"pool 5 should have 20 members, got {len(symbols)}: {symbols}")
    jobs = []
    for item in registered:
        payload = {
            "strategy_version_id": item["version_id"],
            "dataset_snapshot_id": DATASET_ID,
            "universe_snapshot_id": UNIVERSE_ID,
            "factor_snapshot_id": FACTOR_ID,
            "pool_snapshot_id": POOL_ID,
            "symbols": symbols,
            "start_date": start_date,
            "end_date": END_DATE,
            "initial_cash": 1_000_000,
            "cost_model_id": COST_MODEL_ID,
            "benchmark_code": "000300.SH",
            "run_mode": mode,
            "name": f"[{mode}] {item['name']}",
        }
        job = request_json("POST", "/backtest/jobs", token, payload)
        jobs.append({
            "name": item["name"],
            "job_id": job.get("job_id") or job.get("id"),
            "run_id": job.get("backtest_run_id") or job.get("run_id"),
            "status": job.get("status"),
        })
        print(f"queued {item['name']} job={job.get('job_id')}", flush=True)
    return jobs


def wait_jobs(token: str, jobs: list[dict], timeout_sec: int = 5400) -> list[dict]:
    deadline = time.time() + timeout_sec
    remaining = {item["job_id"]: item for item in jobs if item.get("job_id")}
    finished = []
    while remaining and time.time() < deadline:
        listing = request_json("GET", "/backtest/jobs?limit=200", token)
        rows = listing.get("items") if isinstance(listing, dict) else listing
        by_id = {str(item.get("job_id")): item for item in rows or []}
        for job_id in list(remaining):
            detail = by_id.get(job_id)
            if not detail:
                continue
            status = str(detail.get("status") or "")
            if status in {"success", "failed", "cancelled", "interrupted"}:
                item = remaining.pop(job_id)
                item.update({
                    "status": status,
                    "run_id": detail.get("backtest_run_id") or detail.get("run_id"),
                    "message": detail.get("message"),
                })
                finished.append(item)
                print(f"{status}: {item['name']} job={job_id} run={item.get('run_id')}", flush=True)
        if remaining:
            time.sleep(45)
    for item in remaining.values():
        item["status"] = "timeout"
        finished.append(item)
    return finished


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["register", "quick", "full", "wait"], default="quick")
    parser.add_argument("--jobs", default="")
    parser.add_argument("--versions", default="")
    parser.add_argument("--timeout", type=int, default=5400)
    args = parser.parse_args()
    token = login()
    if args.mode == "wait":
        jobs = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
        print(json.dumps(wait_jobs(token, jobs, timeout_sec=args.timeout), ensure_ascii=False, indent=2))
        return
    if args.versions:
        registered = json.loads(Path(args.versions).read_text(encoding="utf-8"))
        if isinstance(registered, dict):
            registered = registered.get("registered") or registered.get("items") or []
    else:
        registered = register(token)
        print(json.dumps({"registered": registered}, ensure_ascii=False, indent=2))
    if args.mode == "register":
        return
    start_date = START_DATE if args.mode == "quick" else FULL_START
    jobs = submit_jobs(token, registered, args.mode, start_date)
    print(json.dumps({"jobs": jobs}, ensure_ascii=False, indent=2))
    print(json.dumps({"finished": wait_jobs(token, jobs)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
