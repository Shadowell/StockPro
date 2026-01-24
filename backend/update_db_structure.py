#!/usr/bin/env python
"""
更新数据库表结构以支持新的字段
"""
import sqlite3
import os
from datetime import datetime


def update_database_structure():
    """
    更新数据库表结构以支持新的字段
    """
    # 获取数据库路径
    import platform
    if platform.system() == "Darwin":  # macOS
        db_path = os.path.expanduser("~/Library/Application Support/StockApp/stock_data.db")
    elif platform.system() == "Windows":
        db_path = os.path.expanduser("~/AppData/Roaming/StockApp/stock_data.db")
    else:  # Linux and others
        db_path = os.path.expanduser("~/.local/share/StockApp/stock_data.db")
    
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    print(f"Updating database structure at: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 为stock_history表添加缺失的字段
    try:
        # 检查是否已存在change_percent字段
        cursor.execute("PRAGMA table_info(stock_history)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'change_amount' not in columns:
            cursor.execute("ALTER TABLE stock_history ADD COLUMN change_amount REAL")
            print("Added change_amount column to stock_history")
        
        if 'change_percent' not in columns:
            cursor.execute("ALTER TABLE stock_history ADD COLUMN change_percent REAL")
            print("Added change_percent column to stock_history")
        
        if 'turnover_rate' not in columns:
            cursor.execute("ALTER TABLE stock_history ADD COLUMN turnover_rate REAL")
            print("Added turnover_rate column to stock_history")
        
        if 'pe_ttm' not in columns:
            cursor.execute("ALTER TABLE stock_history ADD COLUMN pe_ttm REAL")
            print("Added pe_ttm column to stock_history")
        
        if 'pb' not in columns:
            cursor.execute("ALTER TABLE stock_history ADD COLUMN pb REAL")
            print("Added pb column to stock_history")
        
        if 'total_mv' not in columns:
            cursor.execute("ALTER TABLE stock_history ADD COLUMN total_mv REAL")
            print("Added total_mv column to stock_history")
        
        if 'circ_mv' not in columns:
            cursor.execute("ALTER TABLE stock_history ADD COLUMN circ_mv REAL")
            print("Added circ_mv column to stock_history")
        
        # 为stock_fundamentals表添加缺失的字段
        cursor.execute("PRAGMA table_info(stock_fundamentals)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'price' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN price REAL")
            print("Added price column to stock_fundamentals")
        
        if 'change_amount' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN change_amount REAL")
            print("Added change_amount column to stock_fundamentals")
        
        if 'change_percent' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN change_percent REAL")
            print("Added change_percent column to stock_fundamentals")
        
        if 'volume' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN volume BIGINT")
            print("Added volume column to stock_fundamentals")
        
        if 'amount' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN amount REAL")
            print("Added amount column to stock_fundamentals")
        
        if 'amplitude' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN amplitude REAL")
            print("Added amplitude column to stock_fundamentals")
        
        if 'turnover_rate' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN turnover_rate REAL")
            print("Added turnover_rate column to stock_fundamentals")
        
        if 'total_mv' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN total_mv REAL")
            print("Added total_mv column to stock_fundamentals")
        
        if 'circ_mv' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN circ_mv REAL")
            print("Added circ_mv column to stock_fundamentals")
        
        if 'high_52w' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN high_52w REAL")
            print("Added high_52w column to stock_fundamentals")
        
        if 'low_52w' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN low_52w REAL")
            print("Added low_52w column to stock_fundamentals")
        
        if 'eps' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN eps REAL")
            print("Added eps column to stock_fundamentals")
        
        if 'bvps' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN bvps REAL")
            print("Added bvps column to stock_fundamentals")
        
        if 'roe' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN roe REAL")
            print("Added roe column to stock_fundamentals")
        
        if 'net_profit_margin' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN net_profit_margin REAL")
            print("Added net_profit_margin column to stock_fundamentals")
        
        if 'debt_to_equity' not in columns:
            cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN debt_to_equity REAL")
            print("Added debt_to_equity column to stock_fundamentals")
        
        # 创建concept_flow表（如果不存在）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS concept_flow (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                concept_name TEXT NOT NULL,
                net_amount REAL,
                net_volume REAL,
                main_net_amount REAL,
                super_large_net_amount REAL,
                large_net_amount REAL,
                medium_net_amount REAL,
                small_net_amount REAL,
                rank INTEGER
            )
        ''')
        print("Created concept_flow table if it didn't exist")
        
        # 创建ths_hot_rank表（如果不存在）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ths_hot_rank (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rank INTEGER,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                price REAL,
                change_amount REAL,
                change_percent REAL,
                date DATE,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("Created ths_hot_rank table if it didn't exist")
        
        conn.commit()
        print("Database structure updated successfully!")
        
    except Exception as e:
        print(f"Error updating database structure: {str(e)}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    update_database_structure()