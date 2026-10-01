-- PostgreSQL / TimescaleDB extensions to the portable schema.
-- Apply AFTER schema.sql, and only on PostgreSQL.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- The three tables that grow with time are converted to hypertables so that
-- retention and compression policies can be applied per chunk.
SELECT create_hypertable('forecasts', 'base_date', if_not_exists => TRUE);
SELECT create_hypertable('risk_predictions', 'base_date', if_not_exists => TRUE);
SELECT create_hypertable('verification_metrics', 'valid_date', if_not_exists => TRUE);

-- Keep two years of raw forecasts; verification history is kept indefinitely
-- because it is the training set for the risk model.
SELECT add_retention_policy('forecasts', INTERVAL '2 years', if_not_exists => TRUE);

-- Replay predictions are time-series over their origin date; validations over
-- the day they verify.
SELECT create_hypertable('replay_predictions', 'origin_date', if_not_exists => TRUE);
SELECT create_hypertable('replay_validations', 'valid_date', if_not_exists => TRUE);
