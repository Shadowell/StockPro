import akshare as ak
import pandas as pd

try:
    print("Fetching THS Industry Boards...")
    # Get all industry boards
    industries = ak.stock_board_industry_name_ths()
    print(f"Found {len(industries)} industries.")
    print(industries.head())

    # Note: akshare doesn't provide a single function to get "all industry real-time changes" for THS efficiently 
    # without iterating URLs usually. 
    # Let's check if there is a summary function.
    # Usually stock_board_industry_summary_ths doesn't exist. 
    # We might have to stick to 'stock_sect_jgc' (Dongfang Fortune) for ranking if THS is too slow/complex,
    # but user requested THS.
    
    # Alternative: stock_board_industry_index_ths might require looping.
    # Let's check a standard interface for ranking.
    
except Exception as e:
    print(f"Error fetching industries: {e}")

try:
    print("\nFetching THS Concept Boards...")
    concepts = ak.stock_board_concept_name_ths()
    print(f"Found {len(concepts)} concepts.")
    print(concepts.head())
except Exception as e:
    print(f"Error fetching concepts: {e}")
