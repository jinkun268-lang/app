-- Additive schema v6 -> v7; retain existing records, files and corrections.

ALTER TABLE offline_recognitions ADD COLUMN inference_status VARCHAR(20) NULL;

ALTER TABLE offline_recognitions ADD COLUMN inference_error_code VARCHAR(64) NULL;

ALTER TABLE offline_recognitions ADD COLUMN inference_error TEXT NULL;

ALTER TABLE offline_recognitions ADD COLUMN updated_at DATETIME(6) NULL;

UPDATE meta_schema SET value = '7' WHERE name = 'schema_version' AND value = '6';
