CREATE OR REPLACE FUNCTION stockpro_prevent_sealed_dataset_snapshot_mutation()
RETURNS TRIGGER AS $$
DECLARE
    target_snapshot_id BIGINT;
BEGIN
    IF TG_TABLE_NAME = 'dataset_snapshots' AND OLD.status = 'sealed' THEN
        RAISE EXCEPTION 'sealed dataset snapshot is immutable';
    END IF;

    IF TG_TABLE_NAME = 'dataset_snapshot_items' THEN
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

DROP TRIGGER IF EXISTS prevent_sealed_dataset_snapshot_items_mutation ON dataset_snapshot_items;
CREATE TRIGGER prevent_sealed_dataset_snapshot_items_mutation
BEFORE INSERT OR UPDATE OR DELETE ON dataset_snapshot_items
FOR EACH ROW EXECUTE FUNCTION stockpro_prevent_sealed_dataset_snapshot_mutation();
