ALTER TABLE alert_rules ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE alert_rules ADD COLUMN IF NOT EXISTS rule_type TEXT;
ALTER TABLE alert_rules ADD COLUMN IF NOT EXISTS data_purpose TEXT;
ALTER TABLE alert_rules ADD COLUMN IF NOT EXISTS last_evaluated_at TIMESTAMPTZ;

UPDATE alert_rules SET name = code WHERE name IS NULL;
UPDATE alert_rules SET rule_type = 'system' WHERE rule_type IS NULL;
UPDATE alert_rules SET data_purpose = 'seed' WHERE data_purpose IS NULL;

ALTER TABLE alert_rules ALTER COLUMN name SET NOT NULL;
ALTER TABLE alert_rules ALTER COLUMN rule_type SET NOT NULL;
ALTER TABLE alert_rules ALTER COLUMN data_purpose SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'alert_rules_rule_type_check'
    ) THEN
        ALTER TABLE alert_rules ADD CONSTRAINT alert_rules_rule_type_check
            CHECK (rule_type IN ('system','strategy','indicator','price','abnormal'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'alert_rules_data_purpose_check'
    ) THEN
        ALTER TABLE alert_rules ADD CONSTRAINT alert_rules_data_purpose_check
            CHECK (data_purpose IN ('user','acceptance','seed'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_alert_rules_latest
    ON alert_rules(code, rule_version DESC, created_at DESC);
