import akshare as ak
import pandas as pd

print("--- Testing EastMoney Industry Spot ---")
try:
    # This usually returns the industry board with current change %
    df = ak.stock_board_industry_name_em() 
    # Wait, stock_board_industry_name_em returns list.
    # Try stock_board_industry_spot_em is not a function usually.
    # Try stock_board_change_em
    print("Trying stock_board_industry_name_em...")
    print(df.head())
except Exception as e:
    print(f"stock_board_industry_name_em failed: {e}")

try:
    print("\n--- Testing Main Sector Ranking (EastMoney) ---")
    # This is the standard one for sector ranking
    df = ak.stock_board_industry_hist_em(symbol="最新") # Sometimes this works?
    # Or just stock_board_industry_name_em might actually return data?
    # Let's check columns of the previous result
    pass
except Exception as e:
    print(e)

try:
    print("\n--- Testing THS specific ---")
    # There is no direct "rank all ths industries" function known commonly without iteration.
    pass
except:
    pass
