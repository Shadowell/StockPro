"""封存已有全市场日线为研究快照（供策略回测使用）。"""
import sys, time, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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

ranges = [
    ('2025-07-28', '2025-12-31'),
    ('2026-01-01', '2026-06-30'),
]
for start, end in ranges:
    t0 = time.time()
    # 只用区间内实际有封存资格数据的 symbol（避免新股/缺口触发质量门禁）
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT symbol FROM kline_history
                WHERE timeframe='1d' AND trade_date BETWEEN %s AND %s
                  AND collected_at IS NOT NULL
                  AND source IN ('tushare','akshare')
                  AND symbol = ANY(%s)
                GROUP BY symbol HAVING COUNT(*) >= 60
                """,
                (start, end, symbols),
            )
            usable = [r[0] for r in cur.fetchall()]
    print(f'{start}~{end}: usable symbols {len(usable)}/{len(symbols)}', flush=True)
    try:
        r = svc.publish_daily_bar_range(start, end, usable, minimum_rows_per_symbol=50,
                                        reference_dataset_codes=(
                                            "security_master", "trade_calendar", "adjustment_factors",
                                            "daily_valuation", "suspensions", "price_limits",
                                            "benchmark_bars", "corporate_actions", "universe_history"))
        snap = r.get('snapshot') or {}
        print(json.dumps({'range': f'{start}~{end}', 'status': r.get('status'),
                          'snapshot_id': snap.get('id'), 'elapsed_s': round(time.time()-t0, 1)},
                         ensure_ascii=False), flush=True)
    except Exception as exc:
        print(json.dumps({'range': f'{start}~{end}', 'error': str(exc)[:250]}, ensure_ascii=False), flush=True)
db.close_pool()
print('DONE', flush=True)
