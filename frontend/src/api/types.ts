/**
 * Types mirroring the FastAPI response models in `backend/app/schemas.py`.
 * They are the contract between the two halves of the system; when the
 * backend swaps its baseline model for a trained one, these do not change.
 */

export type RiskCategory = 'LOW' | 'MODERATE' | 'HIGH' | 'SEVERE';

export interface LocationRef {
  id: string;
  name: string;
  state: string;
  lat: number;
  lon: number;
  featured?: boolean;
}

export interface VariableRef {
  id: string;
  label: string;
  unit: string;
  axis_label: string;
}

export interface ModelRef {
  id: string;
  label: string;
  centre: string;
  skill: number;
  has_ensemble: boolean;
}

export interface RiskBand {
  name: RiskCategory;
  min: number;
  max: number;
  color: string;
}

export interface ScenarioRef {
  id: string;
  title: string;
  summary: string;
  expected_band: RiskCategory;
  location_id: string;
  variable_id: string;
  model_id: string;
  horizon: number;
  base_date: string;
}

export interface Selection {
  location_id: string;
  variable_id: string;
  model_id: string;
  horizon: number;
  base_date: string;
  scenario_id?: string;
}

export interface Meta {
  app_name: string;
  tagline: string;
  version: string;
  data_mode: string;
  demo_notice: string | null;
  reference_date: string;
  locations: LocationRef[];
  regions: LocationRef[];
  variables: VariableRef[];
  models: ModelRef[];
  risk_bands: RiskBand[];
  horizons: number[];
  scenarios: ScenarioRef[];
  default_selection: Selection;
  disclaimer: string;
}

export interface FeatureContribution {
  feature: string;
  label: string;
  description: string;
  value: number;
  contribution: number;
  direction: 'increases' | 'decreases';
}

export interface EnsembleDay {
  lead: number;
  label: string;
  date: string;
}

export interface EnsembleMember {
  member: number;
  values: number[];
}

export interface EnsemblePayload {
  days: EnsembleDay[];
  members: EnsembleMember[];
  member_count: number;
  plotted_member_count: number;
  mean: number[];
  deterministic: number[];
  observed: (number | null)[];
  percentiles: Record<'p10' | 'p25' | 'p50' | 'p75' | 'p90', number[]>;
  unit: string;
  axis_label: string;
  spread_anomaly: number;
  high_spread: boolean;
  spread_at_horizon: number;
  range_at_horizon: [number, number];
  climatological_spread: number;
  explanation: string;
}

export interface ModelComparisonRow {
  model_id: string;
  model: string;
  centre: string;
  forecast_value: number;
  unit: string;
  ensemble_spread: number;
  spread_label: string;
  risk_score: number;
  risk_category: RiskCategory;
  forecast_confidence: number;
  historical_skill: number;
}

export interface Analogue {
  rank: number;
  id: string;
  date: string;
  region: string;
  regime: string;
  pattern: string;
  similarity: number;
  bust_occurred: boolean;
  outcome: string;
  verified_error: string;
}

export interface TimelineRow {
  lead_time: number;
  label: string;
  init_date: string;
  risk_score: number;
  risk_category: RiskCategory;
  forecast_confidence: number;
}

export interface HorizonRow {
  horizon: number;
  label: string;
  valid_date: string;
  risk_score: number;
  risk_category: RiskCategory;
  forecast_confidence: number;
  model_confidence: number;
}

export interface VerificationSeriesPoint {
  date: string;
  forecast: number;
  observed: number;
  error: number;
  bust: boolean;
}

export interface ForecastVerification {
  series: VerificationSeriesPoint[];
  unit: string;
  metrics: {
    rmse: number;
    mae: number;
    bias: number;
    acc: number;
    skill: number;
    sample_size: number;
    bust_count: number;
    reference?: string;
  };
}

