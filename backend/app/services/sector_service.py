import akshare as ak
import pandas as pd
from app.models.schemas import SectorBase
import logging
from datetime import date, datetime
from app.db import get_database

logger = logging.getLogger(__name__)

class SectorService:
    def _get_sectors_from_fund_flow(self) -> list[SectorBase]:
        """使用资金流向接口获取板块数据（最可靠的数据源）"""
        try:
            df = ak.stock_fund_flow_concept(symbol="即时")
            if df is None or df.empty:
                return []
            
            # 按涨跌幅排序，只取涨幅>2%的
            df['行业-涨跌幅'] = pd.to_numeric(df['行业-涨跌幅'], errors='coerce').fillna(0.0)
            df = df[df['行业-涨跌幅'] > 2.0]
            df = df.sort_values('行业-涨跌幅', ascending=False)
            
            sectors = []
            for _, row in df.iterrows():
                try:
                    name = str(row.get('行业', '')).strip()
                    if not name:
                        continue
                    
                    change_percent = float(row.get('行业-涨跌幅', 0))
                    leader_stock = str(row.get('领涨股', ''))
                    company_count = int(row.get('公司家数', 0))
                    
                    sector = SectorBase(
                        name=name,
                        change_percent=change_percent,
                        up_count=company_count,  # 使用公司家数作为参考
                        down_count=0,
                        leader_stock=leader_stock
                    )
                    sectors.append(sector)
                except Exception as row_e:
                    continue
            
            return sectors
        except Exception as e:
            logger.error(f"Error fetching sectors from fund flow: {e}")
            return []

    def _get_sectors_from_ths(self) -> list[SectorBase]:
        """使用同花顺接口获取板块数据（备用数据源）"""
        try:
            df = ak.stock_board_concept_name_ths()
            if df is None or df.empty:
                return []
            
            sectors = []
            for _, row in df.iterrows():
                try:
                    name = str(row.get('name', row.get('概念名称', '')))
                    change_percent = float(row.get('涨跌幅', 0) if '涨跌幅' in df.columns else 0)
                    
                    sector = SectorBase(
                        name=name,
                        change_percent=change_percent,
                        up_count=0,
                        down_count=0,
                        leader_stock=""
                    )
                    sectors.append(sector)
                except Exception:
                    continue
            
            return sectors[:50]
        except Exception as e:
            logger.error(f"Error fetching sectors from THS: {e}")
            return []

    def get_hot_sectors(self, date_str: str = None) -> list[SectorBase]:
        try:
            target_date = date_str
            is_today = False
            
            if not target_date:
                target_date = date.today().isoformat()
                is_today = True
            
            if is_today:
                # 方法1: 使用资金流向接口（最可靠）
                sectors = self._get_sectors_from_fund_flow()
                if sectors:
                    return sectors
                
                # 方法2: 尝试东方财富概念板块接口
                try:
                    df = ak.stock_board_concept_name_em()
                    
                    if df is not None and not df.empty and '涨跌幅' in df.columns:
                        df = df[df['涨跌幅'] > 2.0]
                        df = df.sort_values('涨跌幅', ascending=False)
                    
                        sectors = []
                        for _, row in df.iterrows():
                            try:
                                name = str(row['板块名称'])
                                change_percent = float(row['涨跌幅'])
                                up_count = int(row['上涨家数'])
                                down_count = int(row['下跌家数'])
                                leader_stock = str(row['领涨股票'])
                                
                                sector = SectorBase(
                                    name=name,
                                    change_percent=change_percent,
                                    up_count=up_count,
                                    down_count=down_count,
                                    leader_stock=leader_stock
                                )
                                sectors.append(sector)
                            except Exception:
                                continue
                        
                        if sectors:
                            return sectors
                except Exception as api_e:
                    logger.warning(f"东方财富板块接口失败: {api_e}")
                
                # 方法3: 使用同花顺接口
                ths_sectors = self._get_sectors_from_ths()
                if ths_sectors:
                    return ths_sectors

            # 历史数据从数据库获取
            try:
                response = type('obj', (object,), {'data': []})()
                data = response.data
                
                sectors = []
                for row in data:
                    sector = SectorBase(
                        name=row['name'],
                        change_percent=row['change_percent'],
                        up_count=row['up_count'],
                        down_count=row['down_count'],
                        leader_stock=row['leader_stock']
                    )
                    sectors.append(sector)
                
                sectors.sort(key=lambda x: x.change_percent, reverse=True)
                return sectors
                
            except Exception as db_e:
                logger.error(f"Error fetching hot sectors from DB: {db_e}")
                return []

        except Exception as e:
            logger.error(f"Error getting hot sectors: {e}")
            return []
