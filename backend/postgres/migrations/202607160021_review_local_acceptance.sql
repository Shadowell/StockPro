-- Sprint 07: immutable daily review references, local QA drills and backup/restore evidence.

CREATE TABLE IF NOT EXISTS daily_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_date DATE NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sealed')),
    author_name TEXT NOT NULL DEFAULT 'admin',
    summary TEXT,
    next_day_plan TEXT,
    source_manifest_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sealed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS daily_review_items (
    id BIGSERIAL PRIMARY KEY,
    daily_review_id UUID NOT NULL REFERENCES daily_reviews(id) ON DELETE RESTRICT,
    item_key TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('market','pool','strategy','risk','order','trade','position','performance','system')),
    title TEXT NOT NULL,
    summary TEXT,
    source_object_type TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    source_route TEXT,
    resolution_status TEXT NOT NULL DEFAULT 'resolved' CHECK (resolution_status IN ('resolved','archived','unavailable')),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(daily_review_id,item_key)
);

CREATE TABLE IF NOT EXISTS daily_review_metrics (
    id BIGSERIAL PRIMARY KEY,
    daily_review_id UUID NOT NULL REFERENCES daily_reviews(id) ON DELETE RESTRICT,
    metric_code TEXT NOT NULL,
    metric_value DOUBLE PRECISION,
    unit TEXT,
    comparison_window TEXT,
    source_object_type TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    calculation_version TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(daily_review_id,metric_code,source_object_type,source_object_id)
);

CREATE TABLE IF NOT EXISTS qa_drill_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    drill_type TEXT NOT NULL,
    environment TEXT NOT NULL DEFAULT 'local',
    status TEXT NOT NULL CHECK (status IN ('running','passed','failed','blocked')),
    expected_outcome TEXT NOT NULL,
    observed_outcome TEXT,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_hash TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS backup_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backup_type TEXT NOT NULL CHECK (backup_type IN ('daily','manual','restore_rehearsal')),
    scope TEXT NOT NULL DEFAULT 'stockpro_local_pg',
    status TEXT NOT NULL CHECK (status IN ('running','success','failed')),
    location_ref TEXT,
    manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    manifest_hash TEXT,
    backup_size_bytes BIGINT,
    restore_database TEXT,
    restore_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_daily_review_items_timeline ON daily_review_items(daily_review_id,occurred_at,id);
CREATE INDEX IF NOT EXISTS idx_qa_drills_type_started ON qa_drill_runs(drill_type,started_at DESC);
CREATE INDEX IF NOT EXISTS idx_backup_runs_status_started ON backup_runs(status,started_at DESC);

CREATE OR REPLACE FUNCTION prevent_sealed_review_mutation() RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'sealed' THEN
        RAISE EXCEPTION 'sealed daily review is immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_daily_review_immutable ON daily_reviews;
CREATE TRIGGER trg_daily_review_immutable BEFORE UPDATE OR DELETE ON daily_reviews
    FOR EACH ROW EXECUTE FUNCTION prevent_sealed_review_mutation();

CREATE OR REPLACE FUNCTION prevent_sealed_review_child_mutation() RETURNS trigger AS $$
DECLARE review_status TEXT;
BEGIN
    SELECT status INTO review_status FROM daily_reviews WHERE id=COALESCE(OLD.daily_review_id,NEW.daily_review_id);
    IF review_status = 'sealed' THEN
        RAISE EXCEPTION 'sealed daily review evidence is immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_daily_review_items_immutable ON daily_review_items;
CREATE TRIGGER trg_daily_review_items_immutable BEFORE UPDATE OR DELETE ON daily_review_items
    FOR EACH ROW EXECUTE FUNCTION prevent_sealed_review_child_mutation();
DROP TRIGGER IF EXISTS trg_daily_review_metrics_immutable ON daily_review_metrics;
CREATE TRIGGER trg_daily_review_metrics_immutable BEFORE UPDATE OR DELETE ON daily_review_metrics
    FOR EACH ROW EXECUTE FUNCTION prevent_sealed_review_child_mutation();
