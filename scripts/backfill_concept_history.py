#!/usr/bin/env python3
"""
历史概念板块数据回填脚本

由于 AKShare 的 stock_board_concept_name_em() 只能获取当天数据，
本脚本通过获取每个概念板块的历史K线数据来回填历史涨幅。

使用方法:
    python scripts/backfill_concept_history.py --days 30

原理:
    1. 获取所有概念板块列表
    2. 对每个板块调用 stock_board_concept_hist_em() 获取历史K线
    3. 计算每日涨跌幅并存入数据库
"""

import argparse
import sys
import os
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import akshare as ak
import pandas as pd


def get_db():
    """获取数据库实例"""
    from backend.app.db.local_db import LocalDatabase
    return LocalDatabase()


def get_concept_list() -> pd.DataFrame:
    """获取概念板块列表"""
    print("正在获取概念板块列表...")
    try:
        df = ak.stock_board_concept_name_em()
        print(f"共获取 {len(df)} 个概念板块")
        return df
    except Exception as e:
        print(f"获取概念板块列表失败: {e}")
        return pd.DataFrame()


def get_concept_history(concept_name: str, days: int = 30) -> pd.DataFrame:
    """
    获取单个概念板块的历史K线数据
    
    Args:
        concept_name: 概念板块名称
        days: 获取最近多少天的数据
    
    Returns:
        包含日期和涨跌幅的DataFrame
    """
    try:
        # 计算日期范围
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days + 10)).strftime('%Y%m%d')  # 多取几天防止节假日
        
        # 获取历史K线
        df = ak.stock_board_concept_hist_em(
            symbol=concept_name,
            period="日k",
            start_date=start_date,
            end_date=end_date,
            adjust=""
        )
        
        if df is None or df.empty:
            return pd.DataFrame()
        
        # 重命名列
        df = df.rename(columns={
            '日期': 'date',
            '涨跌幅': 'change_percent',
            '收盘': 'close',
            '成交额': 'amount'
        })
        
        # 只保留需要的列
        if 'date' in df.columns and 'change_percent' in df.columns:
            df = df[['date', 'change_percent']].copy()
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            return df.tail(days)
        
        return pd.DataFrame()
        
    except Exception as e:
        # 某些板块可能没有历史数据
        return pd.DataFrame()


def backfill_history(days: int = 30, batch_size: int = 50, delay: float = 0.3):
    """
    回填历史概念板块数据
    
    Args:
        days: 回填最近多少天的数据
        batch_size: 每批处理多少个板块后休息
        delay: 每次请求的延迟（秒）
    """
    db = get_db()
    
    # 获取概念板块列表
    concept_df = get_concept_list()
    if concept_df.empty:
        print("无法获取概念板块列表")
        return
    
    # 获取板块名称列
    name_col = None
    for col in ['板块名称', '名称', 'name']:
        if col in concept_df.columns:
            name_col = col
            break
    
    if not name_col:
        print("找不到板块名称列")
        return
    
    concept_names = concept_df[name_col].tolist()
    total = len(concept_names)
    
    print(f"\n开始回填 {days} 天历史数据，共 {total} 个板块...")
    print(f"预计耗时: {total * delay / 60:.1f} 分钟\n")
    
    # 用于存储每日数据
    daily_data: Dict[str, List[Dict]] = {}  # date -> [sector_info, ...]
    
    success_count = 0
    fail_count = 0
    
    for i, concept_name in enumerate(concept_names):
        try:
            # 获取历史数据
            hist_df = get_concept_history(concept_name, days)
            
            if not hist_df.empty:
                for _, row in hist_df.iterrows():
                    date = row['date']
                    change_pct = float(row['change_percent'])
                    
                    if date not in daily_data:
                        daily_data[date] = []
                    
                    daily_data[date].append({
                        'name': concept_name,
                        'change_percent': change_pct
                    })
                
                success_count += 1
            else:
                fail_count += 1
            
            # 进度显示
            if (i + 1) % 10 == 0:
                print(f"进度: {i + 1}/{total} ({(i + 1) / total * 100:.1f}%) - 成功: {success_count}, 失败: {fail_count}")
            
            # 批次休息
            if (i + 1) % batch_size == 0:
                print(f"  批次休息 2 秒...")
                time.sleep(2)
            else:
                time.sleep(delay)
                
        except Exception as e:
            fail_count += 1
            print(f"  处理 {concept_name} 失败: {e}")
            continue
    
    print(f"\n数据获取完成: 成功 {success_count}, 失败 {fail_count}")
    print(f"共获取 {len(daily_data)} 天的数据")
    
    # 写入数据库
    print("\n正在写入数据库...")
    
    for date in sorted(daily_data.keys()):
        sectors = daily_data[date]
        # 按涨幅排序
        sectors.sort(key=lambda x: x['change_percent'], reverse=True)
        
        # 写入数据库
        db.insert_daily_concept_sectors(date, sectors)
        print(f"  {date}: {len(sectors)} 个板块")
    
    print(f"\n回填完成！共写入 {len(daily_data)} 天的数据")


def main():
    parser = argparse.ArgumentParser(description='回填历史概念板块数据')
    parser.add_argument('--days', type=int, default=30, help='回填最近多少天的数据 (默认: 30)')
    parser.add_argument('--delay', type=float, default=0.3, help='每次请求的延迟秒数 (默认: 0.3)')
    parser.add_argument('--batch', type=int, default=50, help='每批处理多少个板块 (默认: 50)')
    
    args = parser.parse_args()
    
    print("=" * 50)
    print("历史概念板块数据回填工具")
    print("=" * 50)
    print(f"回填天数: {args.days}")
    print(f"请求延迟: {args.delay}秒")
    print(f"批次大小: {args.batch}")
    print("=" * 50)
    
    backfill_history(
        days=args.days,
        batch_size=args.batch,
        delay=args.delay
    )


if __name__ == '__main__':
    main()
