CREATE OR REPLACE FUNCTION stockpro_prevent_sealed_dataset_snapshot_mutation()
RETURNS TRIGGER AS $$
DECLARE
    target_snapshot_id BIGINT;
BEGIN
    IF TG_TABLE_NAME = 'dataset_snapshots' THEN
        IF OLD.status = 'sealed' THEN
            RAISE EXCEPTION 'sealed dataset snapshot is immutable';
        END IF;
    ELSIF TG_TABLE_NAME = 'dataset_snapshot_items' THEN
        target_snapshot_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.snapshot_id ELSE NEW.snapshot_id END;
        IF EXISTS (SELECT 1 FROM dataset_snapshots WHERE id = target_snapshot_id AND status = 'sealed') THEN
            RAISE EXCEPTION 'sealed dataset snapshot items are immutable';
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
