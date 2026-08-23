-- Sprint 04: align the immutability trigger with the persisted backtest_runs schema.

CREATE OR REPLACE FUNCTION prevent_sealed_backtest_mutation()
RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'success' AND (
        NEW.status IS DISTINCT FROM 'success' OR
        OLD.strategy_version_id IS DISTINCT FROM NEW.strategy_version_id OR
        OLD.dataset_snapshot_id IS DISTINCT FROM NEW.dataset_snapshot_id OR
        OLD.factor_snapshot_id IS DISTINCT FROM NEW.factor_snapshot_id OR
        OLD.universe_snapshot_id IS DISTINCT FROM NEW.universe_snapshot_id OR
        OLD.corporate_action_snapshot_id IS DISTINCT FROM NEW.corporate_action_snapshot_id OR
        OLD.research_protocol_id IS DISTINCT FROM NEW.research_protocol_id OR
        OLD.parameters IS DISTINCT FROM NEW.parameters OR
        OLD.start_date IS DISTINCT FROM NEW.start_date OR
        OLD.end_date IS DISTINCT FROM NEW.end_date OR
        OLD.cost_model_id IS DISTINCT FROM NEW.cost_model_id OR
        OLD.benchmark_code IS DISTINCT FROM NEW.benchmark_code OR
        OLD.input_hash IS DISTINCT FROM NEW.input_hash OR
        OLD.initial_cash IS DISTINCT FROM NEW.initial_cash OR
        OLD.frequency IS DISTINCT FROM NEW.frequency OR
        OLD.metrics IS DISTINCT FROM NEW.metrics OR
        OLD.calculation_version IS DISTINCT FROM NEW.calculation_version OR
        OLD.result_manifest IS DISTINCT FROM NEW.result_manifest OR
        OLD.finished_at IS DISTINCT FROM NEW.finished_at OR
        OLD.sealed_at IS DISTINCT FROM NEW.sealed_at
    ) THEN
        RAISE EXCEPTION 'sealed backtest inputs and result evidence are immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
