"""Central configuration for the AtmosGuard MVP backend.

Everything that a future production deployment would need to point at real
infrastructure (NWP archives, TimescaleDB, a trained model registry) is
funnelled through here so that no business logic hard-codes an environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_DIR / ".env")
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime settings.

    ``data_mode`` is the single most important flag in the MVP: it decides
    whether the forecast provider returns synthetic demonstration fields or
    reads a real NWP archive.  The MVP only implements ``"demo"``; the
    ``"live"`` branch raises a clear NotImplementedError so that nothing can
    silently present simulated numbers as operational data.
    """

    app_name: str = "AtmosGuard"
    tagline: str = "Reads the forecast before it fails."
    version: str = "0.1.0"

    # "demo" -> synthetic MVP demonstration data. "live" -> real NWP feeds.
    data_mode: str = field(default_factory=lambda: os.getenv("ATMOSGUARD_DATA_MODE", "demo"))

    # Reference time the synthetic provider treats as "now" so that the demo
    # is byte-for-byte reproducible.  Override to move the demo clock.
    demo_reference_date: str = field(
        default_factory=lambda: os.getenv("ATMOSGUARD_REFERENCE_DATE", "2026-08-26")
    )

    # Number of ensemble members generated per forecast (spec: 20-50).
    ensemble_members: int = field(
        default_factory=lambda: int(os.getenv("ATMOSGUARD_ENSEMBLE_MEMBERS", "42"))
    )

    forecast_days: int = 7

    # Data access layer. SQLite locally; swap for a PostgreSQL/TimescaleDB DSN.
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "ATMOSGUARD_DATABASE_URL", f"sqlite:///{REPO_DIR / 'atmosguard.db'}"
        )
    )

    # Path to a trained, calibrated model. When absent the interpretable
    # baseline model is used and every response is labelled accordingly.
    model_path: str | None = field(default_factory=lambda: os.getenv("ATMOSGUARD_MODEL_PATH"))

    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    serve_frontend: bool = field(default_factory=lambda: _env_bool("ATMOSGUARD_SERVE_FRONTEND", True))

    # Real-time weather provider: OpenWeatherMap (configured via OPENWEATHERMAP_API_KEY in .env)
    openweathermap_api_key: str = field(
        default_factory=lambda: os.getenv("OPENWEATHERMAP_API_KEY", "")
    )

    @property
    def frontend_dist(self) -> Path:
        return REPO_DIR / "frontend" / "dist"

    @property
    def is_demo(self) -> bool:
        return self.data_mode == "demo"


settings = Settings()
