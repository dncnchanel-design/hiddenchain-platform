from __future__ import annotations

import time
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

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
        "tools": ["PSIAdapter", "MPCAdapter", "VPPResourceAdapter", "DeterministicEngine"],
        "input": "DataPermit、RulePackage、可调资源承诺",
        "output": "响应计划、ComputeReceipt、SettlementResult",
        "scenario_code": "VPP_OPERATION",
        "business_mandate": "在不暴露单户负荷的前提下聚合可调能力并修正交易偏差。",
    },
    {
        "code": "AUDIT_RISK",
        "name": "电网调度与监管Agent",
        "did": "did:hiddenchain:agent:audit-risk",
        "tools": ["GridBoundaryAdapter", "SecurityGate", "EvidenceGraph", "FISCOAdapter", "RiskRuleEngine"],
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


class MockDidAdapter:
    code = "MOCK_WEIDENTITY"

    @staticmethod
    def verify_owner(db: Session, owner_id: str) -> dict[str, Any]:
        did = db.scalar(select(DidIdentity).where(DidIdentity.owner_id == owner_id))
        if did is None or did.credential_status != "VALID":
            raise ValueError(f"DID/VC verification failed for {owner_id}")
        return {
            "did": did.did_id,
            "credential_status": did.credential_status,
            "fingerprint": did.public_key_fingerprint,
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


class MockDataSpaceAdapter:
    code = "MOCK_EDC_ODRL_OPA"

    @staticmethod
    def create_contract(
        db: Session,
        task: SettlementTask,
        provider: Organization,
        uploads: list[DataUpload],
        purpose: str = "POWER_SETTLEMENT",
        consumer_org_id: str = "org-exchange-demo",
        algorithm_code: str = "SETTLEMENT_MPC_V1",
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
                "execution_environment": "AUTHORIZED_COMPUTE_SANDBOX",
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
        algorithm_code: str = "SETTLEMENT_MPC_V1",
        execution_environment: str = "AUTHORIZED_COMPUTE_SANDBOX",
        output_mode: str = "AGGREGATE_ONLY",
        raw_data_export: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        constraints = contract.policy_json.get("constraint", {})
        now = now or utc_now()
        reasons: list[str] = []
        if contract.status != "ACTIVE":
            reasons.append("CONTRACT_NOT_ACTIVE")
        if contract.purpose != requested_purpose:
            reasons.append("PURPOSE_MISMATCH")
        if constraints.get("capsule_id") != capsule_id:
            reasons.append("CAPSULE_MISMATCH")
        expected_consumer = constraints.get("consumer_did")
        if expected_consumer and consumer_did is not None and expected_consumer != consumer_did:
            reasons.append("CONSUMER_MISMATCH")
        allowed_algorithms = constraints.get("algorithm_codes") or [algorithm_code]
        if algorithm_code not in allowed_algorithms:
            reasons.append("ALGORITHM_NOT_ALLOWED")
        expected_environment = constraints.get("execution_environment")
        if expected_environment and execution_environment != expected_environment:
            reasons.append("EXECUTION_ENVIRONMENT_NOT_ALLOWED")
        expected_output_mode = constraints.get("output_mode")
        if expected_output_mode and output_mode != expected_output_mode:
            reasons.append("OUTPUT_MODE_NOT_ALLOWED")
        if raw_data_export or constraints.get("raw_data_export") is not False:
            reasons.append("RAW_DATA_EXPORT_NOT_ALLOWED")
        valid_from = _parse_dt(constraints.get("valid_from"))
        expires_at = _parse_dt(constraints.get("expires_at"))
        if valid_from and now < valid_from:
            reasons.append("CONTRACT_NOT_YET_VALID")
        if expires_at and now >= expires_at:
            reasons.append("CONTRACT_EXPIRED")
        allowed = not reasons
        return {
            "decision": "PERMIT" if allowed else "DENY",
            "policy_hash": contract.policy_hash,
            "purpose": requested_purpose,
            "consumer_did": consumer_did or expected_consumer,
            "algorithm_code": algorithm_code,
            "execution_environment": execution_environment,
            "output_mode": output_mode,
            "reasons": reasons,
            "obligations": contract.policy_json.get("obligation", []),
        }


class DataSpaceConnectorAdapter:
    """A small, testable connector boundary aligned with the dataspace papers.

    It intentionally keeps the current local Vault and mock compute runtime,
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
            "usage": {
                "allowed_purposes": [spec.get("default_purpose", "POWER_SETTLEMENT")],
                "output_mode": "AGGREGATE_ONLY",
                "raw_data_export": False,
            },
            "raw_data_exposed": False,
            "transport": {
                "protocol": upload.ingress_json.get("protocol", "HTTPS"),
                "protocols": DataSpaceConnectorAdapter.transport_protocols,
                "source_layer": upload.ingress_json.get("stage", "EDGE"),
                "encryption": upload.ingress_json.get("encryption", "TLS1.3"),
                "attestation": upload.ingress_json.get("attestation", "虚拟仿真来源证明"),
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
        provider_proof = MockDidAdapter.verify_owner(db, provider_org_id)
        consumer_proof = MockDidAdapter.verify_owner(db, consumer_org_id)
        decision = MockDataSpaceAdapter.evaluate(
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
        execution_environment: str = "AUTHORIZED_COMPUTE_SANDBOX",
        output_mode: str = "AGGREGATE_ONLY",
        raw_data_export: bool = False,
        consume: bool = False,
    ) -> dict[str, Any]:
        contract = db.get(DataContract, agreement.contract_id)
        if contract is None:
            return {"decision": "DENY", "reasons": ["CONTRACT_NOT_FOUND"]}
        decision = MockDataSpaceAdapter.evaluate(
            contract,
            purpose,
            contract.policy_json.get("constraint", {}).get("capsule_id", ""),
            consumer_did=agreement.consumer_did,
            algorithm_code=algorithm_code,
            execution_environment=execution_environment,
            output_mode=output_mode,
            raw_data_export=raw_data_export,
        )
        if agreement.state not in {"NEGOTIATED", "ACTIVE"}:
            decision["decision"] = "DENY"
            decision.setdefault("reasons", []).append("AGREEMENT_NOT_ACTIVE")
        if agreement.use_count >= agreement.max_uses:
            decision["decision"] = "DENY"
            decision.setdefault("reasons", []).append("USE_LIMIT_REACHED")
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
            "raw_data_exported": receipt.get("execution_attestation", {}).get("raw_data_exported", False),
            "recorded_at": utc_now().isoformat(),
        }


class RulePackageAdapter:
    code = "RAG_DSL_OPA_MVP"

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
            "reason": "先对齐交易关系，再对敏感电量和价格中间量执行多方安全计算。",
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
            "reason": "在低时延可信执行环境内使用调度边界完成安全约束校核。",
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
            reasons.append("实时任务优先进入TEE，原策略作为域内受控工具运行。")
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


class MockPrivacyComputeAdapter:
    code = "MOCK_SECRET_FLOW"

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
        algorithm_code: str = "SETTLEMENT_MPC_V1",
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
        compute_strategy = AdaptivePrivacyRouter.recommend(
            "MARKET_SETTLEMENT",
            sensitivity_level="L4",
            latency_requirement="BATCH",
            participant_count=2,
        )
        logs = [
            "PSI: participantId + contractId + period intersection established",
            f"StrategyRouter: {compute_strategy['primary']} selected for MARKET_SETTLEMENT",
            "MPC: additive secret-sharing simulation started",
            "MPC: only authorized aggregates released to deterministic engine",
        ]
        if settings.mock_delay_ms:
            time.sleep(settings.mock_delay_ms / 1000)

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
        grid_check_passed = n_minus_one_passed and deviation <= max_residual
        if not grid_check_passed:
            raise ValueError("Grid security gate rejected the settlement compute plan")
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
                    "status": "PASSED" if float(forecast_private.get("forecast_accuracy_pct", 100)) >= 85 else "REVIEW",
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
                    "status": "PASSED" if grid_check_passed else "REJECTED",
                    "metric": f"剩余偏差 {float(self._quantize(deviation, 3)):.1f} MWh",
                    "artifact": scenario_uploads.get("GRID_CONSTRAINT").commitment if scenario_uploads.get("GRID_CONSTRAINT") else None,
                },
            ],
        }
        receipt = {
            "adapter": self.code,
            "psi_key": "participantId+contractId+period",
            "input_commitments": [generator_upload.commitment, retailer_upload.commitment],
            "compute_plan_hash": sha256_json(
                {"algorithm": algorithm_code, "capsule_id": capsule_id, "strategy": compute_strategy}
            ),
            "compute_strategy": compute_strategy,
            "scenario_commitments": {
                code: upload.commitment for code, upload in scenario_uploads.items()
            },
            "execution_attestation": {
                "runtime": "isolated-multi-party-mock",
                "raw_data_exported": False,
                "deterministic_engine": "decimal-v1",
                "grid_security_gate": "PASSED",
            },
            "output_hash": sha256_json(result),
        }
        receipt["receipt_signature"] = sign_value(receipt, "did:hiddenchain:agent:secure-settlement")
        logs.extend(
            [
                f"VPP: {float(vpp_adjustment):.3f} MWh flexibility applied inside secure sandbox",
                "Grid gate: N-1 flag and residual imbalance constraint passed",
                "Deterministic engine: RuleHash, precision and rounding policy applied",
            ]
        )
        duration_ms = max(1, int((time.perf_counter() - started) * 1000))
        return result, receipt, logs, duration_ms

    def run_load_analysis(
        self,
        uploads: list[DataUpload],
        strategy: dict[str, Any] | None = None,
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
            "compute_strategy": strategy or AdaptivePrivacyRouter.recommend(
                "VPP_AGGREGATION",
                sensitivity_level="L3",
                latency_requirement="BATCH",
                participant_count=len(curves),
            ),
        }
        return result, max(1, int((time.perf_counter() - started) * 1000))


class MockBlockchainAdapter:
    code = "MOCK_FISCO_BCOS"

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
