CREATE TABLE IF NOT EXISTS dataset_partition_records (
    partition_id BIGINT NOT NULL REFERENCES dataset_partitions(id) ON DELETE CASCADE,
    record_ordinal INTEGER NOT NULL,
    record_hash TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(partition_id, record_ordinal)
);

CREATE INDEX IF NOT EXISTS idx_dataset_partition_records_hash
    ON dataset_partition_records(partition_id, record_hash);
