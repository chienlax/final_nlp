-- =============================================================================
-- init_scripts/00_create_label_studio_db.sql
-- Creates a separate database for Label Studio's Django backend
-- 
-- This script runs FIRST (alphabetically 00_) to ensure the label_studio
-- database exists before Label Studio container starts.
--
-- Note: PostgreSQL init scripts run against the default database (data_factory)
-- so we need to create the label_studio database from here.
-- =============================================================================

-- Create the label_studio database if it doesn't exist
-- Note: CREATE DATABASE cannot run inside a transaction, so we use a workaround
SELECT 'CREATE DATABASE label_studio OWNER admin'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'label_studio')\gexec

-- Grant all privileges to admin user
GRANT ALL PRIVILEGES ON DATABASE label_studio TO admin;

-- Log success
DO $$
BEGIN
    RAISE NOTICE '✓ Label Studio database created/verified successfully';
END $$;
