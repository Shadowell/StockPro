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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.services.data_sync_service import data_sync_service
from app.services.factor_sync_service import factor_sync_service
from app.db.local_db import db_instance as db


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
        conn = db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT
                    t.id,
                    t.name,
                    t.description,
                    t.sql_content,
                    t.cron_expression,
                    t.enabled,
                    t.created_at,
                    t.updated_at,
                    l.status AS last_status,
                    l.execution_start AS last_run,
                    l.error_message AS last_error
                FROM data_dev_tasks t
                LEFT JOIN data_dev_logs l
                    ON l.id = (
                        SELECT id
                        FROM data_dev_logs
                        WHERE task_id = t.id
                        ORDER BY execution_start DESC, id DESC
                        LIMIT 1
                    )
                ORDER BY t.updated_at DESC, t.id DESC
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "sql_content": row[3],
                    "cron_expression": row[4],
                    "enabled": bool(row[5]),
                    "created_at": row[6],
                    "updated_at": row[7],
                    "last_status": row[8],
                    "last_run": row[9],
                    "last_error": row[10],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def add_data_dev_task(
        self,
        name: str,
        description: str,
        sql_content: str,
        cron_expression: str,
        enabled: bool = True,
    ) -> int:
        conn = db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO data_dev_tasks (name, description, sql_content, cron_expression, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (name, description, sql_content, cron_expression, 1 if enabled else 0),
            )
            task_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()

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
        updates: List[str] = []
        values: List[Any] = []
        if name is not None:
            updates.append("name = ?")
            values.append(name)
        if description is not None:
            updates.append("description = ?")
            values.append(description)
        if sql_content is not None:
            updates.append("sql_content = ?")
            values.append(sql_content)
        if cron_expression is not None:
            updates.append("cron_expression = ?")
            values.append(cron_expression)
        if enabled is not None:
            updates.append("enabled = ?")
            values.append(1 if enabled else 0)

        if not updates:
            return

        updates.append("updated_at = datetime('now')")
        values.append(task_id)

        conn = db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"UPDATE data_dev_tasks SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                raise ValueError("Task not found")
            conn.commit()

            cursor.execute(
                "SELECT cron_expression, enabled FROM data_dev_tasks WHERE id = ?",
                (task_id,),
            )
            row = cursor.fetchone()
        finally:
            conn.close()

        if not row:
            raise ValueError("Task not found")

        next_cron, next_enabled = row[0], bool(row[1])
        if next_enabled:
            self._schedule_data_dev_task(task_id, next_cron)
        else:
            self._unschedule_data_dev_task(task_id)

    def delete_data_dev_task(self, task_id: int) -> None:
        self._unschedule_data_dev_task(task_id)
        conn = db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM data_dev_logs WHERE task_id = ?", (task_id,))
            cursor.execute("DELETE FROM data_dev_tasks WHERE id = ?", (task_id,))
            if cursor.rowcount == 0:
                raise ValueError("Task not found")
            conn.commit()
        finally:
            conn.close()

    def get_task_logs(self, task_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        conn = db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, execution_start, execution_end, status, error_message, affected_rows
                FROM data_dev_logs
                WHERE task_id = ?
                ORDER BY execution_start DESC, id DESC
                LIMIT ?
                """,
                (task_id, max(1, min(int(limit), 500))),
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "execution_start": row[1],
                    "execution_end": row[2],
                    "status": row[3],
                    "error_message": row[4],
                    "affected_rows": row[5],
                }
                for row in rows
            ]
        finally:
            conn.close()

    async def _execute_data_dev_task_job(self, task_id: int) -> None:
        conn = db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT name, sql_content, enabled FROM data_dev_tasks WHERE id = ?",
                (task_id,),
            )
            row = cursor.fetchone()
        finally:
            conn.close()

        if not row:
            logger.warning("Data-dev task not found: %s", task_id)
            self._unschedule_data_dev_task(task_id)
            return

        if not bool(row[2]):
            return

        await self.execute_data_dev_task(task_id=task_id, sql_content=row[1], task_name=row[0])

    def _execute_data_dev_task_sync(self, task_id: int, sql_content: str, task_name: str) -> Dict[str, Any]:
        conn = db.get_connection()
        cursor = conn.cursor()
        log_id: Optional[int] = None
        affected_rows = 0
        try:
            cursor.execute(
                """
                INSERT INTO data_dev_logs (task_id, execution_start, status)
                VALUES (?, datetime('now'), 'running')
                """,
                (task_id,),
            )
            log_id = cursor.lastrowid
            conn.commit()

            statements = [stmt.strip() for stmt in sql_content.split(";") if stmt.strip()]
            for stmt in statements:
                cursor.execute(stmt)
                if cursor.rowcount and cursor.rowcount > 0:
                    affected_rows += int(cursor.rowcount)

            cursor.execute(
                """
                UPDATE data_dev_logs
                SET execution_end = datetime('now'), status = 'success', affected_rows = ?, error_message = NULL
                WHERE id = ?
                """,
                (affected_rows, log_id),
            )
            cursor.execute(
                "UPDATE data_dev_tasks SET updated_at = datetime('now') WHERE id = ?",
                (task_id,),
            )
            conn.commit()
            logger.info("Data-dev task executed successfully: %s(%s), affected_rows=%s", task_name, task_id, affected_rows)
            return {"status": "success", "affected_rows": affected_rows}
        except Exception as e:
            conn.rollback()
            if log_id is not None:
                try:
                    cursor.execute(
                        """
                        UPDATE data_dev_logs
                        SET execution_end = datetime('now'), status = 'failed', error_message = ?
                        WHERE id = ?
                        """,
                        (str(e), log_id),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
            logger.error("Data-dev task failed: %s(%s), error=%s", task_name, task_id, e)
            raise
        finally:
            conn.close()

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
