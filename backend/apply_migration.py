import sqlite3
import os
import platform

def get_db_path():
    if platform.system() == "Darwin":  # macOS
        db_path = os.path.expanduser("~/Library/Application Support/StockApp/stock_data.db")
    elif platform.system() == "Windows":
        db_path = os.path.expanduser("~/AppData/Roaming/StockApp/stock_data.db")
    else:  # Linux and others
        db_path = os.path.expanduser("~/.local/share/StockApp/stock_data.db")
    return db_path

def apply_sql():
    db_path = get_db_path()
    print(f"Database path: {db_path}")
    
    if not os.path.exists(db_path):
        print("Database file does not exist. It might be created on first app run.")
        # We can try to initialize it using LocalDatabase if needed, but let's assume it exists if the user has run the app
        # If it doesn't exist, we should create the directory
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    with open('create_data_dev_tables.sql', 'r') as f:
        sql_script = f.read()
        
    try:
        cursor.executescript(sql_script)
        conn.commit()
        print("Successfully applied create_data_dev_tables.sql")
    except Exception as e:
        print(f"Error applying SQL: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    apply_sql()
