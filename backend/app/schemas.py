"""Pydantic response models.

These are the *contract*. The MVP fills them from the interpretable baseline
model and simulated fields; a production deployment fills the same shapes from
a trained XGBoost model and real NWP archives. Nothing on the frontend has to
change when that swap happens - which is the point of defining them here.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RiskCategory = Literal["LOW", "MODERATE", "HIGH", "SEVERE"]


class LocationOut(BaseModel):
    id: str
    name: str
    state: str
    lat: float
    lon: float
    featured: bool = False


class VariableOut(BaseModel):
    id: str
    label: str
    unit: str
    axis_label: str


class ModelOut(BaseModel):
    id: str
    label: str
    centre: str
    skill: float
    has_ensemble: bool


class RiskBandOut(BaseModel):
    name: RiskCategory
    min: int
    max: int
    color: str


class FeatureContribution(BaseModel):
    feature: str
    label: str
    description: str
    value: float
    contribution: float
    direction: Literal["increases", "decreases"]


class MetaResponse(BaseModel):
    app_name: str
    tagline: str
    version: str
    data_mode: str
    demo_notice: str | None
    reference_date: str
    locations: list[LocationOut]
    regions: list[LocationOut]
    variables: list[VariableOut]
    models: list[ModelOut]
    risk_bands: list[RiskBandOut]
    horizons: list[int]
    scenarios: list[dict[str, Any]]
    default_selection: dict[str, Any]
    disclaimer: str


class RiskResponse(BaseModel):
    """Mirrors the conceptual API response in the AtmosGuard specification."""

    location: dict[str, Any]
    variable: dict[str, Any]
    model: dict[str, Any]
    forecast_horizon: int
    base_date: str
    valid_date: str
    risk_score: float = Field(description="Bust risk, 0-100")
    risk_category: RiskCategory
    confidence: float = Field(description="Forecast confidence, 0-1")
    forecast_confidence: float
    model_confidence: float
    features: dict[str, float]
    feature_contributions: list[FeatureContribution]
    base_value: float
    explanation: str
    explanation_label: str
    explanation_method: str
    synoptic: dict[str, Any]
    ensemble: dict[str, Any]
    model_comparison: dict[str, Any]
    analogues: list[dict[str, Any]]
    analogue_summary: dict[str, Any]
    persistence_history: list[dict[str, Any]]
    horizon_profile: list[dict[str, Any]]
    risk_timeline: list[dict[str, Any]]
    verification: dict[str, Any]
    observation_source: dict[str, Any]
    data_mode: str
    demo_notice: str | None
    disclaimer: str
    generated_at: str
    scenario: dict[str, Any] | None = None


class NetworkResponse(BaseModel):
    sites: list[dict[str, Any]]
    counts: dict[str, int]
    high_risk_areas: int
    highest_risk: dict[str, Any] | None
    mean_model_confidence: float
    network_size: int
    variable_id: str
    horizon: int
    model_id: str
    base_date: str
    data_mode: str
    demo_notice: str | None


class AlertsResponse(BaseModel):
    alerts: list[dict[str, Any]]
    counts: dict[str, int]
    threshold: float
    probability_threshold: float
    base_date: str
    data_mode: str
    demo_notice: str | None
    disclaimer: str


class VerificationResponse(BaseModel):
    model_performance: dict[str, Any]
    label: str
    data_mode: str
    demo_notice: str | None
    disclaimer: str
