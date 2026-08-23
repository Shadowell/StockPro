-- Sprint 06: database-level duplicate prevention for restart-safe cycles.

CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_order_signal
    ON orders(paper_instance_id,signal_id) WHERE paper_instance_id IS NOT NULL AND signal_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_trade_order
    ON trades(paper_instance_id,order_id) WHERE paper_instance_id IS NOT NULL AND order_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_cash_order
    ON cash_ledger(paper_instance_id,ref_type,ref_id) WHERE paper_instance_id IS NOT NULL AND ref_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_risk_order_rule
    ON risk_events(paper_instance_id,order_id,rule_id) WHERE paper_instance_id IS NOT NULL AND order_id IS NOT NULL AND rule_id IS NOT NULL;
