-- AtmosGuard relational schema.
--
-- Written to run unchanged on PostgreSQL (the production target) and SQLite
-- (local development). Portability rules followed here:
--   * TEXT / REAL / INTEGER / TIMESTAMP only - no SERIAL, no JSONB, no arrays.
--   * No ON CONFLICT ... WHERE, no partial-index predicates.
--   * Surrogate keys are supplied by the application, not the database, so the
--     same INSERT works on both engines.
--
-- TimescaleDB hypertable conversion lives in schema_timescale.sql and is
-- applied only on PostgreSQL.

CREATE TABLE IF NOT EXISTS locations (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    state               TEXT NOT NULL,
    lat                 REAL NOT NULL,
    lon                 REAL NOT NULL,
    is_featured         INTEGER NOT NULL DEFAULT 0,
    rain_climatology    REAL NOT NULL,
    temp_climatology    REAL NOT NULL,
    historical_skill    REAL NOT NULL,
    convective_index    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS model_versions (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    version             TEXT NOT NULL,
    kind                TEXT NOT NULL,
    trained             INTEGER NOT NULL DEFAULT 0,
    explanation_method  TEXT NOT NULL,
    notes               TEXT,
    created_at          TIMESTAMP NOT NULL
);

-- One row per (site, variable, NWP model, initialisation, lead time).
CREATE TABLE IF NOT EXISTS forecasts (
    id                  TEXT PRIMARY KEY,
    location_id         TEXT NOT NULL REFERENCES locations(id),
    variable_id         TEXT NOT NULL,
    nwp_model_id        TEXT NOT NULL,
    base_date           TIMESTAMP NOT NULL,
    valid_date          TIMESTAMP NOT NULL,
    lead_time           INTEGER NOT NULL,
    deterministic_value REAL NOT NULL,
    ensemble_mean       REAL NOT NULL,
    ensemble_sd         REAL NOT NULL,
    unit                TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_forecasts_lookup
    ON forecasts (location_id, variable_id, nwp_model_id, base_date, lead_time);
CREATE INDEX IF NOT EXISTS idx_forecasts_valid ON forecasts (valid_date);

-- Individual ensemble member trajectories.
CREATE TABLE IF NOT EXISTS ensemble_members (
    id                  TEXT PRIMARY KEY,
    forecast_id         TEXT NOT NULL REFERENCES forecasts(id),
    member_number       INTEGER NOT NULL,
    value               REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_members_forecast ON ensemble_members (forecast_id);

-- Model inputs, stored one row per predictor so new predictors do not require
-- a migration (the alternative, a wide table, breaks every time the feature
-- set changes).
CREATE TABLE IF NOT EXISTS features (
    id                  TEXT PRIMARY KEY,
    location_id         TEXT NOT NULL REFERENCES locations(id),
    variable_id         TEXT NOT NULL,
    nwp_model_id        TEXT NOT NULL,
    base_date           TIMESTAMP NOT NULL,
    lead_time           INTEGER NOT NULL,
    feature_name        TEXT NOT NULL,
    feature_value       REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_features_lookup
    ON features (location_id, variable_id, base_date, lead_time);

CREATE TABLE IF NOT EXISTS risk_predictions (
    id                  TEXT PRIMARY KEY,
    location_id         TEXT NOT NULL REFERENCES locations(id),
    variable_id         TEXT NOT NULL,
    nwp_model_id        TEXT NOT NULL,
    model_version_id    TEXT NOT NULL REFERENCES model_versions(id),
    base_date           TIMESTAMP NOT NULL,
    valid_date          TIMESTAMP NOT NULL,
    lead_time           INTEGER NOT NULL,
    risk_score          REAL NOT NULL,
    risk_category       TEXT NOT NULL,
    forecast_confidence REAL NOT NULL,
    model_confidence    REAL NOT NULL,
    explanation         TEXT,
    created_at          TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_risk_lookup
    ON risk_predictions (location_id, variable_id, base_date, lead_time);
CREATE INDEX IF NOT EXISTS idx_risk_valid ON risk_predictions (valid_date);

-- Per-prediction feature attributions (SHAP values, or their exact linear
-- equivalent for the baseline model).
CREATE TABLE IF NOT EXISTS risk_contributions (
    id                  TEXT PRIMARY KEY,
    risk_prediction_id  TEXT NOT NULL REFERENCES risk_predictions(id),
    feature_name        TEXT NOT NULL,
    feature_value       REAL NOT NULL,
    contribution        REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_contrib_prediction
    ON risk_contributions (risk_prediction_id);

CREATE TABLE IF NOT EXISTS historical_analogues (
    id                  TEXT PRIMARY KEY,
    event_date          TEXT NOT NULL,
    region              TEXT NOT NULL,
    regime              TEXT NOT NULL,
    pattern             TEXT NOT NULL,
    fingerprint_regime_change    REAL NOT NULL,
    fingerprint_forcing          REAL NOT NULL,
    fingerprint_moisture         REAL NOT NULL,
    fingerprint_convective       REAL NOT NULL,
    bust_occurred       INTEGER NOT NULL,
    outcome             TEXT NOT NULL,
    verified_error      TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id                  TEXT PRIMARY KEY,
    location_id         TEXT NOT NULL REFERENCES locations(id),
    variable_id         TEXT NOT NULL,
    risk_prediction_id  TEXT REFERENCES risk_predictions(id),
    issued_at           TIMESTAMP NOT NULL,
    valid_date          TIMESTAMP NOT NULL,
    lead_time           INTEGER NOT NULL,
    severity            TEXT NOT NULL,
    risk_score          REAL NOT NULL,
    headline            TEXT NOT NULL,
    reason              TEXT NOT NULL,
    recommended_action  TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'Monitoring',
    acknowledged_at     TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts (status, severity);
CREATE INDEX IF NOT EXISTS idx_alerts_issued ON alerts (issued_at);

-- Forecast-vs-observation verification, and the derived bust label that the
-- risk model is trained and scored against.
CREATE TABLE IF NOT EXISTS verification_metrics (
    id                  TEXT PRIMARY KEY,
    location_id         TEXT NOT NULL REFERENCES locations(id),
    variable_id         TEXT NOT NULL,
    base_date           TIMESTAMP NOT NULL,
    valid_date          TIMESTAMP NOT NULL,
    lead_time           INTEGER NOT NULL,
    forecast_value      REAL NOT NULL,
    observed_value      REAL NOT NULL,
    error               REAL NOT NULL,
    normalised_error    REAL NOT NULL,
    bust                INTEGER NOT NULL,
    source              TEXT NOT NULL DEFAULT 'demo'
);

CREATE INDEX IF NOT EXISTS idx_verification_lookup
    ON verification_metrics (location_id, variable_id, valid_date);

-- ---------------------------------------------------------------------------
-- Historical replay: predictions formed at an origin date, and what followed.
--
-- Kept in their own tables rather than reusing `risk_predictions`, because the
-- two are not the same object. A risk_prediction is scored from the
-- reconstructed ensemble, which is anchored to the observation it is later
-- verified against - fine for a live demonstration, invalid as a backtest. A
-- replay_prediction is formed from data dated on or before its origin and
-- nothing else. Mixing them in one table would lose exactly the distinction
-- the replay exists to preserve.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS replay_runs (
    id                  TEXT PRIMARY KEY,
    -- 'A' = forecast-bust validation against an archived NWP forecast.
    -- 'B' = historical weather risk proxy from observations only.
    mode                TEXT NOT NULL CHECK (mode IN ('A', 'B')),
    origin_date         TIMESTAMP NOT NULL,
    lead_days           INTEGER NOT NULL,
    scope               TEXT NOT NULL,
    model_version       TEXT NOT NULL,
    threshold           REAL NOT NULL,
    event_definition    TEXT NOT NULL,
    archive_start       TIMESTAMP NOT NULL,
    archive_end         TIMESTAMP NOT NULL,
    created_at          TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_replay_runs_origin ON replay_runs (origin_date, mode);

CREATE TABLE IF NOT EXISTS replay_predictions (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES replay_runs(id),
    location_id         TEXT NOT NULL REFERENCES locations(id),
    origin_date         TIMESTAMP NOT NULL,
    valid_date          TIMESTAMP NOT NULL,
    lead_time           INTEGER NOT NULL,
    -- Calibrated model output. Never a constant, never a random draw.
    bust_probability    REAL NOT NULL,
    predicted_bust      INTEGER NOT NULL,
    threshold           REAL NOT NULL,
    -- The earliest and latest day this prediction was permitted to read.
    -- Both must be <= origin_date; that is the audit trail for no-leakage.
    evidence_start      TIMESTAMP NOT NULL,
    evidence_end        TIMESTAMP NOT NULL,
    base_value          REAL NOT NULL,
    created_at          TIMESTAMP NOT NULL,
    CHECK (evidence_end <= origin_date),
    CHECK (valid_date > origin_date)
);

CREATE INDEX IF NOT EXISTS idx_replay_pred_lookup
    ON replay_predictions (run_id, location_id, lead_time);
CREATE INDEX IF NOT EXISTS idx_replay_pred_valid ON replay_predictions (valid_date);

CREATE TABLE IF NOT EXISTS replay_contributions (
    id                  TEXT PRIMARY KEY,
    replay_prediction_id TEXT NOT NULL REFERENCES replay_predictions(id),
    feature_name        TEXT NOT NULL,
    feature_value       REAL NOT NULL,
    contribution        REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_replay_contrib
    ON replay_contributions (replay_prediction_id);

CREATE TABLE IF NOT EXISTS replay_validations (
    id                  TEXT PRIMARY KEY,
    replay_prediction_id TEXT NOT NULL REFERENCES replay_predictions(id),
    valid_date          TIMESTAMP NOT NULL,
    -- 0 when the published record does not cover valid_date. The observed
    -- columns then stay NULL: a gap is stored as a gap, never as zero.
    observed_available  INTEGER NOT NULL,
    observed_rainfall   REAL,
    observed_normal     REAL,
    observed_departure  REAL,
    observed_category   TEXT,
    actual_bust         INTEGER,
    outcome             TEXT NOT NULL,
    observation_source  TEXT NOT NULL DEFAULT 'IMD district daily rainfall',
    created_at          TIMESTAMP NOT NULL,
    CHECK (observed_available IN (0, 1)),
    CHECK (observed_available = 1 OR actual_bust IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_replay_val_prediction
    ON replay_validations (replay_prediction_id);

-- Append-only record of what each phase of a replay read and when, so a run
-- can be audited after the fact rather than taken on trust.
CREATE TABLE IF NOT EXISTS audit_log (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT,
    step                TEXT NOT NULL,
    phase               TEXT NOT NULL,
    detail              TEXT NOT NULL,
    reads               TEXT NOT NULL,
    created_at          TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_log (run_id, created_at);