export interface RiskResponse {
  location: LocationRef;
  variable: { id: string; label: string; unit: string };
  model: { id: string; label: string; centre: string };
  forecast_horizon: number;
  base_date: string;
  valid_date: string;
  risk_score: number;
  risk_category: RiskCategory;
  confidence: number;
  forecast_confidence: number;
  model_confidence: number;
  features: Record<string, number>;
  feature_contributions: FeatureContribution[];
  base_value: number;
  explanation: string;
  explanation_label: string;
  explanation_method: string;
  synoptic: {
    regime: string;
    next_regime: string;
    regime_change: number;
    transition_day: number;
    event_day: number;
  };
  ensemble: EnsemblePayload;
  model_comparison: {
    rows: ModelComparisonRow[];
    spread_between_models: number;
    disagreement: boolean;
    message: string;
  };
  analogues: Analogue[];
  analogue_summary: {
    best_similarity: number;
    bust_count: number;
    total: number;
    note: string;
  };
  persistence_history: { init_date: string; lead_time: number; value: number }[];
  horizon_profile: HorizonRow[];
  risk_timeline: TimelineRow[];
  verification: ForecastVerification;
  observation_source: { verified_against: string; real: boolean; window: [string, string] };
  data_mode: string;
  demo_notice: string | null;
  disclaimer: string;
  generated_at: string;
  scenario?: { id: string; title: string; summary: string; expected_band: RiskCategory };
}

export interface NetworkSite {
  id: string;
  name: string;
  state: string;
  lat: number;
  lon: number;
  featured: boolean;
  risk_score: number;
  risk_category: RiskCategory;
  forecast_confidence: number;
  model_confidence: number;
  ensemble_spread: number;
  regime_change: number;
  regime: string;
  top_driver: string;
}

export interface NetworkResponse {
  sites: NetworkSite[];
  counts: Record<RiskCategory, number>;
  high_risk_areas: number;
  highest_risk: NetworkSite | null;
  mean_model_confidence: number;
  network_size: number;
  variable_id: string;
  horizon: number;
  model_id: string;
  base_date: string;
  data_mode: string;
  demo_notice: string | null;
}

export interface Alert {
  id: string;
  location_id: string;
  location_name: string;
  state: string;
  lat: number;
  lon: number;
  variable_id: string;
  variable_label: string;
  horizon: number;
  valid_date: string;
  issued_at: string;
  risk_score: number;
  bust_probability: number;
  severity: RiskCategory;
  model_confidence: number;
  forecast_confidence: number;
  reason: string;
  headline: string;
  status: string;
  recommended_action: string;
  source?: string;
  imd_warning_color?: 'green' | 'yellow' | 'orange' | 'red';
  imd_warning_text?: string;
  past_24_hrs_rainfall?: string;
  todays_forecast?: string;
  bust_drivers?: string[];
  date?: string;
}

export interface AlertsResponse {
  alerts: Alert[];
  counts: Record<RiskCategory, number>;
  threshold: number;
  probability_threshold: number;
  base_date: string;
  data_mode: string;
  demo_notice: string | null;
  disclaimer: string;
}

export interface ModelPerformance {
  operating_threshold: number;
  sample_size: number;
  base_rate: number;
  roc_auc: number;
  brier_score: number;
  precision: number;
  recall: number;
  f1: number;
  accuracy: number;
  confusion_matrix: {
    true_positive: number;
    false_positive: number;
    false_negative: number;
    true_negative: number;
  };
  roc_curve: { fpr: number; tpr: number; threshold: number }[];
  reliability: { bin: string; predicted: number; observed: number; count: number }[];
  band_reliability: {
    band: RiskCategory;
    range: string;
    observed_bust_rate: number;
    count: number;
    share: number;
  }[];
  score_interpretation: string;
  model: {
    name: string;
    version: string;
    kind: string;
    trained: boolean;
    weights: Record<string, number>;
    coefficients?: Record<string, number>;
    intercept?: number;
    predictors?: number;
    contribution_kind?: string;
    comparison?: { model: string; roc_auc_train: number; roc_auc_holdout: number; brier_holdout: number }[];
    training: {
      rows: number;
      train_rows: number;
      test_rows: number;
      base_rate: number;
      roc_auc_train: number;
      roc_auc_holdout: number;
      roc_auc_ablated?: number;
      brier_holdout?: number;
      split: string;
      cutoff_date: string;
      source: string;
    };
    explanation_method: string;
    ablation_note?: string;
    notice: string;
  };
}

