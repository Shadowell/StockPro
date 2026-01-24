#!/usr/bin/env python3
"""
AkShare 股票接口快速参考和测试脚本
此脚本演示了项目中常用的各种AkShare接口的使用方法
"""

import akshare as ak
import pandas as pd
import datetime


def test_interface(interface_name, func, *args, **kwargs):
    """
    测试接口并返回结果
    """
    try:
        if args or kwargs:
            result = func(*args, **kwargs)
        else:
            result = func()
        
        if hasattr(result, 'shape'):
            print(f"✓ {interface_name}: {result.shape}")
            return result
        else:
            print(f"✓ {interface_name}: Success")
            return result
    except Exception as e:
        print(f"✗ {interface_name}: {str(e)[:80]}...")
        return None


def main():
    print("=== AkShare 股票接口快速参考 ===\n")

    # 1. A股实时行情
    print("1. A股实时行情:")
    spot_data = test_interface("stock_zh_a_spot_em", ak.stock_zh_a_spot_em)
    if spot_data is not None and not spot_data.empty:
        print(f"   示例数据: {spot_data.iloc[0]['代码']} - {spot_data.iloc[0]['名称']} - {spot_data.iloc[0]['最新价']}\n")

    # 2. A股历史数据
    print("2. A股历史数据:")
    hist_data = test_interface(
        "stock_zh_a_hist", 
        ak.stock_zh_a_hist, 
        symbol='000001', 
        period='daily', 
        start_date='20240101', 
        end_date='20240110'
    )
    if hist_data is not None and not hist_data.empty:
        print(f"   示例数据: {hist_data.iloc[0]['股票代码']} - {hist_data.iloc[0]['日期']} - 开:{hist_data.iloc[0]['开盘']} 收:{hist_data.iloc[0]['收盘']}\n")

    # 3. 概念板块
    print("3. 概念板块:")
    concept_data = test_interface("stock_board_concept_name_em", ak.stock_board_concept_name_em)
    if concept_data is not None and not concept_data.empty:
        # 东方财富概念板块的列名为 '板块代码' 和 '板块名称'
        print(f"   示例数据: {concept_data.iloc[0]['板块代码']} - {concept_data.iloc[0]['板块名称']}\n")

    # 4. 热门股票排行
    print("4. 热门股票排行:")
    hot_rank_data = test_interface("stock_hot_rank_em", ak.stock_hot_rank_em)
    if hot_rank_data is not None and not hot_rank_data.empty:
        print(f"   示例数据: {hot_rank_data.iloc[0]['当前排名']} - {hot_rank_data.iloc[0]['代码']} - {hot_rank_data.iloc[0]['股票名称']}\n")

    # 5. 涨停池
    print("5. 涨停池:")
    today = datetime.date.today().strftime('%Y%m%d')
    zt_pool_data = test_interface("stock_zt_pool_em", ak.stock_zt_pool_em, date=today)
    if zt_pool_data is not None and not zt_pool_data.empty:
        print(f"   示例数据: {zt_pool_data.iloc[0]['代码']} - {zt_pool_data.iloc[0]['名称']} - {zt_pool_data.iloc[0]['最新价']}\n")

    # 6. 市场资金流
    print("6. 市场资金流:")
    fund_flow_data = test_interface("stock_market_fund_flow", ak.stock_market_fund_flow)
    if fund_flow_data is not None and not fund_flow_data.empty:
        latest = fund_flow_data.iloc[-1]  # 最新数据通常在最后
        print(f"   示例数据: {latest['日期']} - 上证:{latest['上证-收盘价']} - 主力净流入:{latest['主力净流入-净额']}\n")

    # 7. 概念板块成分股
    print("7. 概念板块成分股:")
    concept_name_data = test_interface("stock_board_concept_name_em", ak.stock_board_concept_name_em)
    if concept_name_data is not None and not concept_name_data.empty:
        # 获取第一个概念板块的成分股
        first_concept_code = concept_name_data.iloc[0]['板块代码']
        concept_cons_data = test_interface(
            f"stock_board_concept_cons_em({first_concept_code})", 
            ak.stock_board_concept_cons_em, 
            symbol=first_concept_code
        )
        if concept_cons_data is not None and not concept_cons_data.empty:
            print(f"   示例数据: {first_concept_code} - {len(concept_cons_data)}只成分股 - 第一只: {concept_cons_data.iloc[0]['代码']}-{concept_cons_data.iloc[0]['名称']}\n")

    # 8. 同花顺概念板块
    print("8. 同花顺概念板块:")
    ths_concept_data = test_interface("stock_board_concept_name_ths", ak.stock_board_concept_name_ths)
    if ths_concept_data is not None and not ths_concept_data.empty:
        # 同花顺概念板块的列名为 'code' 和 'name'
        print(f"   示例数据: {ths_concept_data.iloc[0]['code']} - {ths_concept_data.iloc[0]['name']}\n")

    print("=== 接口测试完成 ===")


def get_stock_info(symbol):
    """
    获取单只股票的详细信息
    """
    print(f"\n=== {symbol} 股票信息 ===")
    
    # 获取实时行情
    spot_data = ak.stock_zh_a_spot_em()
    stock_info = spot_data[spot_data['代码'] == symbol]
    
    if not stock_info.empty:
        row = stock_info.iloc[0]
        print(f"名称: {row['名称']}")
        print(f"最新价: {row['最新价']}")
        print(f"涨跌幅: {row['涨跌幅']}")
        print(f"成交量: {row['成交量']}")
        print(f"成交额: {row['成交额']}")
        print(f"市盈率: {row['市盈率-动态']}")
        print(f"市净率: {row['市净率']}")
        print(f"总市值: {row['总市值']}")
    else:
        print(f"未找到股票 {symbol} 的信息")


def get_concept_stocks(concept_name):
    """
    获取特定概念板块的成分股
    """
    print(f"\n=== {concept_name} 概念板块成分股 ===")
    
    # 先获取所有概念板块
    concepts = ak.stock_board_concept_name_em()
    concept_row = concepts[concepts['板块名称'].str.contains(concept_name)]
    
    if not concept_row.empty:
        concept_code = concept_row.iloc[0]['板块代码']
        print(f"概念板块代码: {concept_code}")
        
        # 获取成分股
        cons_data = ak.stock_board_concept_cons_em(symbol=concept_code)
        if not cons_data.empty:
            print(f"成分股数量: {len(cons_data)}")
            print("前5只成分股:")
            for i in range(min(5, len(cons_data))):
                row = cons_data.iloc[i]
                print(f"  {row['代码']} - {row['名称']} - {row['最新价']} ({row['涨跌幅']}%)")
        else:
            print("未找到成分股数据")
    else:
        print(f"未找到概念板块 {concept_name}")


if __name__ == "__main__":
    main()
    
    # 示例：获取特定股票信息
    get_stock_info('000001')  # 平安银行
    
    # 示例：获取特定概念板块成分股
    get_concept_stocks('人工智能')  # 人工智能概念