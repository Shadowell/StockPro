"""补齐指定区间的日频参考数据集（辅助+基准+日历），使完整回测可晋级。

用法：DATABASE_URL=... venv/bin/python backfill_references.py <start> <end>
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.postgres_db import PostgresDatabase
from app.services.reference_dataset_sync_service import ReferenceDatasetSyncService
from app.services.tushare_provider import market_data_provider


def main() -> int:
    start, end = sys.argv[1], sys.argv[2]
    database = PostgresDatabase(os.environ["DATABASE_URL"])
    references = ReferenceDatasetSyncService(database)

    open_dates = market_data_provider.trade_cal_open_dates(start, end)
    print(f"open dates {start}..{end}: {len(open_dates)}", flush=True)

    t0 = time.time()
    ok = skip = fail = 0
    errors = []
    for i, trade_date in enumerate(open_dates):
        try:
            aux = references.sync_daily_auxiliary_datasets(trade_date)
            bad = [code for code, item in aux.items() if item.get("status") not in ("published", "sealed", "skipped_empty")]
            if bad:
                fail += 1
                errors.append((trade_date, f"blocked:{','.join(bad)}"))
            else:
                ok += 1
        except Exception as exc:
            message = str(exc)[:120]
            if "empty" in message.lower() or "没有" in message:
                skip += 1
            else:
                fail += 1
                errors.append((trade_date, message))
        if (i + 1) % 20 == 0:
            elapsed = round(time.time() - t0, 1)
            print(f"progress {i+1}/{len(open_dates)} ok={ok} fail={fail} elapsed={elapsed}s", flush=True)

    print(json.dumps({"ok": ok, "skip": skip, "fail": fail,
                      "sample_errors": errors[:8], "elapsed_s": round(time.time()-t0, 1)},
                     ensure_ascii=False), flush=True)
    db_close = getattr(database, "close_pool", None)
    if db_close:
        db_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
