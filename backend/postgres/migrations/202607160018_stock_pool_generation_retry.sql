-- Sprint 05: failed generations remain evidence, while identical inputs may be retried.

ALTER TABLE stock_pool_generations
    DROP CONSTRAINT IF EXISTS stock_pool_generations_input_hash_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_pool_generation_active_input
    ON stock_pool_generations(input_hash)
    WHERE status IN ('running', 'success');
