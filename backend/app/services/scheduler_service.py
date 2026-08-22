"""
定时调度服务
使用 APScheduler 管理定时任务：
- 每天凌晨自动同步最新K线数据
- 每小时检查数据完整性
"""
import asyncio
import logging
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class SchedulerService:
    """定时调度服务"""

    def __init__(self):
        self._scheduler: AsyncIOScheduler = None
        self._running = False

    async def start(self):
        """启动调度器"""
        if self._running:
            return

        self._scheduler = AsyncIOScheduler(
            timezone='Asia/Shanghai',
            job_defaults={
                'coalesce': True,          # 错过的任务合并执行一次
                'max_instances': 1,         # 同一任务最多1个实例
                'misfire_grace_time': 3600, # 错过1小时内的任务仍会执行
            }
        )

        # ---- 注册定时任务 ----

        # K 线同步统一由下方“数据中心定时同步”负责，避免旧的 11 现货
        # 日同步/快速同步与当前合约宇宙重复运行。

        # 4. 每日心跳播报（早/中/晚）
        for hour in (8, 16, 0):
            self._scheduler.add_job(
                self._heartbeat_job,
                CronTrigger(hour=hour, minute=0),
                id=f'heartbeat_{hour:02d}',
                name=f'系统心跳播报({hour:02d}:00)',
                kwargs={'exchange_name': 'okx'},
            )

        # 5. AI 预测后台补点：基于近期活跃目标持续落库，避免切页后预测中断
        self._scheduler.add_job(
            self._ai_prediction_keepalive_job,
            IntervalTrigger(seconds=25),
            id='ai_prediction_keepalive',
            name='AI预测后台补点',
        )

        # 6. AI Lab 现有策略自动优化：默认配置关闭，开启后每 4 小时扫描一次模拟盘低收益策略
        self._scheduler.add_job(
            self._ai_strategy_optimizer_job,
            IntervalTrigger(hours=4),
            id='ai_strategy_optimizer_4h',
            name='AI Lab现有策略自动优化',
        )

        # 7. 监控中心收益卡片推送：每分钟检查配置，实际推送间隔由配置控制
        self._scheduler.add_job(
            self._strategy_profit_push_job,
            IntervalTrigger(minutes=1),
            id='strategy_profit_push',
            name='运行策略收益卡片推送',
        )

        self._scheduler.add_job(
            self._live_profit_push_job,
            IntervalTrigger(minutes=1),
            id='live_profit_push',
            name='实盘收益卡片推送',
        )

        # 8. 数据中心可配置定时同步：每分钟检查一次配置，实际间隔和周期由数据中心控制
        self._scheduler.add_job(
            self._configured_data_sync_job,
            IntervalTrigger(minutes=1),
            id='configured_data_sync',
            name='数据中心定时同步',
        )

        # 9. 自动交易Agent内置定时扫描：每分钟检查配置，到期后创建 paper-only 研发任务
        self._scheduler.add_job(
            self._auto_agent_research_scan_job,
            IntervalTrigger(minutes=1),
            id='auto_agent_research_scan',
            name='自动交易Agent内置定时扫描',
        )

        # 10. OKX 星球自动发帖：每分钟检查配置，到期后只发布真实实盘合约持仓快照
        self._scheduler.add_job(
            self._orbit_auto_post_job,
            IntervalTrigger(minutes=1),
            id='okx_orbit_auto_post',
            name='OKX星球自动发帖',
        )

        self._scheduler.start()
        self._running = True
        self._register_default_ai_prediction_targets()

        logger.info("定时调度服务已启动")
        self._log_scheduled_jobs()

    async def stop(self):
        """停止调度器"""
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("定时调度服务已停止")

    # ============================================
    # 定时任务实现
    # ============================================

    async def _heartbeat_job(self, exchange_name: str = "okx"):
        """心跳播报：不阻塞主交易事件循环。"""
        try:
            from app.services.strategy_engine import strategy_engine
            from app.services.trading_service import trading_service
            from app.services.feishu_notifier import feishu_notifier

            risk = strategy_engine.get_risk_status()
            circuit = bool(risk.get("circuit_breaker"))
            status = "circuit_breaker" if circuit else "normal"
            strategies_running = len(strategy_engine.get_all_running())

            # 获取账户权益（失败时不抛出，避免任务中断调度器）
            try:
                equity = await trading_service._get_account_equity(exchange_name)
            except Exception as exc:
                logger.warning(f"[定时任务] 心跳获取权益失败: {exc}")
                equity = 0.0

            daily_pnl = float(risk.get("daily_pnl", 0) or 0)

            await feishu_notifier.notify_heartbeat({
                "status": status,
                "strategies_running": strategies_running,
                "equity": float(equity or 0),
                "daily_pnl": daily_pnl,
            })
            logger.info("[定时任务] 心跳播报完成")
        except Exception as e:
            logger.error(f"[定时任务] 心跳播报失败: {e}")

    async def run_heartbeat_now(self, exchange_name: str = "okx"):
        """用于手动触发一次心跳（验证/排障）。"""
        await self._heartbeat_job(exchange_name=exchange_name)

    async def _ai_prediction_keepalive_job(self):
        """后台持续补预测点（活跃目标 TTL 内生效）。"""
        try:
            from app.services.kairos_predictor import KAIROS_INFERENCE_ENABLED

            if not KAIROS_INFERENCE_ENABLED:
                logger.debug("[定时任务] Kairos 推理已关闭，跳过 AI 预测补点")
                return

            from app.services.ai_prediction_service import ai_prediction_service

            wrote = await ai_prediction_service.run_background_prediction_once(
                ttl_minutes=240,
                max_targets=6,
                lookback_limit=320,
            )
            if wrote > 0:
                logger.info("[定时任务] AI 预测补点完成，本轮写入 %d 个目标", wrote)
        except Exception as e:
            logger.error(f"[定时任务] AI 预测补点失败: {e}")

    async def _ai_strategy_optimizer_job(self):
        """每 4 小时扫描模拟盘低收益策略并触发 AI 优化。"""
        try:
            from app.services.strategy_optimizer_service import strategy_optimizer_service

            result = await strategy_optimizer_service.run_once(force=False)
            if result.get("skipped") == "disabled":
                logger.debug("[定时任务] AI Lab 现有策略自动优化未开启，跳过")
            else:
                logger.info("[定时任务] AI Lab 现有策略自动优化完成: %s", result)
        except Exception as e:
            logger.error("[定时任务] AI Lab 现有策略自动优化失败: %s", e)

    async def _strategy_profit_push_job(self):
        """按监控中心配置推送运行中策略收益卡片。"""
        try:
            from app.services.strategy_profit_push_service import strategy_profit_push_service

            result = await strategy_profit_push_service.run_due()
            skipped = result.get("skipped")
            if skipped in {"disabled", "not_due"}:
                logger.debug("[定时任务] 运行策略收益卡片推送跳过: %s", skipped)
            else:
                logger.info("[定时任务] 运行策略收益卡片推送完成: %s", result)
        except Exception as e:
            logger.error("[定时任务] 运行策略收益卡片推送失败: %s", e)

    async def _live_profit_push_job(self):
        """按监控中心配置推送实盘收益卡片。"""
        try:
            from app.services.live_profit_push_service import live_profit_push_service

            result = await live_profit_push_service.run_due()
            skipped = result.get("skipped")
            if skipped in {"disabled", "not_due"}:
                logger.debug("[定时任务] 实盘收益卡片推送跳过: %s", skipped)
            else:
                logger.info("[定时任务] 实盘收益卡片推送完成: %s", result)
        except Exception as e:
            logger.error("[定时任务] 实盘收益卡片推送失败: %s", e)

    async def _configured_data_sync_job(self):
        """按数据中心配置提交可恢复的数据同步任务。"""
        try:
            from app.domain.sync import sync_domain_service

            result = await sync_domain_service.run_scheduled_if_due()
            skipped = result.get("skipped")
            if skipped in {"disabled", "not_due", "sync_running"}:
                logger.debug("[定时任务] 数据中心定时同步跳过: %s", skipped)
            else:
                logger.info("[定时任务] 数据中心定时同步完成: %s", result)
        except Exception as e:
            logger.error("[定时任务] 数据中心定时同步失败: %s", e)

    async def _orbit_auto_post_job(self):
        """按 AI Lab 配置发布真实 OKX 实盘合约收益动态。"""
        try:
            from app.services.orbit_auto_post_service import orbit_auto_post_service

            result = await orbit_auto_post_service.run_due()
            skipped = result.get("skipped")
            if skipped in {"disabled", "not_due", "already_running"}:
                logger.debug("[定时任务] OKX星球自动发帖跳过: %s", skipped)
            else:
                logger.info("[定时任务] OKX星球自动发帖完成: %s", result)
        except Exception as e:
            logger.error("[定时任务] OKX星球自动发帖失败: %s", e)

    async def _auto_agent_research_scan_job(self):
        """按内置固定提示词定时创建自动交易Agent paper-only 研发任务。"""
        try:
            from app.api.v2.endpoints.agent import run_auto_agent_scheduled_scan_once

            result = await run_auto_agent_scheduled_scan_once(force=False)
            skipped = result.get("skipped")
            if skipped in {"disabled", "not_due", "research_already_running"}:
                logger.debug("[定时任务] 自动交易Agent定时扫描跳过: %s", skipped)
            else:
                logger.info("[定时任务] 自动交易Agent定时扫描已创建研发任务: %s", result)
        except Exception as e:
            logger.error("[定时任务] 自动交易Agent定时扫描失败: %s", e)

    def _register_default_ai_prediction_targets(self) -> None:
        """
        注册常驻 AI 预测目标。

        默认让 BTC/USDT 1m 即使没人打开行情页也持续预测并写入 ai_predictions。
        可通过 AI_PREDICTION_DEFAULT_TARGETS 覆盖，格式：
        okx:BTC/USDT:1m:30,okx:ETH/USDT:1m:30
        """
        try:
            from app.services.ai_prediction_service import ai_prediction_service

            raw = os.getenv("AI_PREDICTION_DEFAULT_TARGETS", "okx:BTC/USDT:1m:30")
            count = 0
            for item in raw.split(","):
                parts = [p.strip() for p in item.split(":")]
                if len(parts) < 3 or not all(parts[:3]):
                    continue
                exchange, symbol, timeframe = parts[:3]
                try:
                    steps = int(parts[3]) if len(parts) >= 4 and parts[3] else 30
                except ValueError:
                    steps = 30
                ai_prediction_service.register_pinned_target(
                    exchange,
                    symbol,
                    timeframe,
                    predict_steps=steps,
                )
                count += 1
            if count:
                logger.info("[定时任务] 已注册 %d 个常驻 AI 预测目标", count)
        except Exception as e:
            logger.error("[定时任务] 注册常驻 AI 预测目标失败: %s", e)

    # ============================================
    # 管理接口
    # ============================================

    def get_jobs(self):
        """获取所有定时任务"""
        if not self._scheduler:
            return []

        jobs = []
        for job in self._scheduler.get_jobs():
            next_run = job.next_run_time
            jobs.append({
                'id': job.id,
                'name': job.name,
                'next_run': next_run.strftime('%Y-%m-%d %H:%M:%S') if next_run else None,
                'trigger': str(job.trigger),
            })
        return jobs

    def _log_scheduled_jobs(self):
        """记录已注册的定时任务"""
        for job in self._scheduler.get_jobs():
            next_run = job.next_run_time
            logger.info(
                f"  定时任务: {job.name} "
                f"| 触发器: {job.trigger} "
                f"| 下次执行: {next_run.strftime('%Y-%m-%d %H:%M:%S') if next_run else 'N/A'}"
            )

    @property
    def is_running(self) -> bool:
        return self._running


# 全局实例
scheduler_service = SchedulerService()
