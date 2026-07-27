"""
策略执行服务：管理Python策略脚本的执行、调度
使用项目的虚拟环境执行Python脚本
"""
import logging
import threading
import psycopg2.extras
from typing import Dict, List, Any, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.db import db_instance as db

logger = logging.getLogger(__name__)

class StrategyExecutionService:
    """
    策略执行服务
    - 管理策略脚本的保存、执行
    - 支持定时调度执行
    - 记录执行结果
    """
    
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.running_strategies: Dict[int, str] = {}  # strategy_id -> job_id
        self._lock = threading.Lock()
        self._started = False
    
    def start(self):
        """启动调度器"""
        if not self._started:
            self.scheduler.start()
            self._started = True
            logger.info("Strategy execution scheduler started")
            
            # 恢复之前运行中的策略
            self._restore_running_strategies()
    
    def stop(self):
        """停止调度器"""
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False
            logger.info("Strategy execution scheduler stopped")
    
    def _restore_running_strategies(self):
        """恢复之前标记为运行中的策略"""
        try:
            running = db.get_running_strategies()
            for strategy in running:
                logger.info(f"Restoring running strategy: {strategy['name']} (id={strategy['id']})")
                self._schedule_strategy(strategy['id'], strategy['interval_seconds'])
        except Exception as e:
            logger.error(f"Error restoring running strategies: {e}")
    
    # ============ 策略管理 ============
    
    def save_strategy(self, name: str, script_content: str, description: str = '',
                      interval_seconds: int = 60) -> Dict[str, Any]:
        """保存策略脚本"""
        try:
            strategy_id = db.save_strategy(
                name=name,
                script_content=script_content,
                description=description,
                interval_seconds=interval_seconds
            )
            from app.services.strategy_runtime_service import StrategyRuntimeService
            version_result = StrategyRuntimeService(db).ensure_legacy_version(
                strategy_id,
                db.get_strategy_by_id(strategy_id) or {},
            )
            return {
                'success': True,
                'id': strategy_id,
                'strategy_version': version_result.get('strategy_version'),
                'validation': version_result.get('validation'),
                'message': f'Strategy "{name}" saved successfully'
            }
        except Exception as e:
            logger.error(f"Error saving strategy: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_strategies(self) -> List[Dict]:
        """获取所有策略"""
        return db.get_strategies()
    
    def get_strategy(self, strategy_id: int) -> Optional[Dict]:
        """获取单个策略"""
        return db.get_strategy_by_id(strategy_id)

    def update_strategy(
        self,
        strategy_id: int,
        name: str,
        script_content: str,
        description: str = "",
        interval_seconds: int = 60,
    ) -> Dict[str, Any]:
        """按 ID 更新策略脚本"""
        try:
            strategy = db.update_strategy(
                strategy_id=strategy_id,
                name=name,
                script_content=script_content,
                description=description,
                interval_seconds=interval_seconds,
            )
            if not strategy:
                return {"success": False, "error": "Strategy not found"}
            from app.services.strategy_runtime_service import StrategyRuntimeService
            version_result = StrategyRuntimeService(db).ensure_legacy_version(strategy_id, strategy)
            return {**strategy, "success": True, "strategy_version": version_result.get("strategy_version"), "validation": version_result.get("validation")}
        except Exception as e:
            logger.error(f"Error updating strategy: {e}")
            return {"success": False, "error": str(e)}
    
    def delete_strategy(self, strategy_id: int) -> Dict[str, Any]:
        """删除策略"""
        try:
            # 先停止运行中的策略
            if strategy_id in self.running_strategies:
                self.stop_strategy(strategy_id)
            
            success = db.delete_strategy(strategy_id)
            if success:
                return {'success': True, 'message': 'Strategy deleted'}
            else:
                return {'success': False, 'error': 'Strategy not found'}
        except Exception as e:
            logger.error(f"Error deleting strategy: {e}")
            return {'success': False, 'error': str(e)}
    
    # ============ 策略执行 ============
    
    def execute_strategy(self, strategy_id: int) -> Dict[str, Any]:
        """Use the shared snapshot replay runtime; never execute arbitrary stdout scripts."""
        strategy = db.get_strategy_by_id(strategy_id)
        if not strategy:
            return {'success': False, 'error': 'Strategy not found'}
        from app.services.strategy_runtime_service import StrategyRuntimeService
        runtime = StrategyRuntimeService(db)
        version_result = runtime.ensure_legacy_version(strategy_id, strategy)
        version = version_result.get("strategy_version") or {}
        if (version_result.get("validation") or {}).get("valid") is not True:
            return {"success": False, "error": "Strategy API v1 validation failed", "validation": version_result.get("validation")}
        with db.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT id FROM dataset_snapshots WHERE status='sealed' ORDER BY trade_date DESC NULLS LAST, id DESC LIMIT 1")
                row = cursor.fetchone()
        if not row:
            return {"success": False, "error": "No sealed dataset snapshot"}
        result = runtime.replay(str(version["id"]), {"dataset_snapshot_id": int(row["id"]), "mode": "quick", "event_limit": 30})
        return {"success": result.get("status") == "success", "result": result}
    
    # ============ 策略调度 ============
    
    def start_strategy(self, strategy_id: int, interval_seconds: int = None) -> Dict[str, Any]:
        """启动策略定时执行"""
        strategy = db.get_strategy_by_id(strategy_id)
        if not strategy:
            return {'success': False, 'error': 'Strategy not found'}
        
        with self._lock:
            if strategy_id in self.running_strategies:
                return {'success': False, 'error': 'Strategy is already running'}
            
            interval = interval_seconds or strategy['interval_seconds']
            
            # 更新数据库中的间隔时间
            if interval_seconds:
                db.save_strategy(
                    name=strategy['name'],
                    script_content=strategy['script_content'],
                    description=strategy['description'],
                    interval_seconds=interval_seconds
                )
            
            success = self._schedule_strategy(strategy_id, interval)
            
            if success:
                db.update_strategy_running_status(strategy_id, True)
                return {
                    'success': True,
                    'message': f'Strategy started with {interval}s interval'
                }
            else:
                return {'success': False, 'error': 'Failed to schedule strategy'}
    
    def _schedule_strategy(self, strategy_id: int, interval_seconds: int) -> bool:
        """内部方法：添加调度任务"""
        try:
            job_id = f"strategy_{strategy_id}"
            
            # 移除已存在的任务
            existing_job = self.scheduler.get_job(job_id)
            if existing_job:
                self.scheduler.remove_job(job_id)
            
            # 添加新任务
            self.scheduler.add_job(
                func=self._execute_scheduled_strategy,
                trigger=IntervalTrigger(seconds=interval_seconds),
                id=job_id,
                args=[strategy_id],
                replace_existing=True
            )
            
            self.running_strategies[strategy_id] = job_id
            logger.info(f"Scheduled strategy {strategy_id} with interval {interval_seconds}s")
            return True
            
        except Exception as e:
            logger.error(f"Error scheduling strategy {strategy_id}: {e}")
            return False
    
    def _execute_scheduled_strategy(self, strategy_id: int):
        """执行调度的策略"""
        strategy = db.get_strategy_by_id(strategy_id)
        if strategy:
            self.execute_strategy(strategy_id)
    
    def stop_strategy(self, strategy_id: int) -> Dict[str, Any]:
        """停止策略定时执行"""
        with self._lock:
            if strategy_id not in self.running_strategies:
                # 可能数据库中标记为运行但实际未调度
                db.update_strategy_running_status(strategy_id, False)
                return {'success': True, 'message': 'Strategy stopped'}
            
            job_id = self.running_strategies[strategy_id]
            
            try:
                self.scheduler.remove_job(job_id)
            except Exception as e:
                logger.warning(f"Job {job_id} not found when stopping: {e}")
            
            del self.running_strategies[strategy_id]
            db.update_strategy_running_status(strategy_id, False)
            
            logger.info(f"Strategy {strategy_id} stopped")
            return {'success': True, 'message': 'Strategy stopped'}
    
    def get_running_strategies(self) -> List[Dict]:
        """获取正在运行的策略"""
        return db.get_running_strategies()
    
    # ============ 执行结果 ============
    
    def get_strategy_results(self, strategy_id: int, limit: int = 50) -> List[Dict]:
        """获取策略执行结果"""
        return db.get_strategy_results(strategy_id, limit)
    
    def get_latest_result(self, strategy_id: int) -> Optional[Dict]:
        """获取最新执行结果"""
        return db.get_latest_strategy_result(strategy_id)


# 全局实例
strategy_execution_service = StrategyExecutionService()
