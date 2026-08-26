-- Sprint 05: freeze rule versions and completed generation evidence.

CREATE OR REPLACE FUNCTION prevent_stock_pool_evidence_mutation()
RETURNS trigger AS $$
DECLARE
    generation_status TEXT;
BEGIN
    IF TG_TABLE_NAME = 'stock_pool_rules' THEN
        RAISE EXCEPTION 'stock-pool rule versions are immutable';
    END IF;
    IF TG_TABLE_NAME = 'stock_pool_generations' THEN
        IF OLD.status IN ('success', 'failed') THEN
            RAISE EXCEPTION 'completed stock-pool generation is immutable';
        END IF;
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    SELECT status INTO generation_status
    FROM stock_pool_generations
    WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.generation_id ELSE NEW.generation_id END;
    IF generation_status IN ('success', 'failed') THEN
        RAISE EXCEPTION 'completed stock-pool members are immutable';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_stock_pool_rule_immutable ON stock_pool_rules;
CREATE TRIGGER trg_stock_pool_rule_immutable
BEFORE UPDATE OR DELETE ON stock_pool_rules
FOR EACH ROW EXECUTE FUNCTION prevent_stock_pool_evidence_mutation();

DROP TRIGGER IF EXISTS trg_stock_pool_generation_immutable ON stock_pool_generations;
CREATE TRIGGER trg_stock_pool_generation_immutable
BEFORE UPDATE OR DELETE ON stock_pool_generations
FOR EACH ROW EXECUTE FUNCTION prevent_stock_pool_evidence_mutation();

DROP TRIGGER IF EXISTS trg_stock_pool_member_immutable ON stock_pool_members;
CREATE TRIGGER trg_stock_pool_member_immutable
BEFORE UPDATE OR DELETE ON stock_pool_members
FOR EACH ROW EXECUTE FUNCTION prevent_stock_pool_evidence_mutation();
