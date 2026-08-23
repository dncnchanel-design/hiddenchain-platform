from __future__ import annotations

from datetime import date, datetime
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IngressMetadata(StrictModel):
    """Metadata for the trusted acquisition and secure transport boundary."""

    source_type: str = Field(default="UNSPECIFIED", min_length=2, max_length=64)
    protocol: Literal["HTTPS", "MQTT", "WebSocket"] = "HTTPS"
    stage: Literal["TERMINAL", "EDGE", "CLOUD", "BUSINESS"] = "BUSINESS"
    encryption: Literal["TLS1.3", "TLS1.2", "NOT_PROVIDED"] = "NOT_PROVIDED"
    attestation: str = Field(default="NOT_PROVIDED", min_length=2, max_length=128)


class LoginRequest(StrictModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class DataUploadCreate(StrictModel):
    asset_type: Literal[
        "GENERATION_DATA",
        "RENEWABLE_FORECAST",
        "RETAIL_DATA",
        "USER_LOAD_CURVE",
        "VPP_RESOURCE",
        "GRID_CONSTRAINT",
    ]
    trade_batch_no: str = Field(min_length=3, max_length=64)
    label: str = Field(min_length=2, max_length=128)
    schema_version: str = Field(default="v1.0", min_length=1, max_length=32)
    owner_org_id: str | None = None
    ingress: IngressMetadata = Field(default_factory=IngressMetadata)
    local_payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_payload_shape(self) -> "DataUploadCreate":
        payload = self.local_payload

        def number(name: str, *, minimum: float | None = None, maximum: float | None = None) -> None:
            value = payload.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"local_payload.{name} must be a number")
            if not math.isfinite(float(value)):
                raise ValueError(f"local_payload.{name} must be finite")
            if minimum is not None and value < minimum:
                raise ValueError(f"local_payload.{name} must be >= {minimum}")
            if maximum is not None and value > maximum:
                raise ValueError(f"local_payload.{name} must be <= {maximum}")

        if self.asset_type in {"GENERATION_DATA", "RETAIL_DATA"}:
            number("energy_mwh", minimum=0)
        elif self.asset_type == "RENEWABLE_FORECAST":
            number("forecast_energy_mwh", minimum=0)
            number("forecast_accuracy_pct", minimum=0, maximum=100)
        elif self.asset_type == "USER_LOAD_CURVE":
            curve = payload.get("load_curve")
            if not isinstance(curve, list) or len(curve) != 24:
                raise ValueError("local_payload.load_curve must contain exactly 24 values")
            if any(
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(float(item))
                or item < 0
                for item in curve
            ):
                raise ValueError("local_payload.load_curve must contain non-negative numbers")
        elif self.asset_type == "VPP_RESOURCE":
            number("adjustable_capacity_mw", minimum=0)
            number("storage_energy_mwh", minimum=0)
            number("response_minutes", minimum=0)
        elif self.asset_type == "GRID_CONSTRAINT":
            if not isinstance(payload.get("n_minus_one_passed"), bool):
                raise ValueError("local_payload.n_minus_one_passed must be a boolean")
            number("max_residual_imbalance_mwh", minimum=0)
            number("congestion_margin_pct", minimum=0, maximum=100)
        return self


class DataUsageRequestCreate(StrictModel):
    """Consumer-submitted data-use request; actor and provider are server-bound."""

    asset_id: str = Field(min_length=1, max_length=64)
    asset_version_id: str | None = Field(default=None, min_length=1, max_length=64)
    purpose: str = Field(min_length=2, max_length=64)
    usage_mode: str = Field(min_length=2, max_length=64)
    requested_scope: dict[str, Any] = Field(default_factory=dict)
    requested_fields: list[str] = Field(default_factory=list, max_length=128)
    # Optional on the wire so the service can apply its versioned server
    # policy.  The effective value is always persisted and returned with the
    # policy source; clients must not invent an asset-specific default.
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    terms: dict[str, Any] = Field(default_factory=dict)


class DataUsageRequestDecision(StrictModel):
    reason: str = Field(min_length=2, max_length=2000)


class DataUsageRequestReview(StrictModel):
    note: str = Field(default="", max_length=2000)


class ContractNegotiationEventCreate(StrictModel):
    event_type: Literal["COMMENT", "COUNTEROFFER", "COUNTER", "ATTACHMENT"] = "COMMENT"
    message: str = Field(default="", max_length=4000)
    terms: dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=16)


class ContractNegotiationAction(StrictModel):
    message: str = Field(default="", max_length=4000)
    terms: dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=16)


