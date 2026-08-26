CREATE TABLE IF NOT EXISTS extension_data_imports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'file' CHECK (source_type IN ('file','http')),
    file_format TEXT NOT NULL CHECK (file_format IN ('csv','json','xlsx')),
    original_filename TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'staged' CHECK (status IN ('staged','rejected')),
    row_count INTEGER NOT NULL,
    column_names JSONB NOT NULL,
    content_hash TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    created_by TEXT NOT NULL DEFAULT 'admin',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS extension_data_records (
    id BIGSERIAL PRIMARY KEY,
    import_id UUID NOT NULL REFERENCES extension_data_imports(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    payload JSONB NOT NULL,
    row_hash TEXT NOT NULL,
    UNIQUE(import_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_extension_imports_created ON extension_data_imports(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_extension_records_import ON extension_data_records(import_id, ordinal);
