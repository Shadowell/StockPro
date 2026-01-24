#!/usr/bin/env python3
"""
初始化市场日历数据脚本
此脚本将使用免费数据源填充市场日历事件
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.market_service import MarketService
from app.db.local_db import db_instance


def populate_calendar_data():
    """使用免费数据源填充日历数据"""
    print("开始填充市场日历数据...")
    
    try:
        # 使用免费数据源刷新日历数据
        result = MarketService.refresh_market_calendar_with_free_data(months=12)
        
        if result.get('error'):
            print(f"填充日历数据时发生错误: {result['error']}")
            return False
        
        print(f"成功填充 {result['written']} 条日历事件")
        return True
        
    except Exception as e:
        print(f"填充日历数据时发生异常: {e}")
        return False


if __name__ == "__main__":
    success = populate_calendar_data()
    if success:
        print("日历数据填充完成!")
    else:
        print("日历数据填充失败!")
        sys.exit(1)