class TtcTransitionAction(StrictModel):
    to_state: str = Field(min_length=2, max_length=32)
    trigger: str = Field(min_length=2, max_length=96)
    reason: str = Field(min_length=2, max_length=1000)
    agent_did: str | None = Field(default=None, max_length=160)
    trace_id: str | None = Field(default=None, max_length=64)
    attempt_id: str | None = Field(default=None, max_length=36)


class ComputationAction(StrictModel):
    reason: str = Field(default="", max_length=1000)


class AssistantSessionCreate(StrictModel):
    """Create a user-and-organization scoped Trusted Space assistant session."""

    page_path: str | None = Field(default=None, max_length=255)
    entity_type: str | None = Field(default=None, max_length=64)
    entity_id: str | None = Field(default=None, max_length=96)


class AssistantMessageCreate(StrictModel):
    """A user message interpreted only by the deterministic allowlist planner."""

    content: str = Field(min_length=1, max_length=4000)


class AssistantExecuteRequest(StrictModel):
    """Optionally select one step from a persisted assistant plan."""

    step_id: str | None = Field(default=None, max_length=36)


class SolarEvaluationRequest(StrictModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timestamp_utc: datetime
    surface_tilt: float = Field(ge=0, le=180)
    surface_azimuth: float = Field(ge=-360, le=360)
    ghi_wm2: float = Field(ge=0, le=1500)
    dni_wm2: float = Field(ge=0, le=1500)
    dhi_wm2: float = Field(ge=0, le=1500)

    @model_validator(mode="after")
    def require_timezone(self) -> "SolarEvaluationRequest":
        if self.timestamp_utc.tzinfo is None or self.timestamp_utc.utcoffset() is None:
            raise ValueError("timestamp_utc must include a timezone")
        return self


class RuleCreate(StrictModel):
    rule_name: str = Field(min_length=2, max_length=128)
    description: str = Field(default="", max_length=2000)
    contract_price: float = Field(gt=0)
    deviation_threshold_mwh: float = Field(ge=0)
    deviation_penalty_rate: float = Field(ge=0)
    service_fee_rate: float = Field(ge=0)
    rounding: int = Field(default=2, ge=0, le=6)
    source_refs: list[str] = Field(default_factory=list)


class ParticipantInput(StrictModel):
    org_id: str = Field(min_length=1, max_length=64)
    role_in_task: Literal["GENERATOR", "RETAILER"]


class SettlementTaskCreate(StrictModel):
    task_name: str = Field(min_length=2, max_length=128)
    trade_batch_no: str = Field(min_length=3, max_length=64)
    period_start: date
    period_end: date
    rule_id: str
    participants: list[ParticipantInput] = Field(min_length=2)
    scenario_code: Literal["MARKET_SETTLEMENT"] = "MARKET_SETTLEMENT"
    business_description: str = Field(default="", max_length=1000)
    compute_mode: Literal["LOCAL_CONTROLLED"] = "LOCAL_CONTROLLED"
    algorithm_code: str = Field(default="CONTROLLED_SETTLEMENT_V1", min_length=2, max_length=64)
    output_mode: Literal["AGGREGATE_ONLY"] = "AGGREGATE_ONLY"


class WorkflowRunRequest(StrictModel):
    compute_mode: Literal["LOCAL_CONTROLLED"] = "LOCAL_CONTROLLED"
    algorithm_code: str = "CONTROLLED_SETTLEMENT_V1"


class ConnectorNegotiationRequest(StrictModel):
    task_id: str = Field(min_length=1, max_length=64)
    provider_org_id: str = Field(min_length=1, max_length=64)
    consumer_org_id: str = Field(min_length=1, max_length=64)
    asset_types: list[str] = Field(min_length=1)
    purpose: Literal["POWER_SETTLEMENT", "GRID_SECURITY_CHECK", "VPP_AGGREGATION"] = "POWER_SETTLEMENT"
    algorithm_code: str = Field(default="CONTROLLED_SETTLEMENT_V1", min_length=2, max_length=64)
    max_uses: int = Field(default=1, ge=1, le=100)


class UsageControlCheckRequest(StrictModel):
    agreement_id: str = Field(min_length=1, max_length=64)
    purpose: str = Field(min_length=2, max_length=64)
    algorithm_code: str = Field(min_length=2, max_length=64)
    raw_data_export: bool = False
    output_mode: Literal["AGGREGATE_ONLY", "RAW_RECORDS"] = "AGGREGATE_ONLY"
    execution_environment: Literal["APPLICATION_PROCESS", "UNTRUSTED_CLIENT"] = "APPLICATION_PROCESS"


class ResultConfirmRequest(StrictModel):
    decision: Literal["APPROVE", "REJECT"]
    opinion: str = Field(min_length=1, max_length=500)

    @field_validator("opinion")
    @classmethod
    def require_non_blank_opinion(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("opinion must not be blank")
        return normalized


class AuditReportCreate(StrictModel):
    task_id: str = Field(min_length=1, max_length=64)
    template_code: str = Field(default="REGULATORY_AUDIT_V1", min_length=1, max_length=48)


class AuditReportDecisionRequest(StrictModel):
    decision: Literal["APPROVE", "REJECT"]
    opinion: str = Field(min_length=1, max_length=500)

    @field_validator("opinion")
    @classmethod
    def require_non_blank_opinion(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("opinion must not be blank")
        return normalized


class AgentQueryRequest(StrictModel):
    task_id: str
    question: str = Field(min_length=2, max_length=500)


class TrustedQueryTranslation(StrictModel):
    """Canonical, locally validated instruction produced by the LLM preview."""

    function: Literal["SUM", "BALANCE", "TREND"]
    target_data_types: list[str] = Field(min_length=1, max_length=8)
    period_start: date
    period_end: date
    requested_granularity: Literal["MONTH", "DAY", "15_MINUTE", "DETAIL"]
    spatial_scope: Literal["REGION", "ORGANIZATION", "METER_POINT"]
    group_by: list[str] = Field(min_length=1, max_length=8)
    output_mode: Literal["SUMMARY", "CHART", "COMPUTE_ONLY"]


class TrustedExecutionRequest(StrictModel):
    """Natural-language/API request for the eight-step trusted execution loop."""

    question: str = Field(min_length=2, max_length=1000)
    consumer_role: Literal["ENERGY_BUREAU", "REGULATOR", "PUBLIC"] = "ENERGY_BUREAU"
    purpose: str = Field(default="CROSS_ENERGY_TREND", min_length=2, max_length=64)
    period_start: date | None = None
    period_end: date | None = None
    target_data_types: list[str] = Field(default_factory=list, max_length=12)
    group_by: list[str] = Field(default_factory=lambda: ["region", "period"], max_length=8)
    requested_fields: list[str] = Field(default_factory=list, max_length=24)
    requested_granularity: Literal["MONTH", "DAY", "15_MINUTE", "DETAIL"] | None = None
    spatial_scope: Literal["REGION", "ORGANIZATION", "METER_POINT"] = "REGION"
    output_mode: Literal["SUMMARY", "CHART", "COMPUTE_ONLY"] = "SUMMARY"
    translation: TrustedQueryTranslation | None = None
    translation_hash: str | None = Field(default=None, min_length=64, max_length=64)


class TrustedExecutionTranslationRequest(StrictModel):
    """Request for the optional DeepSeek natural-language translation preview."""

    question: str = Field(min_length=2, max_length=1000)
    period_start: date | None = None
    period_end: date | None = None
    requested_granularity: Literal["MONTH", "DAY", "15_MINUTE", "DETAIL"] | None = None
    spatial_scope: Literal["REGION", "ORGANIZATION", "METER_POINT"] = "REGION"
    group_by: list[str] = Field(default_factory=lambda: ["region", "period"], max_length=8)
    output_mode: Literal["SUMMARY", "CHART", "COMPUTE_ONLY"] = "SUMMARY"
    offline_test: bool = False


class TrustedExecutionReviewRequest(StrictModel):
    opinion: str = Field(default="核对通过，确认计算结果", min_length=2, max_length=500)
    accept: bool = True


class AgentInvokeRequest(StrictModel):
    task_id: str = Field(min_length=1, max_length=64)
    instruction: str = Field(min_length=2, max_length=500)


class AgentBatchInvokeRequest(StrictModel):
    task_id: str = Field(min_length=1, max_length=64)


class PrivacyAnalysisCreate(StrictModel):
    analysis_name: str = Field(min_length=2, max_length=128)
    dataset_ids: list[str] = Field(min_length=1)
    analysis_type: Literal["PEAK_VALLEY", "LOAD_CLUSTER", "DR_POTENTIAL"] = "PEAK_VALLEY"
    privacy_level: Literal["AGGREGATED", "K_ANONYMIZED", "DIFFERENTIAL_PRIVACY"] = "AGGREGATED"
    privacy_budget: float = Field(default=1.0, gt=0, le=10)
    scenario_code: Literal[
        "RENEWABLE_FORECAST",
        "MARKET_SETTLEMENT",
        "VPP_AGGREGATION",
        "GRID_SECURITY_CHECK",
    ] = "VPP_AGGREGATION"
    sensitivity_level: Literal["L2", "L3", "L4"] = "L3"
    latency_requirement: Literal["REAL_TIME", "MINUTE", "BATCH"] = "BATCH"


class AnomalyResolve(StrictModel):
    resolution: str = Field(min_length=2, max_length=500)
