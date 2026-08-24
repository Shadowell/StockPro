"""把 strategy_library 的最新代码注册为每个策略的新不可变版本。"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.postgres_db import PostgresDatabase
from app.services.strategy_application_service import StrategyApplicationService


def main() -> int:
    database = PostgresDatabase(os.environ["DATABASE_URL"])
    from app.core.app_context import build_app_context
    context = build_app_context()
    service = StrategyApplicationService(context.repositories.strategies)
    database = context.repositories.data.database
    lib = Path(__file__).parent / "strategy_library"
    results = []
    for path in sorted(lib.glob("*.py")):
        code = path.read_text()
        match = re.search(r'"""(\[A股\][^\n]+)', code)
        name = match.group(1).strip().rstrip("。") if match else None
        if not name:
            print(f"skip {path.stem}: no name", flush=True)
            continue
        # 数据库里同名（可能带句号）
        row = database._fetch_one(
            "SELECT id FROM strategy_versions WHERE name LIKE %s ORDER BY created_at DESC LIMIT 1",
            (name + "%",),
        )
        if not row:
            print(f"skip {path.stem}: not found ({name})", flush=True)
            continue
        try:
            created = service.create_version(str(row["id"]), {
                "script_content": code,
                "description": "None 防护加固版",
            })
            version = created.get("version") or created
            validation = version.get("validation_status") or created.get("validation_status")
            print(json.dumps({"file": path.stem, "new_version": str(version.get('id')), "validation": str(validation)}, ensure_ascii=False), flush=True)
            results.append({"file": path.stem, "version_id": str(version.get("id")), "status": str(validation)})
        except Exception as exc:
            print(json.dumps({"file": path.stem, "error": str(exc)[:200]}, ensure_ascii=False), flush=True)
    out = Path(__file__).parent / "strategy_library" / "upgrade_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