export interface VerificationResponse {
  model_performance: ModelPerformance;
  label: string;
  data_mode: string;
  demo_notice: string | null;
  disclaimer: string;
}

export interface SystemStatus {
  data_mode: string;
  demo_notice: string | null;
  sources: { id: string; name: string; role: string; status: string; detail: string }[];
  pipeline: { stage: string; status: string; detail: string }[];
  model: ModelPerformance['model'];
  reference_date: string;
  ensemble_members: number;
  database: string;
  disclaimer: string;
}


export interface ClimateTrend {
  slope_per_decade: number;
  percent_per_decade: number;
  z: number;
  p_value: number;
  significant: boolean;
  direction: string;
}

export interface ClimateProfile {
  subdivision: string;
  location_id: string;
  location_name: string;
  record: { start: number; end: number; years: number };
  annual_mean: number;
  monsoon_mean: number;
  monsoon_share: number;
  variability: number;
  trend: ClimateTrend | null;
  categories: { category: string; years: number; frequency: number; range: string }[];
  decades: { decade: number; label: string; mean: number; departure_pct: number; years: number }[];
  extremes: {
    wettest: { year: number; monsoon: number; departure_pct: number; category: string }[];
    driest: { year: number; monsoon: number; departure_pct: number; category: string }[];
  };
  baseline_shift: {
    early_period: string;
    late_period: string;
    early_mean: number;
    late_mean: number;
    change_pct: number;
    early_variability: number;
    late_variability: number;
  } | null;
  series: { year: number; monsoon: number; annual: number }[];
  source: { name: string; publisher: string; method: string };
}

export interface DataSource {
  id: string;
  name: string;
  agency: string;
  country: string;
  portal: string;
  role: string;
  variables: string[];
  resolution: string;
  coverage: string;
  fmt: string;
  access: string;
  how_to_get: string;
  licence: string;
  feeds: string;
  notes: string;
  status: string;
  docs: string[];
}

export interface SourcesResponse {
  sources: DataSource[];
  in_use: string[];
  counts: Record<string, number>;
  note: string;
}


export interface StateWarning {
  state: string;
  level: string;
  color: string;
  risk_score: number;
  median_risk: number;
  risk_category: RiskCategory;
  sites: number;
  worst_site: string;
  driver: string;
  hazards: string[];
  primary_hazard?: string | null;
  forecast_temp?: number;
  forecast_wind?: number;
  observed_category: string | null;
  peak_rainfall: number;
  meaning: string;
}

export interface WarningsResponse {
  states: StateWarning[];
  counts: Record<string, number>;
  state_count: number;
  levels: { level: string; color: string; meaning: string }[];
  disclaimer: string;
  base_date: string;
  valid_date: string;
  horizon: number;
  model_id: string;
  data_mode: string;
  demo_notice: string | null;
}

/* -------------------------------------------------------------------------- */
/* Historical replay                                                           */
/* -------------------------------------------------------------------------- */

export interface ReplayModeState {
  id: string;
  name: string;
  available: boolean;
  reason: string;
  looked_for?: string[];
  candidate_archives?: { id: string; name: string; covers: string; why: string; reference: string; access: string }[];
  missing_antecedent_days?: string[];
}

