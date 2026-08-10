-- Persist business, acceptance and seed ownership so operator counts are deterministic.

ALTER TABLE strategy_scripts ADD COLUMN IF NOT EXISTS data_purpose TEXT;
ALTER TABLE paper_instances ADD COLUMN IF NOT EXISTS data_purpose TEXT;
ALTER TABLE stock_pools ADD COLUMN IF NOT EXISTS data_purpose TEXT;

UPDATE strategy_scripts
SET data_purpose = CASE
    WHEN lower(coalesce(name, '') || ' ' || coalesce(description, '')) ~ '(^|[^a-z])(acceptance|fixture|smoke|sprint[-_ ]*[0-9]*|qa|test)([^a-z]|$)'
         OR coalesce(name, '') || coalesce(description, '') ~ '(验收|演练|测试)'
        THEN 'acceptance'
    WHEN lower(coalesce(name, '') || ' ' || coalesce(description, '')) ~ '(^|[^a-z])(seed|demo|sample)([^a-z]|$)'
         OR coalesce(name, '') || coalesce(description, '') ~ '(示例|样例)'
        THEN 'seed'
    ELSE 'user'
END
WHERE data_purpose IS NULL;

UPDATE paper_instances
SET data_purpose = CASE
    WHEN lower(coalesce(name, '')) ~ '(^|[^a-z])(acceptance|fixture|smoke|sprint[-_ ]*[0-9]*|qa|test)([^a-z]|$)'
         OR coalesce(name, '') ~ '(验收|演练|测试)'
        THEN 'acceptance'
    WHEN lower(coalesce(name, '')) ~ '(^|[^a-z])(seed|demo|sample)([^a-z]|$)'
         OR coalesce(name, '') ~ '(示例|样例)'
        THEN 'seed'
    ELSE 'user'
END
WHERE data_purpose IS NULL;

UPDATE stock_pools
SET data_purpose = CASE
    WHEN lower(coalesce(name, '') || ' ' || coalesce(description, '')) ~ '(^|[^a-z])(acceptance|fixture|smoke|sprint[-_ ]*[0-9]*|qa|test)([^a-z]|$)'
         OR coalesce(name, '') || coalesce(description, '') ~ '(验收|演练|测试)'
        THEN 'acceptance'
    WHEN lower(coalesce(name, '') || ' ' || coalesce(description, '')) ~ '(^|[^a-z])(seed|demo|sample)([^a-z]|$)'
         OR coalesce(name, '') || coalesce(description, '') ~ '(示例|样例)'
        THEN 'seed'
    ELSE 'user'
END
WHERE data_purpose IS NULL;

ALTER TABLE strategy_scripts ALTER COLUMN data_purpose SET DEFAULT 'user';
ALTER TABLE strategy_scripts ALTER COLUMN data_purpose SET NOT NULL;
ALTER TABLE strategy_scripts ADD CONSTRAINT strategy_scripts_data_purpose_check
    CHECK (data_purpose IN ('user', 'acceptance', 'seed'));

ALTER TABLE paper_instances ALTER COLUMN data_purpose SET DEFAULT 'user';
ALTER TABLE paper_instances ALTER COLUMN data_purpose SET NOT NULL;
ALTER TABLE paper_instances ADD CONSTRAINT paper_instances_data_purpose_check
    CHECK (data_purpose IN ('user', 'acceptance', 'seed'));

ALTER TABLE stock_pools ALTER COLUMN data_purpose SET DEFAULT 'user';
ALTER TABLE stock_pools ALTER COLUMN data_purpose SET NOT NULL;
ALTER TABLE stock_pools ADD CONSTRAINT stock_pools_data_purpose_check
    CHECK (data_purpose IN ('user', 'acceptance', 'seed'));

CREATE INDEX IF NOT EXISTS idx_strategy_scripts_data_purpose ON strategy_scripts(data_purpose);
CREATE INDEX IF NOT EXISTS idx_paper_instances_data_purpose ON paper_instances(data_purpose);
CREATE INDEX IF NOT EXISTS idx_stock_pools_data_purpose ON stock_pools(data_purpose);
