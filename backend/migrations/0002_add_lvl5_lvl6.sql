-- Add level5 and level6 columns to parse_results table
ALTER TABLE parse_results ADD COLUMN IF NOT EXISTS level5 VARCHAR(255);
ALTER TABLE parse_results ADD COLUMN IF NOT EXISTS level6 VARCHAR(255);
