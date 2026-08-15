from __future__ import annotations

from datetime import date, datetime
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IngressMetadata(StrictModel):
    """Metadata for the trusted acquisition and secure transport boundary."""

    source_type: str = Field(default="EDGE_METER", min_length=2, max_length=64)
    protocol: Literal["HTTPS", "MQTT", "WebSocket"] = "HTTPS"
    stage: Literal["TERMINAL", "EDGE", "CLOUD", "BUSINESS"] = "EDGE"
    encryption: Literal["TLS1.3", "TLS1.2"] = "TLS1.3"
    attestation: str = Field(default="虚拟仿真来源证明", min_length=2, max_length=128)


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


class WorkflowRunRequest(StrictModel):
    compute_mode: Literal["MPC_MOCK", "SECRET_FLOW"] = "MPC_MOCK"
    algorithm_code: str = "SETTLEMENT_MPC_V1"


class ConnectorNegotiationRequest(StrictModel):
    task_id: str = Field(min_length=1, max_length=64)
    provider_org_id: str = Field(min_length=1, max_length=64)
    consumer_org_id: str = Field(min_length=1, max_length=64)
    asset_types: list[str] = Field(min_length=1)
    purpose: Literal["POWER_SETTLEMENT", "GRID_SECURITY_CHECK", "VPP_AGGREGATION"] = "POWER_SETTLEMENT"
    algorithm_code: str = Field(default="SETTLEMENT_MPC_V1", min_length=2, max_length=64)
    max_uses: int = Field(default=1, ge=1, le=100)


class UsageControlCheckRequest(StrictModel):
    agreement_id: str = Field(min_length=1, max_length=64)
    purpose: str = Field(min_length=2, max_length=64)
    algorithm_code: str = Field(min_length=2, max_length=64)
    raw_data_export: bool = False
    output_mode: Literal["AGGREGATE_ONLY", "RAW_RECORDS"] = "AGGREGATE_ONLY"
    execution_environment: Literal["AUTHORIZED_COMPUTE_SANDBOX", "UNTRUSTED_CLIENT"] = "AUTHORIZED_COMPUTE_SANDBOX"


class ResultConfirmRequest(StrictModel):
    opinion: str = "同意场景结果"


class AuditReportCreate(StrictModel):
    task_id: str = Field(min_length=1, max_length=64)
    template_code: str = Field(default="REGULATORY_AUDIT_V1", min_length=1, max_length=48)


class AgentQueryRequest(StrictModel):
    task_id: str
    question: str = Field(min_length=2, max_length=500)


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
    output_mode: Literal["SUMMARY", "CHART", "COMPUTE_ONLY"] = "SUMMARY"


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


class ImportBatch(StrictModel):
    trade_batch_no: str = Field(min_length=3, max_length=64)
    period: str = Field(min_length=1, max_length=32)
    period_start: date
    period_end: date


class ImportDataAsset(StrictModel):
    asset_type: Literal[
        "GENERATION_DATA",
        "RENEWABLE_FORECAST",
        "RETAIL_DATA",
        "USER_LOAD_CURVE",
        "VPP_RESOURCE",
        "GRID_CONSTRAINT",
    ]
    upload_id: str | None = None
    owner_org_id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=2, max_length=128)
    ingress: IngressMetadata = Field(default_factory=IngressMetadata)
    local_payload: dict[str, Any]
    validation_status: str | None = None
    signature_status: str | None = None
    signature_id: str | None = None


class ImportPrivacyAnalysisRequest(StrictModel):
    analysis_name: str = Field(min_length=2, max_length=128)
    dataset_ids: list[str] = Field(default_factory=list)
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


class ImportBusinessValidationRequest(StrictModel):
    task_name: str = Field(min_length=2, max_length=128)
    rule_id: str = Field(min_length=1, max_length=64)
    participants: list[ParticipantInput] = Field(min_length=2)
    compute_mode: Literal["MPC_MOCK", "SECRET_FLOW"] = "MPC_MOCK"
    algorithm_code: str = Field(default="SETTLEMENT_MPC_V1", min_length=2, max_length=64)


class SettlementImportFile(StrictModel):
    fixture_id: str = Field(min_length=1, max_length=128)
    created_at: str | None = None
    is_simulated: bool = True
    organizations: dict[str, Any] = Field(default_factory=dict)
    batch: ImportBatch
    data_assets: list[ImportDataAsset] = Field(min_length=2)
    privacy_analysis_request: ImportPrivacyAnalysisRequest | None = None
    business_validation_request: ImportBusinessValidationRequest


class AnomalyInjectCreate(StrictModel):
    task_id: str
    event_type: Literal["HASH_MISMATCH", "UNAUTHORIZED_ACCESS", "MISSING_SIGNATURE", "POLICY_DENIED"]
    mutate_evidence: bool = False


class AnomalyResolve(StrictModel):
    resolution: str = Field(min_length=2, max_length=500)