export interface ReplayAvailability {
  origin: string;
  leads: number[];
  valid_days: string[];
  archive: { start: string; end: string; days: number; source: string };
  mode_a: ReplayModeState;
  mode_b: ReplayModeState;
  verification: {
    verifiable_days: string[];
    unverifiable_days: string[];
    note: string;
  };
  model_trained: boolean;
}

export interface ReplayOrigins {
  origins: string[];
  count: number;
  default: string | null;
  fully_verifiable_through: string | null;
  archive_start: string;
  archive_end: string;
  min_antecedent_days: number;
  note: string;
}

export interface ReplayContribution {
  feature: string;
  label: string;
  description: string;
  value: number;
  contribution: number;
}

export interface ReplayPrediction {
  prediction_id: string;
  origin: string;
  valid_day: string;
  lead_time: number;
  location_id: string;
  probability: number;
  predicted_event: boolean;
  threshold: number;
  evidence_window: string[];
  base_value: number;
  contributions: ReplayContribution[];
}

export type ReplayOutcome = 'hit' | 'false alarm' | 'miss' | 'correct negative' | 'not verifiable';

export interface ReplayValidation {
  prediction_id: string;
  valid_day: string;
  observed_available: boolean;
  observed_rainfall: number | null;
  observed_normal: number | null;
  observed_departure_pct: number | null;
  observed_category: string | null;
  actual_event: boolean | null;
  predicted_event: boolean;
  probability: number;
  outcome: ReplayOutcome;
  note: string | null;
}

export interface ReplaySummary {
  verified_days: number;
  unverified_days: number;
  hit: number;
  'false alarm': number;
  miss: number;
  'correct negative': number;
  correct: number;
  hit_rate: number | null;
  false_alarm_ratio: number | null;
  note: string;
}

export interface ReplayEvent {
  label: string;
  definition: string;
  source: string;
}

export interface ReplayAuditEntry {
  step: string;
  phase: string;
  detail: string;
  reads: string;
  at: string;
}

export interface ReplayRun {
  run_id: string;
  mode: string;
  mode_name?: string;
  mode_note?: string;
  event?: ReplayEvent;
  origin: string;
  location_id: string;
  location_name: string;
  subdivision?: string;
  threshold?: number;
  availability: ReplayAvailability;
  predictions: ReplayPrediction[];
  validations: ReplayValidation[];
  summary: ReplaySummary | null;
  audit_log: ReplayAuditEntry[];
  model_version: string;
}

export interface ReplayConfusion {
  threshold: number;
  true_positive: number;
  false_positive: number;
  false_negative: number;
  true_negative: number;
  precision: number;
  recall: number;
  f1: number;
  accuracy: number | null;
  base_rate: number | null;
}

export interface ReplayReliabilityBin {
  bin_lower: number;
  bin_upper: number;
  count: number;
  mean_predicted: number | null;
  observed_rate: number | null;
}

export interface ReplayGroupMetric {
  count: number;
  events: number;
  roc_auc: number | null;
  brier: number;
  precision: number;
  recall: number;
  f1: number;
  base_rate: number | null;
  lead_time?: number;
  subdivision?: string;
  origin?: string;
}

export interface ReplayBacktest {
  mode: string;
  mode_name: string;
  mode_note: string;
  event: ReplayEvent;
  threshold: number;
  model_version: string;
  window: {
    origins: string[];
    origin_count: number;
    archive_start: string;
    archive_end: string;
    sites: number;
    leads: number[];
  };
  counts: {
    prediction_outcome_pairs: number;
    events: number;
    skipped_no_observation: number;
  };
  overall: {
    roc_auc: number | null;
    brier: number;
    confusion: ReplayConfusion;
    reliability: ReplayReliabilityBin[];
  };
  out_of_sample: {
    origins: string[];
    count: number;
    roc_auc: number | null;
    confusion: ReplayConfusion;
  } | null;
  by_lead: ReplayGroupMetric[];
  by_subdivision: ReplayGroupMetric[];
  by_origin: ReplayGroupMetric[];
  model_holdout: Record<string, unknown>;
  caveat: string;
  honesty_note: string;
}

