from __future__ import annotations
from datetime import time
from app.domain.instruments.adapters import AshareCashAdapter
from app.domain.instruments.models import InstrumentContract
from app.services.ashare_backtest_engine import AShareBacktestEngine,next_weekday
from decimal import Decimal

def engine()->AShareBacktestEngine:
    return AShareBacktestEngine(bars=[{'trade_date':'2026-08-20','symbol':'SH_600000','open':10,'close':10,'turnover':1000000},{'trade_date':'2026-08-21','symbol':'SH_600000','open':10,'close':10,'turnover':1000000}],intents=[],initial_cash=1_000_000,cost_model={'commission_rate':0.0003,'minimum_commission':5,'stamp_duty_rate':0.001,'transfer_fee_rate':0.00001,'max_participation_rate':0.1})
def test_calendar_lunch_and_next_session_semantics()->None:
    stock=InstrumentContract.stock('600000.SH','SSE','CNY',Decimal('0.01'),100,'浦发银行');sessions=AshareCashAdapter().calendar(stock).sessions
    assert sessions[0].end==time(11,30)and sessions[1].start==time(13,0)
    assert next_weekday('2026-08-21')=='2026-08-24'
def test_lot_t1_clear_and_short_rejections()->None:
    broker=engine();accepted=broker._resolve_quantity({'intent_type':'order','requested_value':100},{'quantity':100,'available_quantity':100},1_000_000,10);invalid_lot=broker._resolve_quantity({'intent_type':'order','requested_value':50},None,1_000_000,10);t1=broker._resolve_quantity({'intent_type':'order','requested_value':-100},{'quantity':100,'available_quantity':0},1_000_000,10);clear=broker._resolve_quantity({'intent_type':'order_target','requested_value':0},{'quantity':55,'available_quantity':55},1_000_000,10);short=broker._resolve_quantity({'intent_type':'order_target_percent','requested_value':-0.1},None,1_000_000,10)
    assert accepted==(100,None)and invalid_lot[1]=='INVALID_LOT_SIZE'and t1[1]=='T1_NOT_AVAILABLE'and clear==(-55,None)and short[1]=='SHORT_OR_LEVERAGE_NOT_SUPPORTED'
def test_limits_suspension_cost_capacity_and_no_future_data()->None:
    broker=engine();buy=broker._fees('buy',10_000);sell=broker._fees('sell',10_000)
    assert buy['commission']==5 and buy['tax']==0 and sell['tax']==10
    assert broker._affordable_quantity(100,10,1004)==0 and broker._affordable_quantity(100,10,1006)==100
    future_action={'symbol':'SH_600000','announcement_available_at':'2026-08-22','cash_div':1};positions={'SH_600000':{'quantity':100,'available_quantity':100,'avg_cost':10}};assert broker._apply_corporate_actions('2026-08-21',positions,0,[])==0
    assert broker._reason('LIMIT_UP') and broker._reason('LIMIT_DOWN') and broker._reason('SUSPENDED')
