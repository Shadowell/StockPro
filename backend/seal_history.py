import sys, time, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or '.')
from app.db.postgres_db import PostgresDatabase
from app.services.dataset_snapshot_service import DatasetSnapshotService

db = PostgresDatabase(os.environ['DATABASE_URL'])
svc = DatasetSnapshotService(db)
with db.get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT payload->>'symbol' FROM dataset_partition_records r
            JOIN dataset_partitions p ON p.id=r.partition_id
            JOIN dataset_definitions d ON d.id=p.dataset_id
            WHERE d.code='universe_history' AND p.created_at > NOW() - INTERVAL '7 days'
            ORDER BY 1""")
        symbols = [r[0] for r in cur.fetchall()]
print('universe symbols:', len(symbols), flush=True)
quarters = [('2025-01-01','2025-03-31'),('2025-04-01','2025-06-30'),
            ('2025-07-01','2025-09-30'),('2025-10-01','2025-12-31'),
            ('2026-01-01','2026-03-31'),('2026-04-01','2026-06-30')]
results = []
t0 = time.time()
for start, end in quarters:
    try:
        r = svc.publish_daily_bar_range(start, end, symbols, minimum_rows_per_symbol=1,
                                        reference_dataset_codes=())
        results.append({'range': f'{start}~{end}', 'status': r.get('status'),
                        'snapshot': (r.get('snapshot') or {}).get('id')})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    except Exception as exc:
        results.append({'range': f'{start}~{end}', 'error': str(exc)[:200]})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
print(json.dumps({'elapsed_s': round(time.time()-t0, 1)}, ensure_ascii=False), flush=True)
db.close_pool()
