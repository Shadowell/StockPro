# 放量突破策略 - 参考strategy_template_1.py
import akshare as ak
import json
import pandas as pd
from datetime import datetime, timedelta

# 参数
period_days = 20
volume_threshold = 1.75
market_cap_low = 30 * 10**8
market_cap_high = 160 * 10**8

def get_trading_days(date_str, n):
    trade_days_df = ak.tool_trade_date_hist_sina()
    today = datetime.strptime(date_str, '%Y-%m-%d')
    trade_days_df['trade_date'] = pd.to_datetime(trade_days_df['trade_date'])
    days = trade_days_df[trade_days_df['trade_date'] < today].tail(n)['trade_date'].tolist()
    return days[0].strftime('%Y%m%d'), days[-1].strftime('%Y%m%d')

df = ak.stock_zh_a_spot_em()
today = datetime.now().strftime('%Y-%m-%d')
start_date, end_date = get_trading_days(today, period_days)

stocks = []
for _, row in df.iterrows():
    try:
        code, name = row['代码'], row['名称']
        price, volume = float(row['最新价']), float(row['成交量'])
        market_cap = float(row['总市值'])
        open_price = float(row['今开'])
        pct = float(row['涨跌幅'])
        
        if 'ST' in name or code.startswith(('30','688','8','43','9')):
            continue
        if market_cap > market_cap_high or market_cap <= market_cap_low:
            continue
        if price <= 5 or open_price > price:
            continue
        
        hist = ak.stock_zh_a_hist(symbol=code, period='daily', start_date=start_date, end_date=end_date, adjust='qfq')
        if hist.empty or len(hist) < period_days:
            continue
        if any(p >= 9.8 for p in hist['涨跌幅']):
            continue
        if all(volume > v * volume_threshold for v in hist['成交量']):
            stocks.append({"code": code, "name": name, "reason": f"放量{volume/hist['成交量'].mean():.1f}倍"})
        if len(stocks) >= 15:
            break
    except:
        continue

print(json.dumps({"stocks": stocks}, ensure_ascii=False))
