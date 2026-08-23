from __future__ import annotations
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
BACKEND_ROOT=Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT)not in sys.path:sys.path.insert(0,str(BACKEND_ROOT))
from app.domain.instruments.adapters import AshareCashAdapter
from app.domain.instruments.models import InstrumentContract

def test_future_contract_accepts_real_metadata_without_defaults()->None:
    future=InstrumentContract(symbol='IF2609.CFFEX',name='沪深300股指期货2609',asset_class='future',market='CN',exchange='CFFEX',currency='CNY',tick_size=Decimal('0.2'),lot_size=1,contract_multiplier=Decimal('300'),margin_rate=None,expiry_date=date(2026,9,18),last_trade_date=date(2026,9,18),settlement_type='cash',session_calendar='CFFEX_INDEX_FUTURE',shortable=True)
    assert future.margin_rate is None and future.contract_multiplier==Decimal('300')
def test_only_cash_adapter_is_instantiated()->None:
    stock=InstrumentContract.stock('600519.SH','SSE','CNY',Decimal('0.01'),100,'贵州茅台');rules=AshareCashAdapter().execution_rules(stock)
    assert rules.t_plus_days==1 and rules.lot_size==100 and rules.shortable is False
