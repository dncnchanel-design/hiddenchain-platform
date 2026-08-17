from __future__ import annotations

import math
import time
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    BlockchainEvidence,
    DataContract,
    DataSpaceAgreement,
    DataUpload,
    DidIdentity,
    Organization,
    SettlementRule,
    SettlementTask,
    utc_now,
)
from ..security import sha256_json, sign_value
from .credentials import JsonLdCredentialAdapter
from .privacy import OpenDPAdapter
from .vault import LocalDomainVault


DATA_PRODUCT_CATALOG = {
    "GENERATION_DATA": {
        "label": "发电计量数据产品",
        "semantic_ref": "energy:GenerationMeasurement",
        "unit": "MWh",
        "time_granularity": "MONTH",
        "default_purpose": "POWER_SETTLEMENT",
    },
    "RETAIL_DATA": {
        "label": "售电履约数据产品",
        "semantic_ref": "energy:RetailDelivery",
        "unit": "MWh",
        "time_granularity": "MONTH",
        "default_purpose": "POWER_SETTLEMENT",
    },
    "USER_LOAD_CURVE": {
        "label": "用户负荷曲线数据产品",
        "semantic_ref": "energy:UserLoadCurve",
        "unit": "MW",
        "time_granularity": "HOUR",
        "default_purpose": "VPP_AGGREGATION",
    },
    "RENEWABLE_FORECAST": {
        "label": "新能源出力预测产品",
        "semantic_ref": "energy:RenewableForecast",
        "unit": "MWh",
        "time_granularity": "MONTH",
        "default_purpose": "POWER_SETTLEMENT",
    },
    "VPP_RESOURCE": {
        "label": "虚拟电厂可调资源产品",
        "semantic_ref": "energy:VppFlexibilityResource",
        "unit": "MW/MWh",
        "time_granularity": "MONTH",
        "default_purpose": "VPP_AGGREGATION",
    },
    "GRID_CONSTRAINT": {
        "label": "调度安全边界产品",
        "semantic_ref": "energy:GridSecurityConstraint",
        "unit": "MWh/%",
        "time_granularity": "DAY",
        "default_purpose": "GRID_SECURITY_CHECK",
    },
}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


AGENT_DEFINITIONS = [
    {
        "code": "ORCHESTRATOR",
        "name": "四场景可信编排Agent",
        "did": "did:hiddenchain:agent:orchestrator",
        "tools": ["WorkflowEngine", "TaskStateStore", "CapabilityGateway"],
        "input": "用户请求、四场景任务上下文",
        "output": "TaskContext、跨场景TaskDAG",
        "scenario_code": "CROSS_SCENARIO",
        "business_mandate": "识别交易意图，编排新能源、市场、虚拟电厂、调度与监管任务。",
    },
    {
        "code": "DATA_ACCESS",
        "name": "新能源消纳Agent",
        "did": "did:hiddenchain:agent:data-access",
        "tools": ["EDCAdapter", "ForecastFeatureAdapter", "DataCatalog", "PolicyEngine"],
        "input": "出力预测、计量DataRef、主体DID",
        "output": "预测风险摘要、DataPermit",
        "scenario_code": "RENEWABLE_CONSUMPTION",
        "business_mandate": "校验新能源预测与计量承诺，输出可供交易使用的风险摘要。",
    },
    {
        "code": "RULE_CONTRACT",
        "name": "市场交易Agent",
        "did": "did:hiddenchain:agent:rule-contract",
        "tools": ["RuleRAG", "DSLValidator", "OPAAdapter", "MarketRuleEngine", "SigningGate"],
        "input": "交易批次、市场规则、数据许可",
        "output": "RulePackage、RuleHash、结算计算计划",
        "scenario_code": "MARKET_TRADING",
        "business_mandate": "解析市场条款，固化确定性规则并组织多方自动结算。",
    },
    {
        "code": "SECURE_SETTLEMENT",
        "name": "虚拟电厂协同Agent",
        "did": "did:hiddenchain:agent:secure-settlement",
        "tools": ["CommitmentJoin", "LocalControlledCompute", "VPPResourceAdapter", "DeterministicEngine"],
        "input": "DataPermit、RulePackage、可调资源承诺",
        "output": "响应计划、ComputeReceipt、SettlementResult",
        "scenario_code": "VPP_OPERATION",
        "business_mandate": "在不暴露单户负荷的前提下聚合可调能力并修正交易偏差。",
    },
    {
        "code": "AUDIT_RISK",
        "name": "电网调度与监管Agent",
        "did": "did:hiddenchain:agent:audit-risk",
        "tools": ["GridBoundaryAdapter", "SecurityGate", "EvidenceGraph", "LocalEvidenceLedger", "RiskRuleEngine"],
        "input": "调度边界承诺、计算回执、证据事件",
        "output": "安全校核结论、AuditBundle、风险等级",
        "scenario_code": "GRID_DISPATCH",
        "business_mandate": "在结算前执行安全闸门，并在结算后核验证据与异常责任。",
    },
    {
        "code": "REPORT_EXPLAIN",
        "name": "可信报告Agent",
        "did": "did:hiddenchain:agent:report-explain",
        "tools": ["ReportTemplate", "CitationRAG", "CredentialService"],
        "input": "四场景结果、AuditBundle",
        "output": "可引用ReportArtifact、审计凭证",
        "scenario_code": "REGULATORY_REPORT",
        "business_mandate": "只依据结构化证据生成报告，输出可追溯引用而非黑箱结论。",
    },
]


class IdentityCredentialAdapter:
    code = "LOCAL_DID_CREDENTIAL_V1"

    @staticmethod
    def verify_owner(db: Session, owner_id: str) -> dict[str, Any]:
        did = db.scalar(select(DidIdentity).where(DidIdentity.owner_id == owner_id))
        if did is None or did.credential_status != "VALID":
            raise ValueError(f"DID/VC verification failed for {owner_id}")
        return {
            "did": did.did_id,
            "credential_status": did.credential_status,
            "fingerprint": did.public_key_fingerprint,
            "credential_evidence": JsonLdCredentialAdapter.fingerprint(did.credential_json),
            "verified": True,
        }

    @staticmethod
    def issue_capability(agent_did: str, tools: list[str], capsule_id: str) -> dict[str, Any]:
        claims = {
            "sub": agent_did,
            "capsule_id": capsule_id,
            "tools": tools,
            "expires_at": (utc_now() + timedelta(minutes=30)).isoformat(),
        }
        return {"claims": claims, "token_signature": sign_value(claims, agent_did)}


