"""批量注册策略库到 StockPro（创建版本 + 验证 + 快速诊断回测）。

用法：
    cd backend && DATABASE_URL=... venv/bin/python register_strategies.py [--quick]

前置：backend 服务已在 4445 运行，管理员凭据在 .env。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib import request as urlreq


BASE = os.environ.get("STOCKPRO_API", "http://127.0.0.1:4445/api")
LIB_DIR = Path(__file__).resolve().parent / "strategy_library"


def env_value(key: str, default: str = "") -> str:
    text = Path(__file__).parent.joinpath(".env").read_text()
    match = re.search(rf"^{key}=(.*)$", text, re.M)
    return match.group(1).strip() if match else default


def api_call(method: str, path: str, payload=None, token=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urlreq.Request(f"{BASE}{path}", data=body, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urlreq.urlopen(req, timeout=300) as response:
        return json.loads(response.read().decode())


def main() -> int:
    quick = "--quick" in sys.argv
    username = env_value("ADMIN_USERNAME", "admin")
    password = env_value("ADMIN_PASSWORD")
    login = api_call("POST", "/auth/admin/login", {"username": username, "password": password})
    token = login.get("access_token")

    existing = {item["name"]: item["id"] for item in api_call("GET", "/strategies", token=token)["items"]}
    results = []
    for path in sorted(LIB_DIR.glob("*.py")):
        code = path.read_text()
        name_match = re.search(r'"""(\[A股\][^\n]+)', code)
        name = name_match.group(1).strip() if name_match else path.stem
        print(f"--- {path.stem}: {name}", flush=True)
        try:
            validation = api_call("POST", "/strategies/validate", {"script_content": code}, token)
            valid = bool(validation.get("valid"))
            issues = validation.get("issues") or []
            if not valid:
                print(f"    INVALID: {issues[:3]}", flush=True)
                results.append({"file": path.stem, "status": "invalid", "issues": issues})
                continue
            version_id = None
            if name in existing:
                parent_id = existing[name]
                created = api_call("POST", f"/strategies/{parent_id}/versions",
                                   {"script_content": code, "description": f"批量注册 {path.stem}"}, token)
                version = created.get("version") or created
                version_id = str(version.get("id") or "")
            else:
                created = api_call("POST", "/strategies",
                                   {"name": name, "description": f"{path.stem} 策略库注册", "script_content": code}, token)
                item = created.get("strategy") or created
                version = (item.get("version") or {}) if isinstance(item, dict) else {}
                version_id = str(version.get("id") or item.get("id") or "")
                existing[name] = str(item.get("id") or "")
            print(f"    version {version_id} valid={valid}", flush=True)
            entry = {"file": path.stem, "name": name, "version_id": version_id, "status": "registered"}
            if quick and version_id:
                run = api_call("POST", f"/strategies/{version_id}/quick-run", {}, token)
                metrics = ((run.get("run") or {}).get("core_metrics") if isinstance(run, dict) else None) or run.get("metrics") or {}
                entry["quick_run"] = {
                    "run_id": run.get("run_id") or (run.get("run") or {}).get("id"),
                    "status": run.get("status"),
                    "total_return": metrics.get("total_return"),
                    "trade_count": metrics.get("total_trades"),
                }
                print(f"    quick: {entry['quick_run']}", flush=True)
            results.append(entry)
        except Exception as exc:
            print(f"    ERROR: {exc}", flush=True)
            results.append({"file": path.stem, "status": "error", "error": str(exc)[:200]})
    out = Path(__file__).parent / "strategy_library" / "registration_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print(json.dumps(results, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
