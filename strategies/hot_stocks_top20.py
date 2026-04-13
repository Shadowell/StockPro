# 热门股票TOP20
import akshare as ak
import json

try:
    df = ak.stock_hot_rank_em()
    
    if df is None or df.empty:
        print(json.dumps({"stocks": [], "error": "暂无热门股票数据"}, ensure_ascii=False))
    else:
        # 过滤主板
        filtered = []
        for _, row in df.iterrows():
            code = str(row.get('代码', ''))
            name = str(row.get('股票名称', row.get('名称', '')))
            
            if 'ST' in name:
                continue
            if code.startswith(('30', '688', '8', '43', '9')):
                continue
            
            rank = row.get('当前排名', row.get('序号', 0))
            filtered.append({
                "code": code,
                "name": name,
                "reason": f"热度排名第{rank}名"
            })
            
            if len(filtered) >= 20:
                break
        
        print(json.dumps({"stocks": filtered}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"stocks": [], "error": str(e)}, ensure_ascii=False))
