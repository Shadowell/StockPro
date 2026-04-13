# 主板涨幅TOP10 - 快速筛选
import akshare as ak
import json

df = ak.stock_zh_a_spot_em()

# 过滤主板：排除ST、创业板、科创板、北交所
df = df[~df['名称'].str.contains('ST', na=False)]
df = df[~df['代码'].str.startswith(('30', '688', '8', '43', '9'))]

# 按涨幅排序取前10
result = df.nlargest(10, '涨跌幅')

output = {
    "stocks": [
        {"code": row['代码'], "name": row['名称'], "reason": f"涨{row['涨跌幅']:.2f}%"}
        for _, row in result.iterrows()
    ]
}
print(json.dumps(output, ensure_ascii=False))
