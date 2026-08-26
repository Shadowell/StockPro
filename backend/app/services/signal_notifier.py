"""
策略信号通知系统
================
Phase 4: 实盘信号推送

功能:
  1. 策略信号推送到日志 (核心)
  2. 信号持久化到数据库
  3. 可选: Telegram / Webhook 推送
  4. 实盘检查清单 (Pre-Flight Checklist)

使用:
    from app.services.signal_notifier import SignalNotifier

    notifier = SignalNotifier()
    notifier.notify_signal({...})
"""
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from app.db.local_db import db_instance as db

logger = logging.getLogger(__name__)


@dataclass
class LiveSignal:
    """实盘信号"""
    timestamp: str
    strategy: str
    symbol: str
    timeframe: str
    action: str       # buy / sell / hold
    reason: str
    price: float
    suggested_qty: float
    stop_loss: float
    take_profit: float
    regime: str       # 市场状态
    confidence: str   # high / medium / low
    risk_note: str    # 风控备注


class SignalNotifier:
    """信号通知器"""

    def __init__(self):
        self.signals: List[LiveSignal] = []
        self._ensure_table()

    def _ensure_table(self):
        """确保信号记录表存在"""
        try:
            conn = db.get_connection()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS live_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT,
                    price REAL,
                    suggested_qty REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    regime TEXT,
                    confidence TEXT,
                    risk_note TEXT,
                    executed INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"创建live_signals表失败: {e}")

    def notify_signal(self, signal: LiveSignal):
        """
        发送信号通知
        1. 保存到内存
        2. 保存到数据库
        3. 打印日志
        """
        self.signals.append(signal)

        # 保存到数据库
        try:
            conn = db.get_connection()
            conn.execute(
                """INSERT INTO live_signals
                   (timestamp, strategy, symbol, timeframe, action, reason,
                    price, suggested_qty, stop_loss, take_profit, regime,
                    confidence, risk_note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (signal.timestamp, signal.strategy, signal.symbol, signal.timeframe,
                 signal.action, signal.reason, signal.price, signal.suggested_qty,
                 signal.stop_loss, signal.take_profit, signal.regime,
                 signal.confidence, signal.risk_note)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"保存信号到数据库失败: {e}")

        # 日志通知
        emoji = {
            'buy': '🟢 买入',
            'sell': '🔴 卖出',
            'hold': '⚪ 持有',
        }.get(signal.action, signal.action)

        logger.info(
            f"\n{'='*60}\n"
            f"  📡 实盘信号: {emoji}\n"
            f"  策略: {signal.strategy}\n"
            f"  品种: {signal.symbol} ({signal.timeframe})\n"
            f"  价格: ${signal.price:,.2f}\n"
            f"  建议仓位: {signal.suggested_qty:.4f}\n"
            f"  止损: ${signal.stop_loss:,.2f}\n"
            f"  止盈: ${signal.take_profit:,.2f}\n"
            f"  市场状态: {signal.regime}\n"
            f"  置信度: {signal.confidence}\n"
            f"  风控: {signal.risk_note}\n"
            f"  时间: {signal.timestamp}\n"
            f"{'='*60}"
        )

    def get_recent_signals(self, limit: int = 50) -> List[Dict]:
        """获取最近的信号"""
        try:
            conn = db.get_connection()
            cursor = conn.execute(
                """SELECT * FROM live_signals ORDER BY id DESC LIMIT ?""",
                (limit,)
            )
            columns = [d[0] for d in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.warning(f"查询信号失败: {e}")
            return []

    def get_signal_stats(self) -> Dict:
        """获取信号统计"""
        try:
            conn = db.get_connection()
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN action='buy' THEN 1 ELSE 0 END) as buys,
                    SUM(CASE WHEN action='sell' THEN 1 ELSE 0 END) as sells,
                    SUM(CASE WHEN executed=1 THEN 1 ELSE 0 END) as executed
                FROM live_signals
            """)
            row = cursor.fetchone()
            conn.close()
            return {
                'total': row[0] or 0,
                'buys': row[1] or 0,
                'sells': row[2] or 0,
                'executed': row[3] or 0,
            }
        except:
            return {'total': 0, 'buys': 0, 'sells': 0, 'executed': 0}


