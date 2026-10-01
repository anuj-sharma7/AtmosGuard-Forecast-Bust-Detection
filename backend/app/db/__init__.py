"""Data-access layer.

SQLite locally, PostgreSQL/TimescaleDB in production. The schema in
`schema.sql` is written to run on both: no SQLite-only types, and the
TimescaleDB hypertable calls are isolated in `schema_timescale.sql`.
"""