export interface ReplayModelCard {
  name: string;
  kind: string;
  model_version: string;
  mode: string;
  mode_name: string;
  mode_note: string;
  event: ReplayEvent;
  threshold: number;
  threshold_note: string;
  predictors: { name: string; label: string; description: string; coefficient: number }[];
  explanation_method: string;
  training: Record<string, unknown>;
  metrics: Record<string, unknown>;
  caveat: string;
  leakage_controls: string[];
}

/* -------------------------------------------------------------------------- */
/* Monthly replay (1901-2017 sub-division record)                              */
/* -------------------------------------------------------------------------- */

export interface MonthlyMeta {
  subdivisions: string[];
  record_start: number;
  record_end: number;
  test_from_year: number;
  extreme_z: number;
  resolution: string;
  resolution_note: string;
  model_trained: boolean;
  event: { label: string; definition: string; source: string; climatology: string } | null;
  threshold_note: string | null;
  training: Record<string, unknown> | null;
  caveat: string | null;
}

export interface MonthlyContribution {
  feature: string;
  label: string;
  description: string;
  value: number;
  contribution: number;
}

export interface MonthlyTargetPrediction {
  probability: number;
  threshold: number;
  flag: boolean;
  base_value: number;
  contributions: MonthlyContribution[];
}

export interface MonthlyPrediction {
  subdivision: string;
  origin: string;
  origin_label: string;
  target: string;
  target_label: string;
  features: Record<string, number>;
  evidence_through: string;
  extreme: MonthlyTargetPrediction;
  wet: MonthlyTargetPrediction;
  dry: MonthlyTargetPrediction;
}

export interface MonthlyValidation {
  target: string;
  target_label?: string;
  observed_available: boolean;
  rainfall_mm?: number;
  climatology_mm?: number;
  climatology_years?: number;
  departure_pct?: number;
  z?: number;
  category?: string;
  actual_extreme?: boolean;
  actual_direction?: 'wet' | 'dry' | 'neither';
  predicted_extreme?: boolean;
  predicted_direction?: 'wet' | 'dry' | 'neither';
  direction_correct?: boolean | null;
  verdict?: 'hit' | 'miss' | 'false alarm' | 'correct negative';
  source?: string;
  note?: string;
}

export interface MonthlyRow {
  prediction: MonthlyPrediction;
  validation: MonthlyValidation;
}

export interface MonthlyReplay {
  requested_date: string;
  target: string;
  target_label: string;
  origin: string;
  origin_label: string;
  held_out: boolean;
  resolution_note: string | null;
  event: { label: string; definition: string; source: string; climatology: string } | null;
  rows: MonthlyRow[];
  summary: {
    subdivisions: number;
    verified: number;
    hit?: number;
    miss?: number;
    'false alarm'?: number;
    'correct negative'?: number;
    correct: number;
    accuracy: number | null;
    hit_rate: number | null;
    false_alarm_ratio: number | null;
    actual_extremes: number;
  };
}

/* -------------------------------------------------------------------------- */
/* 7-day station replay, 2010-2017 (NOAA GHCN-Daily)                           */
/* -------------------------------------------------------------------------- */

export interface GhcnStation {
  station_id: string;
  name: string;
  lat: number;
  lon: number;
  elevation_m: number;
}

export interface StationLeadMetric {
  lead: number;
  tmax_mae_c: number;
  tmax_mae_climatology_c: number;
  tmax_mae_persistence_c: number;
  tmax_mae_same_rows_as_persistence_c: number;
  tmax_within_2c: number;
  rain_day_accuracy: number;
  rain_rows: number;
  bust_rate: number;
  bust_auc: number | null;
}

