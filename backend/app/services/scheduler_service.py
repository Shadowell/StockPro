"""
调度服务：管理后台数据同步任务
"""
import asyncio
import logging
from typing import Optional
from datetime import datetime, time, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.services.data_sync_service import data_sync_service


logger = logging.getLogger(__name__)


class SchedulerService:
    """
    调度服务，管理后台数据同步任务
    """
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_initialized = False
        
    async def initialize(self):
        """
        初始化调度器并添加任务
        """
        if self.is_initialized:
            return
            
        # 添加数据同步任务
        # 每天早上8点同步一次股票历史数据
        self.scheduler.add_job(
            func=self._sync_stock_history,
            trigger=CronTrigger(hour=8, minute=0),  # 每天早上8点
            id='sync_stock_history',
            name='同步股票历史数据',
            replace_existing=True
        )
        
        # 每天下午3点同步一次热门概念和基本面数据
        self.scheduler.add_job(
            func=self._sync_market_data,
            trigger=CronTrigger(hour=15, minute=0),  # 每天下午3点
            id='sync_market_data',
            name='同步市场数据',
            replace_existing=True
        )
        
        # 每小时同步一次热门股票数据
        self.scheduler.add_job(
            func=self._sync_ths_hot,
            trigger=CronTrigger(minute=30),  # 每小时的30分钟
            id='sync_ths_hot',
            name='同步热门股票数据',
            replace_existing=True
        )
        
        # 立即运行一次初始同步
        self.scheduler.add_job(
            func=self._initial_sync,
            trigger='date',
            run_date=datetime.now(),
            id='initial_sync',
            name='初始数据同步'
        )
        
        self.is_initialized = True
        logger.info("Scheduler initialized with data sync jobs")
    
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