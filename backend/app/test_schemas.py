from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import Field

from .schemas import IngressMetadata, ParticipantInput, StrictModel


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
    compute_mode: Literal["LOCAL_CONTROLLED"] = "LOCAL_CONTROLLED"
    algorithm_code: str = Field(default="CONTROLLED_SETTLEMENT_V1", min_length=2, max_length=64)


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
