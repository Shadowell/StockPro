"""
策略执行服务：管理Python策略脚本的执行、调度
使用项目的虚拟环境执行Python脚本
"""
import asyncio
import json
import logging
import subprocess
import sys
import tempfile
import threading
import time
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.db.local_db import db_instance as db

logger = logging.getLogger(__name__)

# 获取项目虚拟环境的Python解释器路径
def get_venv_python() -> str:
    """获取虚拟环境中的Python解释器路径"""
    # 获取backend目录
    current_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    
    # 虚拟环境的Python路径
    if sys.platform == 'win32':
        venv_python = os.path.join(current_dir, 'venv', 'Scripts', 'python.exe')
    else:
        venv_python = os.path.join(current_dir, 'venv', 'bin', 'python')
    
    # 如果虚拟环境存在，使用它；否则使用当前Python
    if os.path.exists(venv_python):
        logger.info(f"Using venv Python: {venv_python}")
        return venv_python
    else:
        logger.warning(f"Venv not found at {venv_python}, using system Python: {sys.executable}")
        return sys.executable

# 全局变量：虚拟环境Python路径
VENV_PYTHON = get_venv_python()


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
            return {
                'success': True,
                'id': strategy_id,
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
        """立即执行策略"""
        strategy = db.get_strategy_by_id(strategy_id)
        if not strategy:
            return {'success': False, 'error': 'Strategy not found'}
        
        return self._run_script(strategy_id, strategy['script_content'], strategy['name'])
    
    def _run_script(self, strategy_id: int, script_content: str, strategy_name: str) -> Dict[str, Any]:
        """执行Python脚本"""
        start_time = time.time()
        
        try:
            # 创建临时文件存放脚本
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                f.write(script_content)
                temp_script_path = f.name
            
            try:
                # 获取backend目录作为工作目录
                backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                
                # 设置环境变量，确保使用虚拟环境
                env = os.environ.copy()
                venv_dir = os.path.join(backend_dir, 'venv')
                if os.path.exists(venv_dir):
                    if sys.platform == 'win32':
                        env['PATH'] = os.path.join(venv_dir, 'Scripts') + os.pathsep + env.get('PATH', '')
                    else:
                        env['PATH'] = os.path.join(venv_dir, 'bin') + os.pathsep + env.get('PATH', '')
                    env['VIRTUAL_ENV'] = venv_dir
                
                # 使用虚拟环境的Python执行脚本
                result = subprocess.run(
                    [VENV_PYTHON, temp_script_path],
                    capture_output=True,
                    text=True,
                    timeout=300,  # 5分钟超时
                    cwd=backend_dir,
                    env=env
                )
                
                execution_duration_ms = int((time.time() - start_time) * 1000)
                
                if result.returncode == 0:
                    # 解析输出
                    output = result.stdout.strip()
                    try:
                        # 尝试解析JSON输出
                        parsed_output = json.loads(output)
                        result_data = json.dumps(parsed_output, ensure_ascii=False)
                    except json.JSONDecodeError:
                        # 如果不是JSON，包装为text格式
                        result_data = json.dumps({'raw_output': output}, ensure_ascii=False)
                    
                    # 保存成功结果
                    db.save_strategy_result(
                        strategy_id=strategy_id,
                        status='success',
                        result_data=result_data,
                        execution_duration_ms=execution_duration_ms
                    )
                    
                    logger.info(f"Strategy '{strategy_name}' executed successfully in {execution_duration_ms}ms")
                    
                    return {
                        'success': True,
                        'result': parsed_output if 'parsed_output' in dir() else {'raw_output': output},
                        'execution_time_ms': execution_duration_ms
                    }
                else:
                    # 执行失败
                    error_msg = result.stderr or f"Script exited with code {result.returncode}"
                    
                    db.save_strategy_result(
                        strategy_id=strategy_id,
                        status='failed',
                        error_message=error_msg,
                        execution_duration_ms=execution_duration_ms
                    )
                    
                    logger.error(f"Strategy '{strategy_name}' failed: {error_msg}")
                    
                    return {
                        'success': False,
                        'error': error_msg,
                        'execution_time_ms': execution_duration_ms
                    }
                    
            finally:
                # 清理临时文件
                try:
                    os.unlink(temp_script_path)
                except:
                    pass
                    
        except subprocess.TimeoutExpired:
            error_msg = "Script execution timed out (5 minutes)"
            db.save_strategy_result(
                strategy_id=strategy_id,
                status='failed',
                error_message=error_msg
            )
            return {'success': False, 'error': error_msg}
            
        except Exception as e:
            error_msg = str(e)
            db.save_strategy_result(
                strategy_id=strategy_id,
                status='failed',
                error_message=error_msg
            )
            logger.error(f"Error executing strategy: {e}")
            return {'success': False, 'error': error_msg}
    
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
            self._run_script(strategy_id, strategy['script_content'], strategy['name'])
    
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
