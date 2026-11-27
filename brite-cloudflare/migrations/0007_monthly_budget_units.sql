ALTER TABLE model_monthly_usage ADD COLUMN reserved_input_bytes INTEGER NOT NULL DEFAULT 0 CHECK(reserved_input_bytes>=0);
