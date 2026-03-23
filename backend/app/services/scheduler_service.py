"""
调度服务：管理后台数据同步任务

数据更新频率分类：
- 天级数据：每日收盘后更新（股票历史、涨停数据、龙虎榜、北向资金等）
- 小时级数据：交易时间内每小时更新（热门板块、热度排行、资金流向等）
- 分钟级数据：交易时间内每分钟更新（实时行情、快讯资讯等）
"""
import asyncio
import logging
from typing import Optional
from datetime import datetime, time, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.services.data_sync_service import data_sync_service
from app.services.factor_sync_service import factor_sync_service


logger = logging.getLogger(__name__)


class SchedulerService:
    """
    调度服务，管理后台数据同步任务
    
    调度策略：
    1. 天级任务：固定时间执行（如16:00、18:00）
    2. 小时级任务：交易时间内每小时执行
    3. 分钟级任务：交易时间内每分钟执行
    """
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_initialized = False
        
    def _is_trading_time(self) -> bool:
        """判断当前是否为交易时间（周一到周五 9:00-15:30）"""
        now = datetime.now()
        weekday = now.weekday()
        current_time = now.time()
        
        # 周末不交易
        if weekday >= 5:
            return False
        
        # 交易时间 9:15-11:30, 13:00-15:00
        morning_start = time(9, 15)
        morning_end = time(11, 30)
        afternoon_start = time(13, 0)
        afternoon_end = time(15, 0)
        
        if morning_start <= current_time <= morning_end:
            return True
        if afternoon_start <= current_time <= afternoon_end:
            return True
        
        return False
        
    async def initialize(self):
        """
        初始化调度器并添加任务
        """
        if self.is_initialized:
            return
        
        # ========== 天级任务 ==========
            
        # 股票历史数据 - 每天16:00
        self.scheduler.add_job(
            func=self._sync_stock_history,
            trigger=CronTrigger(hour=16, minute=0, day_of_week='mon-fri'),
            id='daily_stock_history',
            name='同步股票历史数据',
            replace_existing=True
        )
        
        # 涨停连板数据 - 每天16:30
        self.scheduler.add_job(
            func=self._sync_zt_pool,
            trigger=CronTrigger(hour=16, minute=30, day_of_week='mon-fri'),
            id='daily_zt_pool',
            name='同步涨停连板数据',
            replace_existing=True
        )
        
        # 每日概念板块数据（用于复盘中心）- 每天15:30
        self.scheduler.add_job(
            func=self._sync_daily_concept_sectors,
            trigger=CronTrigger(hour=15, minute=30, day_of_week='mon-fri'),
            id='daily_concept_sectors',
            name='同步每日概念板块',
            replace_existing=True
        )
        
        # 龙虎榜数据 - 每天18:00
        self.scheduler.add_job(
            func=self._sync_dragon_tiger,
            trigger=CronTrigger(hour=18, minute=0, day_of_week='mon-fri'),
            id='daily_dragon_tiger',
            name='同步龙虎榜数据',
            replace_existing=True
        )
        
        # 北向资金 - 每天18:30
        self.scheduler.add_job(
            func=self._sync_northbound,
            trigger=CronTrigger(hour=18, minute=30, day_of_week='mon-fri'),
            id='daily_northbound',
            name='同步北向资金数据',
            replace_existing=True
        )
        
        # 因子数据 - 每天16:00
        self.scheduler.add_job(
            func=self._sync_factor_data,
            trigger=CronTrigger(hour=16, minute=0, day_of_week='mon-fri'),
            id='daily_factor_data',
            name='同步因子库数据',
            replace_existing=True
        )
        
        # ========== 小时级任务 ==========
        
        # 热门概念和基本面数据 - 交易时间每小时00分
        self.scheduler.add_job(
            func=self._sync_market_data,
            trigger=CronTrigger(minute=0, hour='9-15', day_of_week='mon-fri'),
            id='hourly_market_data',
            name='同步市场数据',
            replace_existing=True
        )
        
        # 板块行情 - 交易时间每小时30分
        self.scheduler.add_job(
            func=self._sync_sector_realtime,
            trigger=CronTrigger(minute=30, hour='9-15', day_of_week='mon-fri'),
            id='hourly_sector',
            name='同步板块行情',
            replace_existing=True
        )
        
        # 热度排行 - 交易时间每小时30分
        self.scheduler.add_job(
            func=self._sync_ths_hot,
            trigger=CronTrigger(minute=30, hour='9-15', day_of_week='mon-fri'),
            id='hourly_ths_hot',
            name='同步热门股票数据',
            replace_existing=True
        )
        
        # ========== 分钟级任务 ==========
        
        # 全市场行情 - 交易时间每5分钟
        self.scheduler.add_job(
            func=self._sync_realtime_stocks,
            trigger=CronTrigger(minute='*/5', hour='9-15', day_of_week='mon-fri'),
            id='minute_stocks',
            name='同步实时行情',
            replace_existing=True
        )
        
        # 快讯资讯 - 每分钟
        self.scheduler.add_job(
            func=self._sync_news,
            trigger=IntervalTrigger(minutes=1),
            id='minute_news',
            name='同步快讯资讯',
            replace_existing=True
        )
        
        # 初始同步改为延迟执行，避免启动时崩溃
        # self.scheduler.add_job(
        #     func=self._initial_sync,
        #     trigger='date',
        #     run_date=datetime.now(),
        #     id='initial_sync',
        #     name='初始数据同步'
        # )
        logger.info("Initial sync disabled for stability")
        
        self.is_initialized = True
        logger.info("Scheduler initialized with data sync jobs (daily/hourly/minute)")
    
    async def start(self):
        """
        启动调度器
        """
        await self.initialize()
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler started")
    
    async def shutdown(self):
        """
        关闭调度器
        """
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler shutdown")
    
    async def _sync_stock_history(self):
        """
        同步股票历史数据
        """
        try:
            # 获取昨天的日期
            from datetime import datetime, timedelta
            yesterday = datetime.now() - timedelta(days=1)
            date_str = yesterday.strftime('%Y%m%d')
            
            logger.info(f"Starting stock history sync for date {date_str}")
            result = data_sync_service.sync_stock_history(date_str)
            logger.info(f"Stock history sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in stock history sync: {str(e)}")
    
    async def _sync_market_data(self):
        """
        同步市场数据（热门概念、基本面等）
        """
        try:
            logger.info("Starting market data sync")
            
            # 同步热门概念
            concept_result = data_sync_service.sync_hot_concepts()
            logger.info(f"Concept sync completed: {concept_result}")
            
            # 同步基本面数据
            fundamental_result = data_sync_service.sync_fundamentals()
            logger.info(f"Fundamentals sync completed: {fundamental_result}")
            
        except Exception as e:
            logger.error(f"Error in market data sync: {str(e)}")
    
    async def _sync_ths_hot(self):
        """
        同步同花顺热门股票数据
        """
        try:
            logger.info("Starting THS hot stocks sync")
            result = data_sync_service.sync_ths_hot()
            logger.info(f"THS hot stocks sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in THS hot stocks sync: {str(e)}")
    
    async def _sync_factor_data(self):
        """
        同步因子库数据
        """
        try:
            logger.info("Starting factor data sync")
            
            # 初始化因子定义（如果还没有初始化）
            factor_sync_service.init_factor_definitions()
            
            # 同步所有因子数据
            result = factor_sync_service.sync_all_factors()
            logger.info(f"Factor data sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in factor data sync: {str(e)}")
    
    async def _sync_zt_pool(self):
        """
        同步涨停连板数据（天级）
        """
        try:
            logger.info("Starting zt pool sync")
            result = data_sync_service.sync_zt_pool()
            logger.info(f"ZT pool sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in zt pool sync: {str(e)}")
    
    async def _sync_dragon_tiger(self):
        """
        同步龙虎榜数据（天级）
        """
        try:
            logger.info("Starting dragon tiger board sync")
            result = data_sync_service.sync_dragon_tiger()
            logger.info(f"Dragon tiger sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in dragon tiger sync: {str(e)}")
    
    async def _sync_northbound(self):
        """
        同步北向资金数据（天级）
        """
        try:
            logger.info("Starting northbound flow sync")
            result = data_sync_service.sync_northbound_flow()
            logger.info(f"Northbound flow sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in northbound flow sync: {str(e)}")
    
    async def _sync_sector_realtime(self):
        """
        同步板块实时行情（小时级）
        """
        if not self._is_trading_time():
            logger.debug("Not trading time, skipping sector sync")
            return
        
        try:
            logger.info("Starting sector realtime sync")
            result = data_sync_service.sync_sector_realtime()
            logger.info(f"Sector realtime sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in sector realtime sync: {str(e)}")
    
    async def _sync_realtime_stocks(self):
        """
        同步全市场实时行情（分钟级）
        """
        if not self._is_trading_time():
            return
        
        try:
            result = data_sync_service.sync_realtime_stocks()
            logger.debug(f"Realtime stocks sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in realtime stocks sync: {str(e)}")
    
    async def _sync_news(self):
        """
        同步快讯资讯（分钟级）
        """
        try:
            result = data_sync_service.sync_news()
            if result.get('count', 0) > 0:
                logger.info(f"News sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in news sync: {str(e)}")
    
    async def _sync_daily_concept_sectors(self):
        """
        同步每日概念板块数据（天级，用于复盘中心）
        """
        try:
            logger.info("Starting daily concept sectors sync")
            result = data_sync_service.sync_daily_concept_sectors()
            logger.info(f"Daily concept sectors sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in daily concept sectors sync: {str(e)}")
    
    async def _initial_sync(self):
        """
        初始数据同步
        """
        try:
            logger.info("Starting initial data sync")
            
            # 同步股票历史数据
            yesterday = datetime.now() - timedelta(days=1)
            date_str = yesterday.strftime('%Y%m%d')
            stock_result = data_sync_service.sync_stock_history(date_str)
            logger.info(f"Initial stock sync completed: {stock_result}")
            
            # 同步其他数据
            concept_result = data_sync_service.sync_hot_concepts()
            logger.info(f"Initial concept sync completed: {concept_result}")
            
            fundamental_result = data_sync_service.sync_fundamentals()
            logger.info(f"Initial fundamentals sync completed: {fundamental_result}")
            
            ths_result = data_sync_service.sync_ths_hot()
            logger.info(f"Initial THS sync completed: {ths_result}")
            
            # 初始化因子定义
            factor_sync_service.init_factor_definitions()
            logger.info("Factor definitions initialized")
            
        except Exception as e:
            logger.error(f"Error in initial data sync: {str(e)}")
    
    def add_custom_job(self, func, trigger, id: str, name: str, **kwargs):
        """
        添加自定义任务
        """
        self.scheduler.add_job(
            func=func,
            trigger=trigger,
            id=id,
            name=name,
            replace_existing=True,
            **kwargs
        )
        logger.info(f"Added custom job: {name}")


# 全局实例
scheduler_service = SchedulerService()


async def init_scheduler():
    """
    初始化调度器
    """
    await scheduler_service.start()
    return scheduler_service


async def shutdown_scheduler():
    """
    关闭调度器
    """
    await scheduler_service.shutdown()