export interface StationsMeta {
  stations: GhcnStation[];
  default_station: string;
  default_date: string;
  first_date: string;
  last_date: string;
  train_period: string[];
  test_period: string[];
  forecast_note: string;
  bust_definition: { temperature: string; rain: string; any: string };
  thresholds: { bust_any: number; bust_temp: number; bust_rain: number };
  overall: {
    tmax_mae_c: number;
    tmax_mae_climatology_c: number;
    tmax_within_2c: number;
    tmin_mae_c: number;
    rain_day_accuracy: number;
    rain_day_accuracy_climatology: number;
    rows: number;
  };
  by_lead: StationLeadMetric[];
  by_year: {
    year: number;
    forecasts: number;
    tmax_mae_c: number;
    tmax_within_2c: number;
    bust_auc: number | null;
    bust_call_accuracy: number;
    bust_rate: number;
  }[];
  bust_any: {
    rows: number;
    roc_auc: number | null;
    brier: number;
    brier_climatology: number;
    confusion_operating: ReplayConfusion;
    reliability: ReplayReliabilityBin[];
    call_accuracy_operating: number;
    call_accuracy_at_50: number;
    call_accuracy_always_no: number;
  };
  source: string;
  source_url: string;
  /** Present only in a static build: the dates it carries. */
  preview_dates?: string[];
}

export interface StationForecastDay {
  lead: number;
  date: string;
  tmax_c: number;
  tmin_c: number;
  rain_probability: number;
  rain_mm: number;
  rain_class: string;
  normal_tmax_c: number;
  normal_tmin_c: number;
  normal_rain_probability: number | null;
  bust_probability: number;
  bust_probability_temperature: number;
  bust_probability_rain: number;
}

export interface StationValidationRow {
  lead: number;
  date: string;
  observed_tmax_c: number | null;
  observed_tmin_c: number | null;
  observed_rain_mm: number | null;
  observed_rain_class: string | null;
  tmax_error_c: number | null;
  tmin_error_c: number | null;
  tmax_within_2c: boolean | null;
  rain_correct: boolean | null;
  temperature_bust: boolean | null;
  rain_bust: boolean | null;
  actual_bust: boolean | null;
  predicted_bust: boolean;
  verdict: ReplayOutcome;
  rain_reported: boolean;
}

export interface StationReplay {
  station: GhcnStation;
  origin: string;
  evidence_through: string;
  history: { date: string; tmax_c: number | null; tmin_c: number | null; rain_mm: number | null }[];
  forecast: StationForecastDay[];
  thresholds: { bust_any: number; bust_temp: number; bust_rain: number };
  held_out: boolean;
  forecast_note: string;
  validation: {
    rows: StationValidationRow[];
    summary: {
      days_verified: number;
      hit?: number;
      miss?: number;
      'false alarm'?: number;
      'correct negative'?: number;
      tmax_within_2c: number;
      tmax_checked: number;
      tmax_mae_c: number | null;
      rain_correct: number;
      rain_checked: number;
      bust_correct: number;
    };
    source: string;
    station_page: string;
  };
}

/* -------------------------------------------------------------------------- */
/* Live IMD feed                                                               */
/* -------------------------------------------------------------------------- */

export type ImdLiveState =
  | 'not_configured'
  | 'needs_probe'
  | 'unreachable'
  | 'rejected'
  | 'error'
  | 'unrecognised'
  | 'connected'
  | 'static';

export interface ImdLiveCity {
  station_id: string | null;
  city: string | null;
  state: string | null;
  date: string | null;
  max_temp: number | null;
  min_temp: number | null;
  rainfall: number | null;
  warning: string | null;
}

export interface ImdLiveStatus {
  state: ImdLiveState;
  message: string;
  checked_at: string;
  endpoint: string;
  cities: ImdLiveCity[];
  matched: Record<
    string,
    {
      location_id: string;
      location_name: string;
      imd_city: string;
      max_temp: number | null;
      min_temp: number | null;
      rainfall: number | null;
      warning: string | null;
      date: string | null;
    }
  >;
  http_status?: number | null;
  fields_seen?: string[];
  records?: number;
  cache_ttl_seconds?: number;
}

