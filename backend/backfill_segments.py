"""分段回填全市场日线（带进度输出）。"""
import sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.db.postgres_db import PostgresDatabase
from app.services.kline_sync_service import KlineSyncService

db = PostgresDatabase(os.environ['DATABASE_URL'])
svc = KlineSyncService(db)

segments = [
    ('2025-01-01', '2025-03-31'),
    ('2025-04-01', '2025-06-30'),
    ('2025-07-01', '2025-09-30'),
    ('2025-10-01', '2025-12-31'),
]
for start, end in segments:
    t0 = time.time()
    try:
        job = svc.create_market_daily_sync_job(
            start_date=start, end_date=end,
            job_name=f'backfill-{start[:7]}',
        )
        result = svc.run_job(job['job_id'])
        print(f"{start}..{end}: {result.get('status')} completed={result.get('completed_items')} "
              f"failed={result.get('failed_items')} elapsed={round(time.time()-t0,1)}s", flush=True)
    except Exception as exc:
        print(f"{start}..{end}: ERROR {str(exc)[:150]}", flush=True)
print('ALL DONE', flush=True)
db.close_pool()
