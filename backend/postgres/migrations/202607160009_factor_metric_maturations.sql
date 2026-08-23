CREATE TABLE IF NOT EXISTS factor_metric_evaluations (
    id BIGSERIAL PRIMARY KEY,
    source_compute_run_id BIGINT NOT NULL REFERENCES factor_compute_runs(id),
    evaluation_dataset_snapshot_id BIGINT NOT NULL REFERENCES dataset_snapshots(id),
    knowledge_cutoff_at TIMESTAMPTZ NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'sealed', 'failed')),
    result_hash TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sealed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_factor_metric_evaluations_source
    ON factor_metric_evaluations(source_compute_run_id, knowledge_cutoff_at DESC);

CREATE TABLE IF NOT EXISTS factor_matured_metrics (
    evaluation_id BIGINT NOT NULL REFERENCES factor_metric_evaluations(id) ON DELETE RESTRICT,
    source_compute_run_id BIGINT NOT NULL REFERENCES factor_compute_runs(id) ON DELETE RESTRICT,
    factor_version_id BIGINT NOT NULL REFERENCES factor_versions(id) ON DELETE RESTRICT,
    factor_trade_date DATE NOT NULL,
    metric_code TEXT NOT NULL,
    horizon INTEGER,
    metric_value DOUBLE PRECISION,
    metric_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (evaluation_id, metric_code, horizon)
);

CREATE INDEX IF NOT EXISTS idx_factor_matured_metrics_lookup
    ON factor_matured_metrics(source_compute_run_id, metric_code, horizon, evaluation_id DESC);

CREATE OR REPLACE FUNCTION prevent_sealed_factor_evaluation_mutation()
RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM factor_metric_evaluations
        WHERE id = COALESCE(OLD.evaluation_id, NEW.evaluation_id) AND status = 'sealed'
    ) THEN
        RAISE EXCEPTION 'sealed factor metric evaluation is immutable';
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_protect_sealed_factor_matured_metrics ON factor_matured_metrics;
CREATE TRIGGER trg_protect_sealed_factor_matured_metrics
BEFORE UPDATE OR DELETE ON factor_matured_metrics
FOR EACH ROW EXECUTE FUNCTION prevent_sealed_factor_evaluation_mutation();
