-- Convert ports_json from TEXT to JSONB for databases created before this change.
-- Safe to run on databases where the column is already JSONB (no-op via DO block).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'services'
          AND column_name = 'ports_json'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE services ALTER COLUMN ports_json TYPE JSONB USING ports_json::jsonb;
    END IF;
END $$;