export interface ImdStationDayForecast {
  day: number;
  max_temp?: number | null;
  min_temp?: number | null;
  forecast?: string;
  warning?: string;
  warning_color?: string;
}

export interface ImdStationForecast {
  station_code: string;
  station_name: string;
  state: string;
  subdivision?: string;
  lat: number;
  lon: number;
  date: string;
  past_24_hrs_rainfall: string;
  today_max_temp?: string | null;
  today_min_temp?: string | null;
  todays_forecast: string;
  day_1_warning: string;
  day_1_warning_color: string;
  forecast_7days: ImdStationDayForecast[];
  bust_risk_score?: number;
  bust_category?: 'LOW' | 'MODERATE' | 'HIGH' | 'SEVERE';
  bust_drivers?: string[];
  recommendation?: string;
  sunset_time?: string;
  sunrise_time?: string;
  humidity_0830?: string;
}

export interface LiveWeatherResponse {
  lat: number;
  lon: number;
  temperature: number | null;
  relative_humidity: number | null;
  precipitation_mm: number | null;
  wind_speed_kmh: number | null;
  weather_code: number;
  weather_description: string;
  time: string | null;
  source: string;
  status: string;
}

export interface ImdCityForecastResponse {
  source: string;
  count: number;
  stations: ImdStationForecast[];
  date?: string;
  bulletin_date?: string;
  forecast_valid_from?: string;
  forecast_valid_to?: string;
  forecast_horizon_days?: number;
  last_updated?: string;
  updated_at: string;
}

export interface ImdBustResponse {
  location_id: string;
  location_name: string;
  matched_station: string;
  matched_state: string;
  distance_km: number;
  date: string;
  bulletin_date?: string;
  forecast_valid_from?: string;
  forecast_valid_to?: string;
  last_updated?: string;
  past_24_hrs_rainfall: string;
  today_max_temp?: string | null;
  today_min_temp?: string | null;
  todays_forecast: string;
  day_1_warning: string;
  day_1_warning_color: 'green' | 'yellow' | 'orange' | 'red';
  forecast_7days: ImdStationDayForecast[];
  bust_risk_score: number;
  bust_category: 'LOW' | 'MODERATE' | 'HIGH' | 'SEVERE';
  bust_drivers: string[];
  recommendation: string;
  humidity_0830?: string | null;
  sunrise_time?: string | null;
  sunset_time?: string | null;
  source: string;
  updated_at: string;
}

export interface ImdRealtimeAlert {
  id: string;
  location_id: string;
  location_name: string;
  state: string;
  lat: number;
  lon: number;
  variable_id: string;
  variable_label: string;
  horizon: number;
  valid_date: string;
  issued_at: string;
  risk_score: number;
  bust_probability: number;
  severity: 'LOW' | 'MODERATE' | 'HIGH' | 'SEVERE';
  model_confidence: number;
  forecast_confidence: number;
  reason: string;
  headline: string;
  status: string;
  recommended_action: string;
  source: string;
  imd_warning_color: 'green' | 'yellow' | 'orange' | 'red';
  imd_warning_text: string;
  past_24_hrs_rainfall: string;
  todays_forecast: string;
  bust_drivers: string[];
  date: string;
}

export interface ImdRealtimeAlertsResponse {
  alerts: ImdRealtimeAlert[];
  counts: Record<string, number>;
  severe_count: number;
  high_count: number;
  total: number;
  threshold: number;
  probability_threshold: number;
  base_date: string;
  issued_at: string;
  bulletin_date?: string;
  forecast_valid_from?: string;
  forecast_valid_to?: string;
  last_updated?: string;
  source: string;
  updated_at: string;
  data_mode: string;
  disclaimer: string;
}
