# 平底放量突破首板策略
# 策略逻辑：
# 1. 排除ST股、创业板、科创板、北交所
# 2. 总市值30-160亿，股价>5元
# 3. 近20天无涨停（平底）
# 4. 当日成交量 > 近20天每天的1.75倍（放量）
# 5. 开盘价 < 当前价（低开高走，突破）
# 适合做首板突破

import akshare as ak
import json
import pandas as pd
from datetime import datetime

# ====== 参数设置 ======
PERIOD_DAYS = 20          # 观察周期
PRICE_MIN = 5.0           # 最低价格
VOLUME_RATIO = 1.75       # 放量倍数阈值
MARKET_CAP_MIN = 30e8     # 最低市值30亿
MARKET_CAP_MAX = 160e8    # 最高市值160亿
LIMIT_UP_PCT = 9.8        # 涨停阈值
MAX_RESULTS = 20          # 最大返回数量

def get_trading_days(n):
    """获取最近n个交易日的起止日期"""
    try:
        trade_df = ak.tool_trade_date_hist_sina()
        trade_df['trade_date'] = pd.to_datetime(trade_df['trade_date'])
        today = datetime.now()
        past_days = trade_df[trade_df['trade_date'] < today].tail(n)['trade_date'].tolist()
        if len(past_days) >= 2:
            return past_days[0].strftime('%Y%m%d'), past_days[-1].strftime('%Y%m%d')
    except:
        pass
    return None, None

# 获取交易日期范围
start_date, end_date = get_trading_days(PERIOD_DAYS)
if not start_date:
    print(json.dumps({"stocks": [], "error": "无法获取交易日历"}, ensure_ascii=False))
    exit()

# 获取实时行情
try:
    df = ak.stock_zh_a_spot_em()
except Exception as e:
    print(json.dumps({"stocks": [], "error": f"获取行情失败: {e}"}, ensure_ascii=False))
    exit()

filtered = []
checked = 0

for _, row in df.iterrows():
    try:
        code = str(row['代码'])
        name = str(row['名称'])
        
        # 1. 排除非主板
        if 'ST' in name:
            continue
        if code.startswith(('30', '688', '43', '8', '9')):
            continue
        
        # 2. 市值和价格过滤
        market_cap = float(row['总市值'] or 0)
        price = float(row['最新价'] or 0)
        if market_cap < MARKET_CAP_MIN or market_cap > MARKET_CAP_MAX:
            continue
        if price < PRICE_MIN:
            continue
        
        # 3. 低开高走（开盘价 < 当前价）
        open_price = float(row['今开'] or 0)
        if open_price <= 0 or open_price >= price:
            continue
        
        # 4. 获取历史数据检查
        volume = float(row['成交量'] or 0)
        if volume <= 0:
            continue
        
        checked += 1
        if checked > 500:  # 限制检查数量，避免超时
            break
        
        hist = ak.stock_zh_a_hist(symbol=code, period='daily', 
                                  start_date=start_date, end_date=end_date, adjust='qfq')
        if hist.empty or len(hist) < PERIOD_DAYS:
            continue
        
        # 5. 近期无涨停（平底）
        if any(pct >= LIMIT_UP_PCT for pct in hist['涨跌幅']):
            continue
        
        # 6. 放量检查（当日成交量 > 历史每日 * 倍数）
        hist_volumes = hist['成交量'].tolist()
        if not all(volume > v * VOLUME_RATIO for v in hist_volumes):
            continue
        
        # 符合条件
        pct_chg = float(row['涨跌幅'] or 0)
        avg_vol = sum(hist_volumes) / len(hist_volumes)
        vol_ratio = volume / avg_vol if avg_vol > 0 else 0
        
        filtered.append({
            "code": code,
            "name": name,
            "reason": f"放量{vol_ratio:.1f}x 涨{pct_chg:.1f}% 市值{market_cap/1e8:.0f}亿"
        })
        
        if len(filtered) >= MAX_RESULTS:
            break
            
    except Exception:
        continue

print(json.dumps({"stocks": filtered}, ensure_ascii=False))
