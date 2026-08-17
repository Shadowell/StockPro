"""
调度服务：管理后台数据同步任务

数据更新频率分类：
- 天级数据：每日收盘后更新（股票历史、涨停数据、龙虎榜、北向资金等）
- 小时级数据：交易时间内每小时更新（热门板块、热度排行、资金流向等）
- 分钟级数据：交易时间内每分钟更新（实时行情、快讯资讯等）
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.core.config import settings
from app.services.data_sync_service import data_sync_service
from app.services.daily_reference_sync_service import DailyReferenceSyncService
from app.services.factor_sync_service import factor_sync_service
from app.services.local_backup_service import LocalBackupService
from app.services.tushare_catalog_service import TushareCatalogService
from app.db import db_instance as db


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
        self.data_dev_job_prefix = "data_dev_task_"
        self.manual_task_status: Dict[str, Any] = {
            "task_id": None,
            "is_running": False,
            "total": 0,
            "processed": 0,
            "message": "Idle",
        }
        self.tushare_catalog_service = TushareCatalogService(db)
        
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

    def _data_dev_job_id(self, task_id: int) -> str:
        return f"{self.data_dev_job_prefix}{task_id}"

    def _schedule_data_dev_task(self, task_id: int, cron_expression: str) -> None:
        trigger = CronTrigger.from_crontab(cron_expression)
        self.scheduler.add_job(
            func=self._execute_data_dev_task_job,
            trigger=trigger,
            id=self._data_dev_job_id(task_id),
            name=f"数据开发任务#{task_id}",
            args=[task_id],
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=300,
        )

    def _unschedule_data_dev_task(self, task_id: int) -> None:
        job_id = self._data_dev_job_id(task_id)
        try:
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
        except Exception:
            logger.debug("No data-dev job found for task_id=%s", task_id)

    def refresh_daily_reference_schedule(self, schedule: Dict[str, Any]) -> None:
        """Make the one managed post-close job match its PG schedule record."""
        job_id = "daily_reference_publication"
        if not bool(schedule.get("enabled")):
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
            logger.info("Daily reference publication is disabled in PostgreSQL")
            return
        cron = str(schedule.get("cron") or "30 17 * * 1-5")
        timezone = ZoneInfo(str(schedule.get("timezone") or "Asia/Shanghai"))
        trigger = CronTrigger.from_crontab(cron, timezone=timezone)
        self.scheduler.add_job(
            func=self._sync_daily_reference_publication,
            trigger=trigger,
            id=job_id,
            name="PG 日终参考数据与市场证据",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=1800,
        )

    def _reload_data_dev_jobs(self) -> None:
        try:
            tasks = self.get_data_dev_tasks()
            for task in tasks:
                if task.get("enabled"):
                    self._schedule_data_dev_task(task["id"], task["cron_expression"])
                else:
                    self._unschedule_data_dev_task(task["id"])
            logger.info("Loaded %s data-dev task jobs", len(tasks))
        except Exception as e:
            logger.error("Failed to reload data-dev jobs: %s", e)

    def get_data_dev_tasks(self) -> List[Dict[str, Any]]:
        rows = db.list_data_dev_tasks()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "sql_content": row["sql_content"],
                "cron_expression": row["cron_expression"],
                "enabled": bool(row["enabled"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "last_status": row["last_status"],
                "last_run": row["last_run"],
                "last_error": row["last_error"],
            }
            for row in rows
        ]

    def add_data_dev_task(
        self,
        name: str,
        description: str,
        sql_content: str,
        cron_expression: str,
        enabled: bool = True,
    ) -> int:
        task_id = db.create_data_dev_task(name, description, sql_content, cron_expression, enabled)

        if enabled:
            self._schedule_data_dev_task(task_id, cron_expression)
        else:
            self._unschedule_data_dev_task(task_id)

        return int(task_id)

    def update_data_dev_task(
        self,
        task_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        sql_content: Optional[str] = None,
        cron_expression: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        task = db.update_data_dev_task_fields(
            task_id, name=name, description=description,
            sql_content=sql_content, cron_expression=cron_expression, enabled=enabled,
        )
        if not task:
            raise ValueError("Task not found")

        next_cron = task["cron_expression"]
        next_enabled = bool(task["enabled"])
        if next_enabled:
            self._schedule_data_dev_task(task_id, next_cron)
        else:
            self._unschedule_data_dev_task(task_id)

    def delete_data_dev_task(self, task_id: int) -> None:
        self._unschedule_data_dev_task(task_id)
        if not db.delete_data_dev_task_and_logs(task_id):
            raise ValueError("Task not found")

    def get_task_logs(self, task_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        rows = db.get_data_dev_task_logs(task_id, limit)
        return [
            {
                "id": row["id"],
                "execution_start": row["execution_start"],
                "execution_end": row["execution_end"],
                "status": row["status"],
                "error_message": row["error_message"],
                "affected_rows": row["affected_rows"],
            }
            for row in rows
        ]

    async def _execute_data_dev_task_job(self, task_id: int) -> None:
        task = db.get_data_dev_task(task_id)
        if not task:
            logger.warning("Data-dev task not found: %s", task_id)
            self._unschedule_data_dev_task(task_id)
            return

        if not bool(task["enabled"]):
            return

        await self.execute_data_dev_task(task_id=task_id, sql_content=task["sql_content"], task_name=task["name"])

    def _execute_data_dev_task_sync(self, task_id: int, sql_content: str, task_name: str) -> Dict[str, Any]:
        log_id = db.create_data_dev_log(task_id, status="running")
        affected_rows = 0
        try:
            statements = [stmt.strip() for stmt in sql_content.split(";") if stmt.strip()]
            with db.get_connection() as conn:
                with conn.cursor() as cursor:
                    for stmt in statements:
                        cursor.execute(stmt)
                        if cursor.rowcount and cursor.rowcount > 0:
                            affected_rows += int(cursor.rowcount)
                conn.commit()

            db.complete_data_dev_log(log_id, status="success", affected_rows=affected_rows)
            db.update_data_dev_task_fields(task_id)
            logger.info("Data-dev task executed successfully: %s(%s), affected_rows=%s", task_name, task_id, affected_rows)
            return {"status": "success", "affected_rows": affected_rows}
        except Exception as e:
            try:
                db.complete_data_dev_log(log_id, status="failed", error_message=str(e))
            except Exception:
                pass
            logger.error("Data-dev task failed: %s(%s), error=%s", task_name, task_id, e)
            raise

    async def execute_data_dev_task(self, task_id: int, sql_content: str, task_name: str) -> Dict[str, Any]:
        return await asyncio.to_thread(self._execute_data_dev_task_sync, task_id, sql_content, task_name)

    def get_status(self) -> Dict[str, Any]:
        return dict(self.manual_task_status)

    async def fetch_and_save_all_stocks_history(self) -> None:
        if self.manual_task_status.get("is_running"):
            return

        task_id = f"manual_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.manual_task_status = {
            "task_id": task_id,
            "is_running": True,
            "total": 1,
            "processed": 0,
            "message": "Running stock history sync...",
        }

        try:
            result = await asyncio.to_thread(data_sync_service.sync_stock_history)
            status = str(result.get("status", "")).lower()
            message = str(result.get("message", "Completed"))
            self.manual_task_status.update(
                {
                    "is_running": False,
                    "processed": 1,
                    "message": message if status != "error" else f"Error: {message}",
                }
            )
        except Exception as e:
            logger.error("Manual stock history sync failed: %s", e)
            self.manual_task_status.update(
                {
                    "is_running": False,
                    "processed": 0,
                    "message": f"Error: {e}",
                }
            )
        
    async def initialize(self):
        """
        初始化调度器并添加任务
        """
        if self.is_initialized:
            return
        
        # ========== 天级任务 ==========
            
        # The daily reference job is the single source of truth for calendar
        # gate -> bars -> sealed snapshot -> post-close evidence.  It replaces
        # the legacy independent K-line and market-evidence timers.
        self.refresh_daily_reference_schedule(DailyReferenceSyncService(db).get_schedule())

        # Local PostgreSQL is the only supported store for this delivery phase.
        # Keep a daily custom-format dump plus a PG audit manifest. Restore is
        # deliberately a separate acceptance drill against a disposable DB.
        if settings.ENABLE_LOCAL_PG_BACKUP:
            self.scheduler.add_job(
                func=self._create_local_pg_backup,
                trigger=CronTrigger.from_crontab(
                    settings.LOCAL_PG_BACKUP_CRON,
                    timezone=ZoneInfo("Asia/Shanghai"),
                ),
                id="local_pg_daily_backup",
                name="本地 PostgreSQL 每日备份",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=3600,
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

        # Paper 模拟盘周期推进 - 每天19:05（日终参考数据 18:10 封存之后）
        self.scheduler.add_job(
            func=self._advance_paper_instances,
            trigger=CronTrigger(hour=19, minute=5, day_of_week='mon-fri'),
            id='paper_cycle_advance',
            name='Paper 模拟盘周期推进',
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=7200,
        )
        
        # Factor calculation is intentionally not registered here. Sprint 02
        # attaches it to the sealed dataset-snapshot event, never to a clock
        # that can observe incomplete or provider-backed daily data.
        
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

        if settings.RUN_STARTUP_DATA_SYNC:
            self.scheduler.add_job(
                func=self._initial_sync,
                trigger='date',
                run_date=datetime.now(),
                id='initial_sync',
                name='初始数据同步'
            )
        else:
            logger.info("Startup data sync skipped; scheduled/manual sync remains available")
        
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

        # 加载数据开发任务调度
        self._reload_data_dev_jobs()
        
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
            self.scheduler.shutdown(wait=False)
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
            result = await asyncio.to_thread(data_sync_service.sync_stock_history, date_str)
            logger.info(f"Stock history sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in stock history sync: {str(e)}")

    async def _sync_all_ashare_klines(self):
        """
        每日同步全量 A 股日 K 数据
        """
        try:
            logger.info("Starting PG-backed daily A-share reference sync")
            from app.api.endpoints import data as data_module

            result = await data_module.run_daily_reference_sync()
            logger.info("Daily A-share reference sync completed: %s", result)
        except Exception as e:
            logger.error(f"Error in daily all A-share kline sync: {str(e)}")

    async def _sync_daily_reference_publication(self):
        """APScheduler entrypoint: catch up recent trading days then seal today's pipeline."""
        try:
            from datetime import timedelta
            from zoneinfo import ZoneInfo

            from app.api.endpoints import data as data_module
            from app.services.tushare_provider import market_data_provider

            schedule = DailyReferenceSyncService(db).get_schedule()
            catchup_days = max(1, min(10, int(schedule.get("catchupDays") or 5)))
            now = datetime.now(ZoneInfo(str(schedule.get("timezone") or "Asia/Shanghai"))).date()
            start = (now - timedelta(days=catchup_days + 14)).isoformat()
            end = now.isoformat()
            try:
                open_dates = market_data_provider.trade_cal_open_dates(start, end)
            except Exception:
                logger.warning("Trade calendar unavailable for catchup; falling back to today", exc_info=True)
                open_dates = [end]
            targets = open_dates[-catchup_days:] if open_dates else [end]
            for trade_date in targets:
                result = await data_module.run_daily_reference_sync(trade_date=trade_date)
                logger.info("Daily reference catchup %s -> %s", trade_date, result.get("status"))
        except Exception as e:
            logger.error("Error in daily reference publication catchup: %s", e)

    async def _create_local_pg_backup(self):
        """Create one audited local PG backup without blocking the event loop."""
        try:
            result = await asyncio.to_thread(LocalBackupService(db).create_backup)
            logger.info(
                "Local PostgreSQL backup completed: id=%s size=%s",
                result.get("id"),
                result.get("backup_size_bytes"),
            )
        except Exception as exc:
            logger.error("Local PostgreSQL backup failed: %s", exc)

    async def _sync_post_close_market_evidence(self):
        """Publish one source-labelled post-close market-evidence snapshot."""
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        if now.weekday() >= 5:
            return
        try:
            self.tushare_catalog_service.install_catalog()
            result = await asyncio.to_thread(
                self.tushare_catalog_service.sync_market_evidence,
                now.strftime("%Y%m%d"),
                "all_a",
            )
            logger.info("Post-close market evidence synced: %s", result)
        except Exception as e:
            logger.error("Error in post-close market evidence sync: %s", e)
    
    async def _sync_market_data(self):
        """
        同步市场数据（热门概念、基本面等）
        """
        try:
            logger.info("Starting market data sync")
            
            # 同步热门概念
            concept_result = await asyncio.to_thread(data_sync_service.sync_hot_concepts)
            logger.info(f"Concept sync completed: {concept_result}")
            
            # 同步基本面数据
            fundamental_result = await asyncio.to_thread(data_sync_service.sync_fundamentals)
            logger.info(f"Fundamentals sync completed: {fundamental_result}")
            
        except Exception as e:
            logger.error(f"Error in market data sync: {str(e)}")
    
    async def _sync_ths_hot(self):
        """
        同步同花顺热门股票数据
        """
        try:
            logger.info("Starting THS hot stocks sync")
            result = await asyncio.to_thread(data_sync_service.sync_ths_hot)
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
            await asyncio.to_thread(factor_sync_service.init_factor_definitions)
            
            # 同步所有因子数据
            result = await asyncio.to_thread(factor_sync_service.sync_all_factors)
            logger.info(f"Factor data sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in factor data sync: {str(e)}")
    
    async def _sync_zt_pool(self):
        """
        同步涨停连板数据（天级）
        """
        try:
            logger.info("Starting zt pool sync")
            result = await asyncio.to_thread(data_sync_service.sync_zt_pool)
            logger.info(f"ZT pool sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in zt pool sync: {str(e)}")
    
    async def _sync_dragon_tiger(self):
        """
        同步龙虎榜数据（天级）
        """
        try:
            logger.info("Starting dragon tiger board sync")
            result = await asyncio.to_thread(data_sync_service.sync_dragon_tiger)
            logger.info(f"Dragon tiger sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in dragon tiger sync: {str(e)}")
    
    async def _sync_northbound(self):
        """
        同步北向资金数据（天级）
        """
        try:
            logger.info("Starting northbound flow sync")
            result = await asyncio.to_thread(data_sync_service.sync_northbound_flow)
            logger.info(f"Northbound flow sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in northbound flow sync: {str(e)}")
    
    async def _advance_paper_instances(self):
        """
        推进运行中的 Paper 实例周期（天级，封存快照内幂等补齐）
        """
        try:
            from app.db import db_instance
            from app.services.paper_runtime_service import PaperRuntimeService

            logger.info("Starting paper instance cycle advance")
            result = await asyncio.to_thread(
                PaperRuntimeService(db_instance).advance_instances,
                max_dates=30,
            )
            logger.info(
                f"Paper cycle advance completed: {result.get('dates_processed')} dates "
                f"across {result.get('instances_attempted')} instances"
            )
        except Exception as e:
            logger.error(f"Error in paper cycle advance: {str(e)}")

    async def _sync_sector_realtime(self):
        """
        同步板块实时行情（小时级）
        """
        if not self._is_trading_time():
            logger.debug("Not trading time, skipping sector sync")
            return
        
        try:
            logger.info("Starting sector realtime sync")
            result = await asyncio.to_thread(data_sync_service.sync_sector_realtime)
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
            result = await asyncio.to_thread(data_sync_service.sync_realtime_stocks)
            logger.debug(f"Realtime stocks sync completed: {result}")
        except Exception as e:
            logger.error(f"Error in realtime stocks sync: {str(e)}")
    
    async def _sync_news(self):
        """
        同步快讯资讯（分钟级）
        """
        try:
            result = await asyncio.to_thread(data_sync_service.sync_news)
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
            result = await asyncio.to_thread(data_sync_service.sync_daily_concept_sectors)
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
            stock_result = await asyncio.to_thread(data_sync_service.sync_stock_history, date_str)
            logger.info(f"Initial stock sync completed: {stock_result}")
            
            # 同步其他数据
            concept_result = await asyncio.to_thread(data_sync_service.sync_hot_concepts)
            logger.info(f"Initial concept sync completed: {concept_result}")
            
            fundamental_result = await asyncio.to_thread(data_sync_service.sync_fundamentals)
            logger.info(f"Initial fundamentals sync completed: {fundamental_result}")
            
            ths_result = await asyncio.to_thread(data_sync_service.sync_ths_hot)
            logger.info(f"Initial THS sync completed: {ths_result}")
            
            # 初始化因子定义
            await asyncio.to_thread(factor_sync_service.init_factor_definitions)
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
