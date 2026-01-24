from fastapi import APIRouter, HTTPException
from typing import Dict, List, Any
import logging
import sqlite3
import pandas as pd

from app.db.local_db import db_instance

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/tables")
async def get_tables_info() -> List[Dict[str, Any]]:
    """获取数据库中所有表的信息"""
    try:
        # 获取数据库连接
        conn = db_instance.get_connection()
        cursor = conn.cursor()
        
        # 查询所有表名
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        tables_info = []
        for table_row in tables:
            table_name = table_row[0]
            
            # 获取表的列信息
            cursor.execute(f"PRAGMA table_info({table_name});")
            columns_info = cursor.fetchall()
            
            # 获取表的行数
            cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
            row_count = cursor.fetchone()[0]
            
            # 提取列名
            columns = [col[1] for col in columns_info]
            
            tables_info.append({
                "name": table_name,
                "columns": columns,
                "rowCount": row_count
            })
        
        conn.close()
        return tables_info
        
    except Exception as e:
        logger.error(f"Error getting tables info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query")
async def execute_sql_query(request: Dict[str, Any]) -> Dict[str, Any]:
    """执行SQL查询"""
    try:
        sql_query = request.get("query", "").strip()
        
        if not sql_query:
            raise HTTPException(status_code=400, detail="SQL query is required")
        
        # 验证SQL安全性 - 只允许SELECT语句
        sql_upper = sql_query.upper().strip()
        if not sql_upper.startswith("SELECT"):
            raise HTTPException(status_code=400, detail="Only SELECT statements are allowed")
        
        # 限制查询复杂度 - 检查是否有潜在的危险操作
        forbidden_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE", "REPLACE"]
        for keyword in forbidden_keywords:
            if keyword in sql_upper:
                raise HTTPException(status_code=400, detail=f"SQL contains forbidden keyword: {keyword}")
        
        # 获取数据库连接并执行查询
        conn = db_instance.get_connection()
        cursor = conn.cursor()
        
        # 执行查询
        cursor.execute(sql_query)
        rows = cursor.fetchall()
        
        # 获取列名
        column_names = [description[0] for description in cursor.description]
        
        # 限制返回结果数量
        if len(rows) > 1000:
            rows = rows[:1000]
            logger.warning(f"Query result truncated to 1000 rows for security")
        
        # 转换数据为字典格式
        result_data = []
        for row in rows:
            row_dict = {}
            for i, col_name in enumerate(column_names):
                row_dict[col_name] = row[i]
            result_data.append(row_dict)
        
        conn.close()
        
        return {
            "columns": column_names,
            "rows": result_data,
            "rowCount": len(result_data)
        }
        
    except sqlite3.Error as e:
        logger.error(f"SQLite error in query: {e}")
        raise HTTPException(status_code=400, detail=f"SQL error: {str(e)}")
    except Exception as e:
        logger.error(f"Error executing SQL query: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/table/{table_name}")
async def get_table_data(table_name: str, limit: int = 100) -> Dict[str, Any]:
    """获取指定表的数据"""
    try:
        # 验证表名是否存在（防止SQL注入）
        conn = db_instance.get_connection()
        cursor = conn.cursor()
        
        # 获取所有表名
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        
        if table_name not in tables:
            raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
        
        # 构建安全的查询
        query = f"SELECT * FROM {table_name} LIMIT ?"
        cursor.execute(query, (limit,))
        rows = cursor.fetchall()
        
        # 获取列名
        column_names = [description[0] for description in cursor.description]
        
        # 转换数据为字典格式
        result_data = []
        for row in rows:
            row_dict = {}
            for i, col_name in enumerate(column_names):
                row_dict[col_name] = row[i]
            result_data.append(row_dict)
        
        # 获取总行数
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        total_count = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "columns": column_names,
            "rows": result_data,
            "rowCount": len(result_data),
            "totalCount": total_count
        }
        
    except Exception as e:
        logger.error(f"Error getting table data: {e}")
        raise HTTPException(status_code=500, detail=str(e))