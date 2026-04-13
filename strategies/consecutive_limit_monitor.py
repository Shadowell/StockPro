# 连板股监控 - 监控多板股票
import akshare as ak
import json
from datetime import datetime

try:
    today = datetime.now().strftime('%Y%m%d')
    df = ak.stock_zt_pool_em(date=today)
    
    if df is None or df.empty:
        print(json.dumps({"stocks": [], "error": "暂无涨停数据"}, ensure_ascii=False))
    else:
        # 筛选连板数>=2的股票
        if '连板数' in df.columns:
            df['连板数'] = pd.to_numeric(df['连板数'], errors='coerce').fillna(0)
            df = df[df['连板数'] >= 2]
            # 按连板数降序排序
            df = df.sort_values('连板数', ascending=False)
        
        # 过滤主板
        df = df[~df['名称'].str.contains('ST', na=False)]
        df = df[~df['代码'].astype(str).str.startswith(('30', '688', '8', '43', '9'))]
        
        result = df.head(20)
        
        output = {
            "stocks": [
                {"code": str(row['代码']), "name": str(row['名称']), 
                 "reason": f"{int(row.get('连板数', 0))}连板 涨停{row.get('涨停统计', {}).get('days', '')}"}
                for _, row in result.iterrows()
            ]
        }
        print(json.dumps(output, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"stocks": [], "error": str(e)}, ensure_ascii=False))
