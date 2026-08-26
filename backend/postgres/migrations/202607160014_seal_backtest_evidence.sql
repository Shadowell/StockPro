-- Sprint 04: immutable research protocol, cost model, and sealed backtest evidence.

CREATE OR REPLACE FUNCTION prevent_immutable_reference_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% rows are immutable; create a new version instead', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_backtest_cost_model_immutable ON backtest_cost_models;
CREATE TRIGGER trg_backtest_cost_model_immutable
BEFORE UPDATE OR DELETE ON backtest_cost_models
FOR EACH ROW EXECUTE FUNCTION prevent_immutable_reference_mutation();

CREATE OR REPLACE FUNCTION prevent_sealed_protocol_mutation()
RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'sealed' THEN
        RAISE EXCEPTION 'sealed research protocol is immutable; create a new protocol instead';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_research_protocol_immutable ON research_protocols;
CREATE TRIGGER trg_research_protocol_immutable
BEFORE UPDATE OR DELETE ON research_protocols
FOR EACH ROW EXECUTE FUNCTION prevent_sealed_protocol_mutation();

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
        OLD.result_api_version IS DISTINCT FROM NEW.result_api_version OR
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

CREATE OR REPLACE FUNCTION prevent_sealed_backtest_child_mutation()
RETURNS trigger AS $$
DECLARE
    run_id UUID;
    run_status TEXT;
BEGIN
    run_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.backtest_run_id ELSE NEW.backtest_run_id END;
    SELECT status INTO run_status FROM backtest_runs WHERE id = run_id;
    IF run_status = 'success' THEN
        RAISE EXCEPTION 'sealed backtest evidence is immutable';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'backtest_metrics', 'backtest_daily_equity', 'backtest_orders', 'backtest_trades',
        'backtest_daily_positions', 'backtest_logs', 'backtest_custom_records', 'backtest_attribution'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%I_sealed ON %I', table_name, table_name);
        EXECUTE format(
            'CREATE TRIGGER trg_%I_sealed BEFORE INSERT OR UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION prevent_sealed_backtest_child_mutation()',
            table_name,
            table_name
        );
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION prevent_backtest_assessment_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'backtest assessment evidence is append-only';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_backtest_protocol_evaluations_append_only ON backtest_protocol_evaluations;
CREATE TRIGGER trg_backtest_protocol_evaluations_append_only
BEFORE UPDATE OR DELETE ON backtest_protocol_evaluations
FOR EACH ROW EXECUTE FUNCTION prevent_backtest_assessment_mutation();

DROP TRIGGER IF EXISTS trg_backtest_promotion_checks_append_only ON backtest_promotion_checks;
CREATE TRIGGER trg_backtest_promotion_checks_append_only
BEFORE UPDATE OR DELETE ON backtest_promotion_checks
FOR EACH ROW EXECUTE FUNCTION prevent_backtest_assessment_mutation();
