-- Additive schema v5 -> v6; existing tables and original images are preserved.
-- Application startup also creates this table and updates the schema version.

CREATE TABLE offline_recognitions (
	record_id VARCHAR(36) NOT NULL,
	owner_id VARCHAR(36) NOT NULL,
	declaration JSON NOT NULL,
	declaration_hash VARCHAR(64) NOT NULL,
	state VARCHAR(16) NOT NULL,
	file_key VARCHAR(512) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	current_name VARCHAR(100) NOT NULL,
	current_class_id VARCHAR(128),
	correction_version INTEGER NOT NULL,
	correction_events JSON NOT NULL,
	PRIMARY KEY (record_id),
	FOREIGN KEY(owner_id) REFERENCES users (user_id)
);

UPDATE meta_schema SET value = '6' WHERE name = 'schema_version' AND value = '5';