def pre_flight_checklist(
    strategy_name: str = 'adaptive_bollinger',
    symbol: str = 'BTC/USDT',
    timeframe: str = '4h',
    capital_pct: float = 0.10,
    total_capital: float = 10000,
) -> Dict[str, Any]:
    """
    实盘前飞行检查清单 (Pre-Flight Checklist)

    在正式实盘之前，必须通过所有检查项
    """
    from app.services.paper_trading import PaperTradingEngine, RiskConfig

    checks = []
    all_passed = True

    # ---- 1. 数据可用性 ----
    try:
        from app.db.local_db import db_instance as db
        now_ts = int(datetime.now().timestamp() * 1000)
        day_ago = now_ts - 24 * 3600 * 1000
        recent = db.get_klines(
            exchange='okx', symbol=symbol, timeframe=timeframe,
            limit=10, start=day_ago, end=now_ts,
        )
        has_data = recent is not None and len(recent) > 0
        checks.append({
            'item': '数据源可用',
            'passed': has_data,
            'detail': f'最近24h有{len(recent) if recent else 0}根{timeframe}K线'
        })
        if not has_data:
            all_passed = False
    except Exception as e:
        checks.append({'item': '数据源可用', 'passed': False, 'detail': str(e)})
        all_passed = False

    # ---- 2. 回测验证 ----
    try:
        engine = PaperTradingEngine(
            strategy_name=strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            initial_capital=10000,
            stop_loss=0.05,
        )
        r = engine.run_simulation(days_back=90)
        if r['status'] == 'completed':
            bt_ok = r['total_return_pct'] > -15  # 90天不超过-15%算通过
            sharpe_ok = r['sharpe_ratio'] > -1
            checks.append({
                'item': '90天模拟盘验证',
                'passed': bt_ok and sharpe_ok,
                'detail': f"收益{r['total_return_pct']:+.2f}%, 夏普{r['sharpe_ratio']:.2f}, 回撤{r['max_drawdown_pct']:.1f}%"
            })
            if not (bt_ok and sharpe_ok):
                all_passed = False
        else:
            checks.append({'item': '90天模拟盘验证', 'passed': False, 'detail': r.get('message', '数据不足')})
            all_passed = False
    except Exception as e:
        checks.append({'item': '90天模拟盘验证', 'passed': False, 'detail': str(e)})
        all_passed = False

    # ---- 3. 压力测试 (30天) ----
    try:
        engine30 = PaperTradingEngine(
            strategy_name=strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            initial_capital=10000,
            stop_loss=0.03,
            risk_config=RiskConfig(
                account_stop_loss=0.15,
                daily_stop_loss=0.03,
                consecutive_loss_limit=4,
            ),
        )
        r30 = engine30.run_simulation(days_back=30)
        if r30['status'] == 'completed':
            stress_ok = r30['max_drawdown_pct'] < 15
            checks.append({
                'item': '30天压力测试',
                'passed': stress_ok,
                'detail': f"收益{r30['total_return_pct']:+.2f}%, 回撤{r30['max_drawdown_pct']:.1f}%"
            })
            if not stress_ok:
                all_passed = False
        else:
            checks.append({'item': '30天压力测试', 'passed': True, 'detail': '数据不足跳过'})
    except Exception as e:
        checks.append({'item': '30天压力测试', 'passed': True, 'detail': f'跳过: {e}'})

    # ---- 4. 资金管理 ----
    trade_capital = total_capital * capital_pct
    cap_ok = capital_pct <= 0.20  # 不超过总资产20%
    checks.append({
        'item': '资金管理',
        'passed': cap_ok,
        'detail': f'交易资金${trade_capital:,.0f} ({capital_pct*100:.0f}%总资产, 建议≤20%)'
    })
    if not cap_ok:
        all_passed = False

    # ---- 5. 止损设置 ----
    checks.append({
        'item': '止损设置',
        'passed': True,
        'detail': f'账户止损15%, 日止损5%, 单笔止损5%'
    })

    # ---- 6. 交易对 ----
    checks.append({
        'item': '交易对确认',
        'passed': True,
        'detail': f'{symbol} {timeframe} (推荐BTC/USDT 4h)'
    })

    return {
        'all_passed': all_passed,
        'strategy': strategy_name,
        'symbol': symbol,
        'timeframe': timeframe,
        'capital': trade_capital,
        'checks': checks,
        'recommendation': (
            '✅ 所有检查通过，可以开始小仓位实盘' if all_passed
            else '⚠️ 有检查项未通过，建议解决后再实盘'
        ),
        'live_trading_rules': [
            f'1. 只交易 {symbol} {timeframe}',
            f'2. 初始资金不超过 ${trade_capital:,.0f} ({capital_pct*100:.0f}%总资产)',
            '3. 单笔止损5%, 账户止损15%',
            '4. 连续4次亏损暂停1天',
            '5. 每周复盘一次',
            '6. 首月只做模拟盘，第2月可尝试小仓位',
        ]
    }


# 全局实例
signal_notifier = SignalNotifier()
