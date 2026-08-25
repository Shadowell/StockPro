"""只补齐晋级门禁必需的数据：price_limits（涨跌停价）+ benchmark_bars（基准指数）。"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.db.postgres_db import PostgresDatabase
from app.services.reference_dataset_sync_service import ReferenceDatasetSyncService
from app.services.dataset_snapshot_service import DatasetSnapshotService
from app.services.tushare_provider import market_data_provider

start, end = sys.argv[1], sys.argv[2]
database = PostgresDatabase(os.environ['DATABASE_URL'])
references = ReferenceDatasetSyncService(database)
snapshots = DatasetSnapshotService(database)

open_dates = market_data_provider.trade_cal_open_dates(start, end)
print(f"open dates: {len(open_dates)}", flush=True)

t0 = time.time()
ok = fail = 0
for i, trade_date in enumerate(open_dates):
    compact = trade_date.replace('-', '')
    try:
        # 1) 涨跌停价（DATA_QUALITY_PASS 必需）
        result = references.catalog_service.sync_endpoint(
            "stk_limit",
            params={"trade_date": compact},
            fields=["ts_code", "trade_date", "pre_close", "up_limit", "down_limit"],
            include_records=True,
        )
        from app.services.reference_dataset_sync_service import normalise_price_limit_rows, PRICE_LIMIT_FIELDS
        rows, issues = normalise_price_limit_rows(result.get("records") or [], trade_date)
        references.snapshot_service.publish_normalized_partition(
            "price_limits", f"price_limits:{trade_date}:tushare", rows,
            start_date=trade_date, end_date=trade_date,
            request_params={"endpoint": "stk_limit", "endpoint_run_id": result.get("run_id"), "trade_date": compact},
            quality_issues=issues,
        )
        ok += 1
    except Exception as exc:
        fail += 1
        print(f"ERR {trade_date}: {str(exc)[:100]}", flush=True)
    if (i + 1) % 10 == 0:
        print(f"progress {i+1}/{len(open_dates)} ok={ok} fail={fail} elapsed={round(time.time()-t0,1)}s", flush=True)

# 2) 基准指数日线：一次拉全区间（index_daily 按 ts_code）
print("syncing benchmarks...", flush=True)
for ts_code, symbol in (("000300.SH", "SH_000300"), ("399001.SZ", "SZ_399001"), ("000001.SH", "SH_000001"), ("399006.SZ", "SZ_399006")):
    try:
        result = references.catalog_service.sync_endpoint(
            "index_daily",
            params={"ts_code": ts_code, "start_date": start.replace('-', ''), "end_date": end.replace('-', '')},
            fields=["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"],
            include_records=True,
        )
        records = result.get("records") or []
        # 归一化为 benchmark_bars 行
        normalized = []
        for r in records:
            td = str(r.get("trade_date") or "")
            if len(td) == 8:
                td = f"{td[:4]}-{td[4:6]}-{td[6:]}"
            normalized.append({
                "symbol": symbol, "code": symbol, "name": "", "trade_date": td,
                "close": r.get("close"), "source": "tushare",
                "collected_at": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
            })
        pub = snapshots.publish_normalized_partition(
            "benchmark_bars", f"benchmark_bars:{start}:{end}:{symbol}", normalized,
            start_date=start, end_date=end,
            request_params={"endpoint": "index_daily", "ts_code": ts_code},
        )
        print(f"benchmark {symbol}: {pub.get('status')} rows={len(normalized)}", flush=True)
    except Exception as exc:
        print(f"benchmark ERR {symbol}: {str(exc)[:150]}", flush=True)

print(json.dumps({"ok": ok, "fail": fail, "elapsed_s": round(time.time()-t0,1)}, ensure_ascii=False), flush=True)
