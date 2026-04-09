CREATE TABLE IF NOT EXISTS parse_results (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL REFERENCES parse_jobs(id) ON DELETE CASCADE,
    article VARCHAR(128) NULL,
    name VARCHAR(500) NOT NULL DEFAULT '',
    unit VARCHAR(128) NULL,
    price VARCHAR(64) NULL,
    brand VARCHAR(255) NULL,
    weight VARCHAR(64) NULL,
    level1 VARCHAR(255) NULL,
    level2 VARCHAR(255) NULL,
    level3 VARCHAR(255) NULL,
    level4 VARCHAR(255) NULL,
    image TEXT NULL,
    url TEXT NULL,
    supplier VARCHAR(128) NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_parse_results_job_id ON parse_results(job_id);
CREATE INDEX IF NOT EXISTS ix_parse_results_article ON parse_results(article);
