# 涨停板监控
import akshare as ak
import json

df = ak.stock_zh_a_spot_em()

# 过滤主板
df = df[~df['名称'].str.contains('ST', na=False)]
df = df[~df['代码'].str.startswith(('30', '688', '8', '43', '9'))]

# 筛选涨停（涨幅>=9.8%）
df = df[df['涨跌幅'] >= 9.8]

# 按成交额排序
result = df.nlargest(20, '成交额')

output = {
    "stocks": [
        {"code": row['代码'], "name": row['名称'], "reason": f"涨停 成交{row['成交额']/10**8:.1f}亿"}
        for _, row in result.iterrows()
    ]
}
print(json.dumps(output, ensure_ascii=False))
