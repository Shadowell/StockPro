# 平底均线图突破策略
# 策略逻辑：
# 1. 筛选主板股票（排除ST、创业板、科创板、北交所）
# 2. 计算M5/M10/M20/M30四条均线
# 3. 检查最近15天内，四条均线的最大差值百分比都很小（平行）
# 4. 平行的定义：四条均线之间的差值 < 股价的2%
# 这种股票处于横盘整理阶段，一旦放量突破，往往有较好的上涨空间

import akshare as ak
import pandas as pd
import json
from datetime import datetime, timedelta

# ====== 参数设置 ======
CHECK_DAYS = 10           # 检查最近N天的均线平行度
MAX_DIFF_PCT = 1.0        # 均线最大差值百分比（越小越平行）
PRICE_MIN = 3.0           # 最低股价
PRICE_MAX = 100.0         # 最高股价
MARKET_CAP_MIN = 20e8     # 最低市值20亿
MARKET_CAP_MAX = 200e8    # 最高市值500亿
MAX_RESULTS = 30          # 最大返回数量
MA_PERIODS = [5, 10, 20, 30]  # 均线周期

def calculate_ma(prices, period):
    """计算移动平均线"""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def get_ma_diff_pct(ma5, ma10, ma20, ma30, close):
    """计算四条均线的差值百分比"""
    if not all([ma5, ma10, ma20, ma30, close]) or close == 0:
        return None
    
    mas = [ma5, ma10, ma20, ma30]
    max_ma = max(mas)
    min_ma = min(mas)
    diff_pct = (max_ma - min_ma) / close * 100
    return diff_pct

try:
    # 1. 获取实时行情
    df = ak.stock_zh_a_spot_em()
    if df is None or df.empty:
        print(json.dumps({"stocks": [], "error": "获取行情失败"}, ensure_ascii=False))
        exit()
    
    # 2. 初筛主板股票
    df = df[~df['名称'].str.contains('ST', na=False)]
    df = df[~df['代码'].astype(str).str.startswith(('30', '688', '8', '43', '9'))]
    
    # 3. 市值和价格过滤
    df['总市值'] = pd.to_numeric(df['总市值'], errors='coerce').fillna(0)
    df['最新价'] = pd.to_numeric(df['最新价'], errors='coerce').fillna(0)
    df = df[(df['总市值'] >= MARKET_CAP_MIN) & (df['总市值'] <= MARKET_CAP_MAX)]
    df = df[(df['最新价'] >= PRICE_MIN) & (df['最新价'] <= PRICE_MAX)]
    
    # 4. 获取交易日历
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')  # 取90天数据计算30日均线
    
    filtered = []
    checked = 0
    
    for _, row in df.iterrows():
        if len(filtered) >= MAX_RESULTS:
            break
        
        checked += 1
        if checked > 300:  # 限制检查数量，避免超时
            break
        
        try:
            code = str(row['代码'])
            name = str(row['名称'])
            current_price = float(row['最新价'])
            market_cap = float(row['总市值'])
            change_pct = float(row.get('涨跌幅', 0) or 0)
            
            # 5. 获取历史K线
            hist = ak.stock_zh_a_hist(symbol=code, period='daily',
                                      start_date=start_date, end_date=end_date, adjust='qfq')
            
            if hist is None or hist.empty or len(hist) < 30 + CHECK_DAYS:
                continue
            
            # 6. 计算每天的均线并检查平行度
            closes = hist['收盘'].tolist()
            flat_days = 0
            total_diff_pct = 0
            
            for i in range(CHECK_DAYS):
                idx = len(closes) - 1 - i
                if idx < 29:  # 确保能计算30日均线
                    break
                
                prices_for_ma = closes[:idx+1]
                
                ma5 = calculate_ma(prices_for_ma, 5)
                ma10 = calculate_ma(prices_for_ma, 10)
                ma20 = calculate_ma(prices_for_ma, 20)
                ma30 = calculate_ma(prices_for_ma, 30)
                close = prices_for_ma[-1]
                
                diff_pct = get_ma_diff_pct(ma5, ma10, ma20, ma30, close)
                
                if diff_pct is not None and diff_pct <= MAX_DIFF_PCT:
                    flat_days += 1
                    total_diff_pct += diff_pct
            
            # 7. 如果大部分天数均线都很平行
            if flat_days >= CHECK_DAYS - 2:  # 允许2天不完全平行
                avg_diff = total_diff_pct / flat_days if flat_days > 0 else 0
                
                # 计算当前均线
                ma5 = calculate_ma(closes, 5)
                ma10 = calculate_ma(closes, 10)
                ma20 = calculate_ma(closes, 20)
                ma30 = calculate_ma(closes, 30)
                
                filtered.append({
                    "code": code,
                    "name": name,
                    "reason": f"均线平行{flat_days}天 差{avg_diff:.2f}% 涨{change_pct:.1f}% 市值{market_cap/1e8:.0f}亿"
                })
        
        except Exception:
            continue
    
    # 8. 按平行度排序输出
    print(json.dumps({"stocks": filtered}, ensure_ascii=False))

except Exception as e:
    print(json.dumps({"stocks": [], "error": str(e)}, ensure_ascii=False))
