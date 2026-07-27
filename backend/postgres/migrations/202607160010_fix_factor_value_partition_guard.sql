CREATE OR REPLACE FUNCTION prevent_published_factor_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_TABLE_NAME LIKE 'factor_daily_values%' THEN
        IF EXISTS (SELECT 1 FROM factor_compute_runs WHERE id = OLD.compute_run_id AND status = 'published') THEN
            RAISE EXCEPTION 'published factor values are immutable';
        END IF;
    ELSIF TG_TABLE_NAME = 'factor_snapshot_items' THEN
        IF EXISTS (SELECT 1 FROM factor_snapshots WHERE id = OLD.snapshot_id AND status = 'sealed') THEN
            RAISE EXCEPTION 'sealed factor snapshot is immutable';
        END IF;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