class OPAPolicyAdapter:
    """Evaluate the local policy contract through OPA's REST shape.

    The local evaluator intentionally mirrors the bundled Rego policy. This
    keeps local development and unit tests deterministic while Docker Compose
    can use a real OPA sidecar by setting ``OPA_URL``.
    """

    code = "OPA_REGO_COMPAT"
    policy_version = "hiddenchain/v1"

    @staticmethod
    def _epoch(value: datetime | None) -> float | None:
        return value.timestamp() if value else None

    @classmethod
    def _input(
        cls,
        contract: DataContract,
        requested_purpose: str,
        capsule_id: str,
        *,
        consumer_did: str | None,
        algorithm_code: str,
        execution_environment: str,
        output_mode: str,
        raw_data_export: bool,
        use_count: int | None,
        max_uses: int | None,
        agreement_state: str | None,
        now: datetime,
    ) -> dict[str, Any]:
        constraints = contract.policy_json.get("constraint", {})
        valid_from = _parse_dt(constraints.get("valid_from"))
        expires_at = _parse_dt(constraints.get("expires_at"))
        return {
            "contract_status": contract.status,
            "contract_purpose": contract.purpose,
            "requested_purpose": requested_purpose,
            "expected_capsule_id": constraints.get("capsule_id"),
            "capsule_id": capsule_id,
            "expected_consumer_did": constraints.get("consumer_did"),
            "consumer_did": consumer_did,
            "allowed_algorithms": constraints.get("algorithm_codes") or [algorithm_code],
            "algorithm_code": algorithm_code,
            "expected_execution_environment": constraints.get("execution_environment"),
            "execution_environment": execution_environment,
            "expected_output_mode": constraints.get("output_mode"),
            "output_mode": output_mode,
            "contract_raw_data_export": constraints.get("raw_data_export"),
            "raw_data_export": raw_data_export,
            "valid_from_epoch": cls._epoch(valid_from),
            "expires_at_epoch": cls._epoch(expires_at),
            "now_epoch": cls._epoch(now),
            "use_count": use_count,
            "max_uses": max_uses,
            "agreement_state": agreement_state,
            "obligations": contract.policy_json.get("obligation", []),
        }

    @staticmethod
    def _local_decision(policy_input: dict[str, Any]) -> dict[str, Any]:
        reasons: list[str] = []
        if policy_input["contract_status"] != "ACTIVE":
            reasons.append("CONTRACT_NOT_ACTIVE")
        if policy_input["contract_purpose"] != policy_input["requested_purpose"]:
            reasons.append("PURPOSE_MISMATCH")
        if policy_input["expected_capsule_id"] != policy_input["capsule_id"]:
            reasons.append("CAPSULE_MISMATCH")
        expected_consumer = policy_input.get("expected_consumer_did")
        if expected_consumer and policy_input.get("consumer_did") is not None and expected_consumer != policy_input["consumer_did"]:
            reasons.append("CONSUMER_MISMATCH")
        if policy_input["algorithm_code"] not in policy_input["allowed_algorithms"]:
            reasons.append("ALGORITHM_NOT_ALLOWED")
        expected_environment = policy_input.get("expected_execution_environment")
        if expected_environment and policy_input["execution_environment"] != expected_environment:
            reasons.append("EXECUTION_ENVIRONMENT_NOT_ALLOWED")
        expected_output_mode = policy_input.get("expected_output_mode")
        if expected_output_mode and policy_input["output_mode"] != expected_output_mode:
            reasons.append("OUTPUT_MODE_NOT_ALLOWED")
        if policy_input["raw_data_export"] or policy_input.get("contract_raw_data_export") is not False:
            reasons.append("RAW_DATA_EXPORT_NOT_ALLOWED")
        valid_from = policy_input.get("valid_from_epoch")
        expires_at = policy_input.get("expires_at_epoch")
        now = policy_input.get("now_epoch")
        if valid_from is not None and now < valid_from:
            reasons.append("CONTRACT_NOT_YET_VALID")
        if expires_at is not None and now >= expires_at:
            reasons.append("CONTRACT_EXPIRED")
        if policy_input.get("agreement_state") and policy_input["agreement_state"] not in {"NEGOTIATED", "ACTIVE"}:
            reasons.append("AGREEMENT_NOT_ACTIVE")
        if policy_input.get("max_uses") is not None and policy_input.get("use_count", 0) >= policy_input["max_uses"]:
            reasons.append("USE_LIMIT_REACHED")
        return {
            "allow": not reasons,
            "reasons": reasons,
            "obligations": policy_input.get("obligations", []),
        }

    @classmethod
    def _remote_decision(cls, policy_input: dict[str, Any]) -> dict[str, Any] | None:
        if not settings.opa_url:
            return None
        endpoint = f"{settings.opa_url}{settings.opa_policy_path}"
        try:
            response = httpx.post(
                endpoint,
                json={"input": policy_input},
                timeout=settings.opa_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json().get("result")
            if not isinstance(payload, dict) or not isinstance(payload.get("allow"), bool):
                return None
            return {
                "allow": payload["allow"],
                "reasons": list(payload.get("reasons") or []),
                "obligations": list(payload.get("obligations") or policy_input.get("obligations", [])),
            }
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    @classmethod
    def evaluate(
        cls,
        contract: DataContract,
        requested_purpose: str,
        capsule_id: str,
        *,
        consumer_did: str | None = None,
        algorithm_code: str = "CONTROLLED_SETTLEMENT_V1",
        execution_environment: str = "APPLICATION_PROCESS",
        output_mode: str = "AGGREGATE_ONLY",
        raw_data_export: bool = False,
        use_count: int | None = None,
        max_uses: int | None = None,
        agreement_state: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or utc_now()
        policy_input = cls._input(
            contract,
            requested_purpose,
            capsule_id,
            consumer_did=consumer_did,
            algorithm_code=algorithm_code,
            execution_environment=execution_environment,
            output_mode=output_mode,
            raw_data_export=raw_data_export,
            use_count=use_count,
            max_uses=max_uses,
            agreement_state=agreement_state,
            now=now,
        )
        remote = cls._remote_decision(policy_input)
        if remote is None and settings.opa_url and not settings.opa_local_fallback:
            evaluated = {
                "allow": False,
                "reasons": ["OPA_UNAVAILABLE"],
                "obligations": policy_input.get("obligations", []),
            }
        else:
            evaluated = remote or cls._local_decision(policy_input)
        fallback_used = remote is None and bool(settings.opa_url) and settings.opa_local_fallback
        engine = (
            "OPA_REST"
            if remote is not None
            else ("OPA_REGO_COMPAT_LOCAL" if fallback_used or not settings.opa_url else "OPA_FAIL_CLOSED")
        )
        result_basis = {
            "policy_hash": contract.policy_hash,
            "input_hash": sha256_json(policy_input),
            "allow": evaluated["allow"],
            "reasons": evaluated["reasons"],
        }
        return {
            "decision": "PERMIT" if evaluated["allow"] else "DENY",
            "policy_hash": contract.policy_hash,
            "policy_engine": engine,
            "policy_version": cls.policy_version,
            "policy_input_hash": sha256_json(policy_input),
            "decision_hash": sha256_json(result_basis),
            "policy_remote_configured": bool(settings.opa_url),
            "policy_local_fallback": fallback_used,
            "purpose": requested_purpose,
            "consumer_did": consumer_did or policy_input.get("expected_consumer_did"),
            "algorithm_code": algorithm_code,
            "execution_environment": execution_environment,
            "output_mode": output_mode,
            "reasons": evaluated["reasons"],
            "obligations": evaluated["obligations"],
        }

    @classmethod
    def status(cls) -> dict[str, Any]:
        return {
            "code": cls.code,
            "policy_version": cls.policy_version,
            "remote_configured": bool(settings.opa_url),
            "local_fallback_enabled": settings.opa_local_fallback,
            "endpoint": settings.opa_policy_path,
        }


class LocalUsagePolicyAdapter:
    """Create and evaluate the local data-use policy contract."""

    code = OPAPolicyAdapter.code

    @staticmethod
    def create_contract(
        db: Session,
        task: SettlementTask,
        provider: Organization,
        uploads: list[DataUpload],
        consumer_org_id: str,
        purpose: str = "POWER_SETTLEMENT",
        algorithm_code: str = "CONTROLLED_SETTLEMENT_V1",
        max_uses: int = 1,
    ) -> DataContract:
        consumer_did_record = db.scalar(
            select(DidIdentity).where(DidIdentity.owner_id == consumer_org_id)
        )
        consumer_did = (
            consumer_did_record.did_id
            if consumer_did_record
            else f"did:hiddenchain:org:{consumer_org_id}"
        )
        expires_at = utc_now() + timedelta(days=7)
        data_product_ids = [DataSpaceConnectorAdapter.data_product_id(upload) for upload in uploads]
        policy = {
            "profile": "HCDS-ODRL-DATASPACE-1.0",
            "permission": [
                {
                    "action": "use",
                    "purpose": purpose,
                    "assignee": consumer_did,
                    "target": data_product_ids,
                }
            ],
            "constraint": {
                "data_scope": [upload.asset_type for upload in uploads],
                "data_product_ids": data_product_ids,
                "capsule_id": task.capsule_id,
                "consumer_did": consumer_did,
                "algorithm_codes": [algorithm_code],
                "execution_environment": "APPLICATION_PROCESS",
                "output_mode": "AGGREGATE_ONLY",
                "max_uses": max_uses,
                "valid_from": utc_now().isoformat(),
                "expires_at": expires_at.isoformat(),
                "raw_data_export": False,
            },
            "obligation": [
                "LOG_USAGE",
                "ANCHOR_RECEIPT",
                "DELETE_ON_EXPIRY",
                "NO_SECONDARY_DISTRIBUTION",
            ],
        }
        contract = DataContract(
            task_id=task.task_id,
            provider_org_id=provider.org_id,
            consumer_type=consumer_org_id,
            purpose=purpose,
            data_refs_json=[upload.data_ref for upload in uploads],
            policy_json=policy,
            policy_hash=sha256_json(policy),
            status="ACTIVE",
        )
        db.add(contract)
        db.flush()
        return contract

    @staticmethod
    def evaluate(
        contract: DataContract,
        requested_purpose: str,
        capsule_id: str,
        *,
        consumer_did: str | None = None,
        algorithm_code: str = "CONTROLLED_SETTLEMENT_V1",
        execution_environment: str = "APPLICATION_PROCESS",
        output_mode: str = "AGGREGATE_ONLY",
        raw_data_export: bool = False,
        use_count: int | None = None,
        max_uses: int | None = None,
        agreement_state: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return OPAPolicyAdapter.evaluate(
            contract,
            requested_purpose,
            capsule_id,
            consumer_did=consumer_did,
            algorithm_code=algorithm_code,
            execution_environment=execution_environment,
            output_mode=output_mode,
            raw_data_export=raw_data_export,
            use_count=use_count,
            max_uses=max_uses,
            agreement_state=agreement_state,
            now=now,
        )


class DataSpaceConnectorAdapter:
    """A small, testable connector boundary aligned with the dataspace papers.

    It intentionally keeps the current local Vault and controlled compute runtime,
    but makes catalog discovery, agreement negotiation, policy enforcement and
    receipt recording explicit so a real EDC/OPA adapter can replace it later.
    """

    code = "HCDS_CONNECTOR_1_0"
    protocol_version = "HCDS-1.0"
    transport_protocols = ["HTTPS", "MQTT", "WebSocket"]
    connected_layers = ["数据采集终端", "边缘计算节点", "云端数据中心", "业务应用系统"]

    @staticmethod
    def data_product_id(upload: DataUpload) -> str:
        return f"DP-{sha256_json({'upload_id': upload.upload_id, 'schema': upload.schema_version})[:20].upper()}"

    @staticmethod
    def catalog_entry(
        upload: DataUpload,
        *,
        owner_did: str | None = None,
        owner_name: str | None = None,
    ) -> dict[str, Any]:
        spec = DATA_PRODUCT_CATALOG.get(upload.asset_type, {})
        summary = upload.summary_json or {}
        sensitivity = "L4" if upload.asset_type == "GRID_CONSTRAINT" else (
            "L3" if upload.asset_type in {"GENERATION_DATA", "RETAIL_DATA", "USER_LOAD_CURVE"} else "L2"
        )
        return {
            "data_product_id": DataSpaceConnectorAdapter.data_product_id(upload),
            "upload_id": upload.upload_id,
            "asset_type": upload.asset_type,
            "label": upload.label,
            "owner_org_id": upload.owner_org_id,
            "owner_did": owner_did,
            "owner_org_name": owner_name,
            "connector_id": f"connector://hiddenchain/{upload.owner_org_id}",
            "endpoint": f"connector://hiddenchain/{upload.owner_org_id}/products/{upload.upload_id}",
            "trade_batch_no": upload.trade_batch_no,
            "schema_version": upload.schema_version,
            "semantic_ref": spec.get("semantic_ref", f"energy:{upload.asset_type}"),
            "unit": spec.get("unit", "UNSPECIFIED"),
            "time_granularity": spec.get("time_granularity", "UNSPECIFIED"),
            "sensitivity_level": sensitivity,
            "quality": {
                "validation_status": upload.validation_status,
                "record_count": summary.get("record_count", 0),
                "period": summary.get("period"),
                "data_hash": upload.data_hash,
            },
            "commitment_confirmed": bool(upload.signature_value),
            "usage": {
                "allowed_purposes": [spec.get("default_purpose", "POWER_SETTLEMENT")],
                "output_mode": "AGGREGATE_ONLY",
                "raw_data_export": False,
            },
            "raw_data_exposed": False,
            "transport": {
                "protocol": upload.ingress_json.get("protocol", "HTTPS"),
                "protocols": DataSpaceConnectorAdapter.transport_protocols,
                "source_layer": upload.ingress_json.get("stage", "BUSINESS"),
                "encryption": upload.ingress_json.get("encryption", "NOT_PROVIDED"),
                "attestation": upload.ingress_json.get("attestation", "NOT_PROVIDED"),
            },
        }

    @staticmethod
    def catalog(
        db: Session,
        *,
        asset_type: str | None = None,
        trade_batch_no: str | None = None,
        owner_org_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = select(DataUpload).where(DataUpload.validation_status == "PASSED")
        if asset_type:
            query = query.where(DataUpload.asset_type == asset_type)
        if trade_batch_no:
            query = query.where(DataUpload.trade_batch_no == trade_batch_no)
        if owner_org_id:
            query = query.where(DataUpload.owner_org_id == owner_org_id)
        uploads = db.scalars(query.order_by(DataUpload.created_at.desc())).all()
        orgs = {item.org_id: item for item in db.scalars(select(Organization)).all()}
        dids = {item.owner_id: item for item in db.scalars(select(DidIdentity)).all()}
        return [
            DataSpaceConnectorAdapter.catalog_entry(
                upload,
                owner_did=dids.get(upload.owner_org_id).did_id if dids.get(upload.owner_org_id) else None,
                owner_name=orgs.get(upload.owner_org_id).org_name if orgs.get(upload.owner_org_id) else None,
            )
            for upload in uploads
        ]

    @staticmethod
    def negotiate(
        db: Session,
        *,
        task: SettlementTask,
        contract: DataContract,
        provider_org_id: str,
        consumer_org_id: str,
        uploads: list[DataUpload],
        purpose: str,
        algorithm_code: str,
        max_uses: int = 1,
        current_trace_id: str,
    ) -> tuple[DataSpaceAgreement, dict[str, Any]]:
        provider_proof = IdentityCredentialAdapter.verify_owner(db, provider_org_id)
        consumer_proof = IdentityCredentialAdapter.verify_owner(db, consumer_org_id)
        decision = LocalUsagePolicyAdapter.evaluate(
            contract,
            purpose,
            task.capsule_id,
            consumer_did=consumer_proof["did"],
            algorithm_code=algorithm_code,
        )
        now = utc_now()
        constraints = contract.policy_json.get("constraint", {})
        expires_at = _parse_dt(constraints.get("expires_at")) or now + timedelta(days=7)
        agreement = DataSpaceAgreement(
            contract_id=contract.contract_id,
            task_id=task.task_id,
            provider_org_id=provider_org_id,
            consumer_org_id=consumer_org_id,
            provider_did=provider_proof["did"],
            consumer_did=consumer_proof["did"],
            protocol_version=DataSpaceConnectorAdapter.protocol_version,
            state="NEGOTIATED" if decision["decision"] == "PERMIT" else "REJECTED",
            requested_purpose=purpose,
            algorithm_code=algorithm_code,
            data_product_ids_json=[DataSpaceConnectorAdapter.data_product_id(upload) for upload in uploads],
            offered_policy_hash=contract.policy_hash,
            negotiated_policy_hash=contract.policy_hash,
            valid_from=_parse_dt(constraints.get("valid_from")) or now,
            expires_at=expires_at,
            max_uses=max_uses,
            use_count=0,
            decision_json={
                **decision,
                "provider_connector": f"connector://hiddenchain/{provider_org_id}",
                "consumer_connector": f"connector://hiddenchain/{consumer_org_id}",
                "protocol_version": DataSpaceConnectorAdapter.protocol_version,
            },
            trace_id=current_trace_id,
        )
        db.add(agreement)
        db.flush()
        return agreement, agreement.decision_json

    @staticmethod
    def enforce(
        db: Session,
        agreement: DataSpaceAgreement,
        *,
        purpose: str,
        algorithm_code: str,
        execution_environment: str = "APPLICATION_PROCESS",
        output_mode: str = "AGGREGATE_ONLY",
        raw_data_export: bool = False,
        consume: bool = False,
    ) -> dict[str, Any]:
        contract = db.get(DataContract, agreement.contract_id)
        if contract is None:
            return {"decision": "DENY", "reasons": ["CONTRACT_NOT_FOUND"]}
        decision = LocalUsagePolicyAdapter.evaluate(
            contract,
            purpose,
            contract.policy_json.get("constraint", {}).get("capsule_id", ""),
            consumer_did=agreement.consumer_did,
            algorithm_code=algorithm_code,
            execution_environment=execution_environment,
            output_mode=output_mode,
            raw_data_export=raw_data_export,
            use_count=agreement.use_count,
            max_uses=agreement.max_uses,
            agreement_state=agreement.state,
        )
        if agreement.state not in {"NEGOTIATED", "ACTIVE"}:
            decision["decision"] = "DENY"
            if "AGREEMENT_NOT_ACTIVE" not in decision.setdefault("reasons", []):
                decision["reasons"].append("AGREEMENT_NOT_ACTIVE")
        if agreement.use_count >= agreement.max_uses:
            decision["decision"] = "DENY"
            if "USE_LIMIT_REACHED" not in decision.setdefault("reasons", []):
                decision["reasons"].append("USE_LIMIT_REACHED")
        if utc_now() >= agreement.expires_at:
            decision["decision"] = "DENY"
            decision.setdefault("reasons", []).append("AGREEMENT_EXPIRED")
        if decision["decision"] == "PERMIT" and consume:
            agreement.use_count += 1
            agreement.state = "CONSUMED" if agreement.use_count >= agreement.max_uses else "ACTIVE"
            agreement.decision_json = decision
        decision.update(
            {
                "agreement_id": agreement.agreement_id,
                "use_count": agreement.use_count,
                "max_uses": agreement.max_uses,
                "remaining_uses": max(agreement.max_uses - agreement.use_count, 0),
            }
        )
        return decision

    @staticmethod
    def record_receipt(
        agreement: DataSpaceAgreement,
        receipt: dict[str, Any],
    ) -> None:
        agreement.last_receipt_json = {
            "receipt_hash": sha256_json(receipt),
            "output_hash": receipt.get("output_hash"),
            "api_raw_records_returned": receipt.get("execution_attestation", {}).get(
                "api_raw_records_returned"
            ),
            "cross_domain_non_export_verified": receipt.get("execution_attestation", {}).get(
                "cross_domain_non_export_verified"
            ),
            "recorded_at": utc_now().isoformat(),
        }


class RulePackageAdapter:
    code = "SIGNED_RULE_PACKAGE_V1"

    @staticmethod
    def build(rule: SettlementRule) -> dict[str, Any]:
        package = {
            "rule_id": rule.rule_id,
            "version": rule.rule_version,
            "source_refs": rule.source_refs_json,
            "formula_dsl": rule.formula_dsl,
            "parameters": rule.parameters_json,
            "policy_refs": rule.policy_refs_json,
            "approver_signatures": rule.approver_signatures_json,
            "rounding": rule.parameters_json.get("rounding", 2),
            "rule_hash": rule.rule_hash,
        }
        package["package_hash"] = sha256_json(package)
        return package


class AdaptivePrivacyRouter:
    """Build a deterministic compute plan from business and security constraints."""

    SCENARIOS = {
        "RENEWABLE_FORECAST": {
            "name": "新能源与负荷联合预测",
            "primary": "FEDERATED_LEARNING",
            "supporting": ["DIFFERENTIAL_PRIVACY_OUTPUT"],
            "reason": "多方联合训练但不交换原始气象、出力与负荷样本。",
        },
        "MARKET_SETTLEMENT": {
            "name": "电力市场联合结算",
            "primary": "PSI_MPC",
            "supporting": ["DETERMINISTIC_RULE_ENGINE"],
            "reason": "候选方案需接入并验证外部PSI/MPC运行时；当前系统不会执行该方案。",
        },
        "VPP_AGGREGATION": {
            "name": "虚拟电厂资源聚合",
            "primary": "SECRET_SHARING_HE",
            "supporting": ["DIFFERENTIAL_PRIVACY_OUTPUT"],
            "reason": "隐藏单户负荷和设备能力，仅释放资源池聚合值与响应潜力。",
        },
        "GRID_SECURITY_CHECK": {
            "name": "实时调度安全校核",
            "primary": "TEE_CONFIDENTIAL_COMPUTE",
            "supporting": ["POLICY_SANDBOX"],
            "reason": "候选方案需接入TEE并完成远程证明；当前系统不会执行该方案。",
        },
    }

    @classmethod
    def recommend(
        cls,
        scenario_code: str,
        *,
        sensitivity_level: str = "L3",
        latency_requirement: str = "BATCH",
        participant_count: int = 2,
    ) -> dict[str, Any]:
        selected = cls.SCENARIOS.get(scenario_code, cls.SCENARIOS["MARKET_SETTLEMENT"])
        primary = selected["primary"]
        supporting = list(selected["supporting"])
        reasons = [selected["reason"]]
        if latency_requirement == "REAL_TIME" and primary != "TEE_CONFIDENTIAL_COMPUTE":
            supporting.insert(0, primary)
            primary = "TEE_CONFIDENTIAL_COMPUTE"
            reasons.append("实时任务建议评估外部TEE；接入并完成远程证明前不可执行该候选方案。")
        if sensitivity_level == "L4" and "DIFFERENTIAL_PRIVACY_OUTPUT" not in supporting:
            supporting.append("DIFFERENTIAL_PRIVACY_OUTPUT")
            reasons.append("L4数据的对外结果增加差分隐私披露约束。")
        plan = {
            "scenario_code": scenario_code,
            "scenario_name": selected["name"],
            "primary": primary,
            "supporting": supporting,
            "sensitivity_level": sensitivity_level,
            "latency_requirement": latency_requirement,
            "participant_count": participant_count,
            "release_policy": "AGGREGATE_ONLY",
            "raw_data_export": False,
            "implementation_status": "NOT_CONFIGURED",
            "execution_capability": False,
            "requires_external_runtime": True,
            "reason": " ".join(reasons),
        }
        plan["plan_hash"] = sha256_json(plan)
        return plan

    @classmethod
    def catalog(cls) -> list[dict[str, Any]]:
        defaults = {
            "RENEWABLE_FORECAST": ("L3", "BATCH", 3),
            "MARKET_SETTLEMENT": ("L4", "BATCH", 2),
            "VPP_AGGREGATION": ("L4", "MINUTE", 3),
            "GRID_SECURITY_CHECK": ("L4", "REAL_TIME", 2),
        }
        return [
            cls.recommend(
                code,
                sensitivity_level=values[0],
                latency_requirement=values[1],
                participant_count=values[2],
            )
            for code, values in defaults.items()
        ]


class PandapowerGridAdapter:
    """Run a small deterministic three-bus security check with pandapower."""

    code = "PANDAPOWER_3_BUS"
    network_version = "3-bus-110kv-v1"

    @classmethod
    def status(cls) -> dict[str, Any]:
        try:
            import importlib.util

            installed = importlib.util.find_spec("pandapower") is not None
        except (ImportError, ModuleNotFoundError):
            installed = False
        return {
            "code": cls.code,
            "network_version": cls.network_version,
            "installed": installed,
            "mode": "DETERMINISTIC_THREE_BUS_SECURITY_CHECK",
        }

    @staticmethod
    def _number(payload: dict[str, Any], key: str, default: float) -> float:
        value = payload.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def check(
        self,
        *,
        generation_mwh: float,
        retail_mwh: float,
        vpp_adjustment_mwh: float,
        deviation_mwh: float,
        grid_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = grid_payload or {}
        dispatch_hours = max(self._number(payload, "dispatch_hours", 720.0), 1.0)
        line_limit_mw = max(self._number(payload, "line_limit_mw", 120.0), 0.1)
        congestion_margin_pct = min(max(self._number(payload, "congestion_margin_pct", 0.0), 0.0), 100.0)
        max_line_loading_pct = min(
            max(self._number(payload, "max_line_loading_pct", 100.0 - congestion_margin_pct), 1.0),
            100.0,
        )
        min_voltage_pu = self._number(payload, "min_voltage_pu", 0.95)
        max_voltage_pu = self._number(payload, "max_voltage_pu", 1.05)
        max_residual = self._number(payload, "max_residual_imbalance_mwh", 999999.0)
        n_minus_one_passed = bool(payload.get("n_minus_one_passed", True))

        try:
            import pandapower as pp

            net = pp.create_empty_network(sn_mva=100.0)
            grid_bus = pp.create_bus(net, vn_kv=110.0, name="grid")
            generator_bus = pp.create_bus(net, vn_kv=110.0, name="generator")
            load_bus = pp.create_bus(net, vn_kv=110.0, name="retail-load")
            pp.create_ext_grid(net, grid_bus, vm_pu=1.0, name="system-grid")
            pp.create_sgen(
                net,
                generator_bus,
                p_mw=max(float(generation_mwh), 0.0) / dispatch_hours,
                q_mvar=0.0,
                name="renewable-generation",
            )
            pp.create_load(
                net,
                load_bus,
                p_mw=max(float(retail_mwh) - float(vpp_adjustment_mwh), 0.0) / dispatch_hours,
                q_mvar=0.0,
                name="retail-load",
            )
            max_i_ka = line_limit_mw / (math.sqrt(3.0) * 110.0)
            line_kwargs = {
                "length_km": 1.0,
                "r_ohm_per_km": 0.03,
                "x_ohm_per_km": 0.08,
                "c_nf_per_km": 10.0,
                "max_i_ka": max_i_ka,
                "name": "grid-boundary-line",
            }
            pp.create_line_from_parameters(net, grid_bus, generator_bus, **line_kwargs)
            pp.create_line_from_parameters(net, generator_bus, load_bus, **line_kwargs)
            pp.runpp(net, calculate_voltage_angles=False, init="flat", numba=False)

            line_loadings = [
                float(value)
                for value in net.res_line.loading_percent.tolist()
                if math.isfinite(float(value))
            ]
            voltage_values = [
                float(value)
                for value in net.res_bus.vm_pu.tolist()
                if math.isfinite(float(value))
            ]
            max_line_loading = max(line_loadings, default=0.0)
            min_voltage = min(voltage_values, default=0.0)
            max_voltage = max(voltage_values, default=0.0)
            reasons: list[str] = []
            if not n_minus_one_passed:
                reasons.append("N_MINUS_ONE_REJECTED")
            if float(deviation_mwh) > max_residual:
                reasons.append("RESIDUAL_IMBALANCE_EXCEEDED")
            if max_line_loading > max_line_loading_pct:
                reasons.append("LINE_LOADING_EXCEEDED")
            if min_voltage < min_voltage_pu or max_voltage > max_voltage_pu:
                reasons.append("VOLTAGE_LIMIT_EXCEEDED")
            return {
                "adapter": self.code,
                "network_version": self.network_version,
                "passed": not reasons,
                "reasons": reasons,
                "metrics": {
                    "dispatch_hours": dispatch_hours,
                    "max_line_loading_pct": round(max_line_loading, 4),
                    "min_voltage_pu": round(min_voltage, 6),
                    "max_voltage_pu": round(max_voltage, 6),
                    "residual_imbalance_mwh": round(float(deviation_mwh), 4),
                },
                "constraints": {
                    "max_line_loading_pct": max_line_loading_pct,
                    "min_voltage_pu": min_voltage_pu,
                    "max_voltage_pu": max_voltage_pu,
                    "max_residual_imbalance_mwh": max_residual,
                    "n_minus_one_passed": n_minus_one_passed,
                },
                "raw_data_exposed": False,
            }
        except (ImportError, ModuleNotFoundError):
            return {
                "adapter": self.code,
                "network_version": self.network_version,
                "passed": False,
                "reasons": ["PANDAPOWER_NOT_INSTALLED"],
                "metrics": {},
                "constraints": {},
                "raw_data_exposed": False,
            }
        except Exception as exc:
            return {
                "adapter": self.code,
                "network_version": self.network_version,
                "passed": False,
                "reasons": ["POWER_FLOW_FAILED"],
                "error_type": type(exc).__name__,
                "metrics": {},
                "constraints": {},
                "raw_data_exposed": False,
            }


class LocalControlledComputeAdapter:
    """Deterministic in-process calculation with aggregate-only API output.

    This adapter does not claim MPC, TEE, or cross-domain data non-export. Those
    guarantees require an external protocol implementation and attestation.
    """

    code = "LOCAL_CONTROLLED_SETTLEMENT_V1"

    @staticmethod
    def _quantize(value: Decimal, digits: int) -> Decimal:
        quantum = Decimal("1").scaleb(-digits)
        return value.quantize(quantum, rounding=ROUND_HALF_UP)

    def run_settlement(
        self,
        *,
        generator_upload: DataUpload,
        retailer_upload: DataUpload,
        rule_package: dict[str, Any],
        capsule_id: str,
        scenario_uploads: dict[str, DataUpload] | None = None,
        algorithm_code: str = "CONTROLLED_SETTLEMENT_V1",
    ) -> tuple[dict[str, Any], dict[str, Any], list[str], int]:
        started = time.perf_counter()
        generator_private = LocalDomainVault.read(generator_upload.data_ref)
        retailer_private = LocalDomainVault.read(retailer_upload.data_ref)
        scenario_uploads = scenario_uploads or {}

        def read_scenario(asset_type: str) -> dict[str, Any]:
            upload = scenario_uploads.get(asset_type)
            return LocalDomainVault.read(upload.data_ref) if upload else {}

        forecast_private = read_scenario("RENEWABLE_FORECAST")
        vpp_private = read_scenario("VPP_RESOURCE")
        grid_private = read_scenario("GRID_CONSTRAINT")
        compute_strategy = {
            "primary": self.code,
            "requested_algorithm": algorithm_code,
            "cross_domain_protocol": "NOT_PROVIDED",
        }
        compute_strategy["plan_hash"] = sha256_json(compute_strategy)
        logs = [
            "Participant and contract period intersection established",
            "Usage policy accepted for the selected data references",
            "Deterministic settlement calculation started in the application process",
            "Only the configured aggregate result was returned through the API",
        ]
        if settings.test_compute_delay_ms:
            time.sleep(settings.test_compute_delay_ms / 1000)

        generation = Decimal(str(generator_private["energy_mwh"]))
        retail = Decimal(str(retailer_private["energy_mwh"]))
        params = rule_package["parameters"]
        price = Decimal(str(params["contract_price"]))
        threshold = Decimal(str(params["deviation_threshold_mwh"]))
        penalty_rate = Decimal(str(params["deviation_penalty_rate"]))
        service_rate = Decimal(str(params["service_fee_rate"]))
        digits = int(params.get("rounding", 2))

        settlement_energy = min(generation, retail)
        gross_deviation = abs(generation - retail)
        response_horizon_hours = Decimal("6")
        vpp_capacity = Decimal(str(vpp_private.get("adjustable_capacity_mw", 0)))
        vpp_adjustment = min(gross_deviation, vpp_capacity * response_horizon_hours)
        deviation = max(gross_deviation - vpp_adjustment, Decimal("0"))
        max_residual = Decimal(str(grid_private.get("max_residual_imbalance_mwh", "999999")))
        n_minus_one_passed = bool(grid_private.get("n_minus_one_passed", True))
        grid_powerflow = PandapowerGridAdapter().check(
            generation_mwh=float(generation),
            retail_mwh=float(retail),
            vpp_adjustment_mwh=float(vpp_adjustment),
            deviation_mwh=float(deviation),
            grid_payload=grid_private,
        )
        grid_powerflow["input_boundary_provided"] = bool(grid_private)
        grid_check_passed = n_minus_one_passed and deviation <= max_residual and grid_powerflow["passed"]
        if not grid_check_passed:
            reasons = ", ".join(grid_powerflow.get("reasons", [])) or "GRID_CONSTRAINT_REJECTED"
            raise ValueError(f"Grid security gate rejected the settlement compute plan: {reasons}")
        base_amount = settlement_energy * price
        excess_deviation = max(deviation - threshold, Decimal("0"))
        deviation_penalty = excess_deviation * penalty_rate
        service_fee = settlement_energy * service_rate
        payable = base_amount - deviation_penalty - service_fee

        result = {
            "capsule_id": capsule_id,
            "settlement_energy_mwh": float(self._quantize(settlement_energy, 3)),
            "deviation_mwh": float(self._quantize(deviation, 3)),
            "gross_deviation_mwh": float(self._quantize(gross_deviation, 3)),
            "vpp_adjustment_mwh": float(self._quantize(vpp_adjustment, 3)),
            "base_amount_yuan": float(self._quantize(base_amount, digits)),
            "deviation_penalty_yuan": float(self._quantize(deviation_penalty, digits)),
            "service_fee_yuan": float(self._quantize(service_fee, digits)),
            "payable_amount_yuan": float(self._quantize(payable, digits)),
            "rule_hash": rule_package["rule_hash"],
            "scenario_coordination": [
                {
                    "code": "RENEWABLE_CONSUMPTION",
                    "name": "新能源消纳",
                    "status": "PASSED" if forecast_private and float(forecast_private.get("forecast_accuracy_pct", 0)) >= 85 else "REVIEW_REQUIRED" if forecast_private else "NOT_PROVIDED",
                    "metric": f"预测准确率 {float(forecast_private.get('forecast_accuracy_pct', 0)):.1f}%" if forecast_private else "未接入预测资产",
                    "artifact": scenario_uploads.get("RENEWABLE_FORECAST").commitment if scenario_uploads.get("RENEWABLE_FORECAST") else None,
                },
                {
                    "code": "MARKET_TRADING",
                    "name": "电力市场交易",
                    "status": "PASSED",
                    "metric": f"结算电量 {float(self._quantize(settlement_energy, 3)):.1f} MWh",
                    "artifact": rule_package["rule_hash"],
                },
                {
                    "code": "VPP_OPERATION",
                    "name": "虚拟电厂运营",
                    "status": "PASSED" if vpp_private else "NOT_CONNECTED",
                    "metric": f"偏差调节 {float(self._quantize(vpp_adjustment, 3)):.1f} MWh" if vpp_private else "未接入资源池",
                    "artifact": scenario_uploads.get("VPP_RESOURCE").commitment if scenario_uploads.get("VPP_RESOURCE") else None,
                },
                {
                    "code": "GRID_DISPATCH",
                    "name": "电网调度",
                    "status": "PASSED" if grid_private and grid_check_passed else "REJECTED" if grid_private else "NOT_PROVIDED",
                    "metric": f"剩余偏差 {float(self._quantize(deviation, 3)):.1f} MWh" if grid_private else "未提供调度边界",
                    "artifact": scenario_uploads.get("GRID_CONSTRAINT").commitment if scenario_uploads.get("GRID_CONSTRAINT") else None,
                },
            ],
            "grid_security": grid_powerflow,
        }
        receipt = {
            "adapter": self.code,
            "join_key": "participantId+contractId+period",
            "input_commitments": [generator_upload.commitment, retailer_upload.commitment],
            "compute_plan_hash": sha256_json(
                {"algorithm": algorithm_code, "capsule_id": capsule_id, "strategy": compute_strategy}
            ),
            "compute_strategy": compute_strategy,
            "grid_security": grid_powerflow,
            "scenario_commitments": {
                code: upload.commitment for code, upload in scenario_uploads.items()
            },
            "execution_attestation": {
                "runtime": "application-process",
                "attestation_status": "NOT_PROVIDED",
                "api_raw_records_returned": False,
                "cross_domain_non_export_verified": False,
                "deterministic_engine": "decimal-v1",
                "grid_security_gate": "PASSED" if grid_private else "NOT_RUN",
                "grid_powerflow_adapter": grid_powerflow["adapter"],
                "grid_powerflow_network": grid_powerflow["network_version"],
            },
            "output_hash": sha256_json(result),
        }
        receipt["receipt_signature"] = sign_value(receipt, "did:hiddenchain:agent:secure-settlement")
        logs.append(f"VPP adjustment applied: {float(vpp_adjustment):.3f} MWh")
        if grid_private:
            logs.extend(
                [
                    f"Pandapower: {grid_powerflow['network_version']} power-flow check passed",
                    "Grid gate: supplied N-1 flag, residual imbalance and pandapower constraints passed",
                ]
            )
        else:
            logs.append("Grid gate was not run because no dispatch boundary was provided")
        logs.append("Deterministic engine: RuleHash, precision and rounding policy applied")
        duration_ms = max(1, int((time.perf_counter() - started) * 1000))
        return result, receipt, logs, duration_ms

    def run_load_analysis(
        self,
        uploads: list[DataUpload],
        strategy: dict[str, Any] | None = None,
        *,
        privacy_level: str = "AGGREGATED",
        privacy_budget: float = 1.0,
    ) -> tuple[dict[str, Any], int]:
        started = time.perf_counter()
        curves: list[list[float]] = []
        for upload in uploads:
            payload = LocalDomainVault.read(upload.data_ref)
            curve = payload.get("load_curve")
            if isinstance(curve, list) and len(curve) == 24:
                curves.append([float(item) for item in curve])
        if not curves:
            raise ValueError("No eligible 24-hour load curves")
        aggregate = [round(sum(values), 3) for values in zip(*curves)]
        privacy_controls: dict[str, Any] = {
            "engine": "DETERMINISTIC_AGGREGATE",
            "raw_records_returned": False,
            "raw_data_exposed": False,
        }
        if privacy_level == "DIFFERENTIAL_PRIVACY":
            aggregate, privacy_controls = OpenDPAdapter.release_curve(
                curves,
                epsilon=privacy_budget,
            )
        peak = max(aggregate)
        valley = min(aggregate)
        peak_hour = aggregate.index(peak)
        valley_hour = aggregate.index(valley)
        result = {
            "sample_count": len(curves),
            "aggregate_curve": aggregate,
            "peak_load_mw": peak,
            "peak_hour": peak_hour,
            "valley_load_mw": valley,
            "valley_hour": valley_hour,
            "peak_valley_ratio": round(peak / valley, 3) if valley else None,
            "demand_response_potential_mw": round(max(peak - sum(aggregate) / 24, 0) * 0.35, 3),
            "raw_records_returned": False,
            "privacy_controls": privacy_controls,
            "compute_strategy": strategy or AdaptivePrivacyRouter.recommend(
                "VPP_AGGREGATION",
                sensitivity_level="L3",
                latency_requirement="BATCH",
                participant_count=len(curves),
            ),
        }
        return result, max(1, int((time.perf_counter() - started) * 1000))


class LocalEvidenceLedgerAdapter:
    """Append-only local evidence ledger backed by database ordering and hashes."""

    code = "LOCAL_EVIDENCE_LEDGER_V1"

    def anchor(
        self,
        db: Session,
        *,
        task_id: str | None,
        stage: str,
        biz_type: str,
        biz_id: str,
        payload: dict[str, Any],
    ) -> BlockchainEvidence:
        current_height = db.scalar(select(func.max(BlockchainEvidence.block_height))) or 0
        block_height = int(current_height) + 1
        evidence_hash = sha256_json(payload)
        tx_hash = sha256_json(
            {
                "chain": self.code,
                "height": block_height,
                "evidence_hash": evidence_hash,
                "previous_height": current_height,
            }
        )
        evidence = BlockchainEvidence(
            task_id=task_id,
            stage=stage,
            biz_type=biz_type,
            biz_id=biz_id,
            evidence_hash=evidence_hash,
            payload_json=payload,
            tx_hash=tx_hash,
            block_height=block_height,
            chain_code=self.code,
            status="CONFIRMED",
        )
        db.add(evidence)
        db.flush()
        return evidence

    @staticmethod
    def verify(evidence: BlockchainEvidence) -> dict[str, Any]:
        actual = sha256_json(evidence.payload_json)
        return {
            "evidence_id": evidence.evidence_id,
            "db_hash": evidence.evidence_hash,
            "chain_hash": actual,
            "matched": actual == evidence.evidence_hash,
            "tx_hash": evidence.tx_hash,
            "block_height": evidence.block_height,
            "chain_code": evidence.chain_code,
        }
