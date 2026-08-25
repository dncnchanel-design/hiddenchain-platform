from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    AccessRule,
    DidIdentity,
    LocalSubjectNode,
    Organization,
    PrivacyAnalysisJob,
    SettlementRule,
    SettlementTask,
    TaskParticipant,
    User,
)
from .security import hash_password, sha256_json, sign_value
from .seed import ORGS, USERS, _seed_upload
from .services.adapters import AdaptivePrivacyRouter
from .services.workflow import run_privacy_analysis, run_settlement_workflow
from .trust_models import DataAsset, DataAssetPassport, DataAssetVersion, DataSource


RESOURCE_DEFINITIONS: dict[str, list[tuple[str, str, str]]] = {
    "electricity": [
        ("generation", "发电量", "MWh"),
        ("supply", "供电量", "MWh"),
        ("load", "用电负荷", "MW"),
        ("price", "交易价格", "元/MWh"),
    ],
    "coal": [
        ("production", "煤炭产量", "吨"),
        ("supply", "煤炭供应量", "吨"),
        ("consumption", "煤炭消费量", "吨"),
        ("inventory", "煤炭库存", "吨"),
        ("transport", "煤炭运输量", "吨"),
        ("price", "煤炭价格", "元/吨"),
    ],
    "heat": [
        ("supply", "供热量", "GJ"),
        ("load", "热负荷", "MW"),
        ("fuel", "燃料消耗", "吨标准煤"),
        ("loss", "管网损耗率", "%"),
        ("supply_temperature", "供水温度", "℃"),
        ("return_temperature", "回水温度", "℃"),
        ("price", "供热价格", "元/GJ"),
    ],
    "gas": [
        ("supply", "天然气供应量", "万立方米"),
        ("consumption", "天然气消费量", "万立方米"),
        ("storage", "天然气储量", "万立方米"),
        ("pipeline_flow", "管道流量", "万立方米/日"),
        ("pressure", "管网压力", "MPa"),
        ("price", "天然气价格", "元/立方米"),
    ],
    "oil": [
        ("production", "石油产量", "吨"),
        ("refining", "石油炼化量", "吨"),
        ("inventory", "石油库存", "吨"),
        ("transport", "石油运输量", "吨"),
        ("sales", "石油销售量", "吨"),
        ("price", "石油价格", "元/吨"),
    ],
}

OWNER_BY_DOMAIN = {
    "coal": "org-coal-t01",
    "heat": "org-heat-t01",
    "gas": "org-gas-t01",
    "oil": "org-oil-t01",
}

DEMO_BUSINESS_TASK_ID = "task-demo-business-e2e"
DEMO_BUSINESS_BATCH = "DEMO-2026-08-E2E"


def seed_demo_business(db: Session) -> None:
    """Seed one explicit synthetic scenario and execute the real demo workflow."""

    task = db.get(SettlementTask, DEMO_BUSINESS_TASK_ID)
    if task is None:
        rule_parameters = {
            "contract_price": 420.0,
            "deviation_threshold_mwh": 100.0,
            "deviation_penalty_rate": 150.0,
            "service_fee_rate": 3.2,
            "rounding": 2,
        }
        formula = (
            "PAYABLE = MIN(GENERATION, RETAIL) * PRICE - "
            "MAX(ABS(GENERATION-RETAIL)-THRESHOLD,0) * PENALTY_RATE - "
            "SETTLEMENT_ENERGY * SERVICE_FEE_RATE"
        )
        rule_payload = {
            "formula": formula,
            "parameters": rule_parameters,
            "version": "DEMO-SETTLE-2026-08-001",
        }
        rule = db.get(SettlementRule, "rule-demo-business-v1")
        if rule is None:
            rule = SettlementRule(
                rule_id="rule-demo-business-v1",
                rule_name="演示场景可信结算规则",
                rule_version="DEMO-SETTLE-2026-08-001",
                description="仅用于公开演示的合成数据结算规则，不代表生产业务数据。",
                source_refs_json=["DEMO_SYNTHETIC_SETTLEMENT_RULE"],
                formula_dsl=formula,
                parameters_json=rule_parameters,
                policy_refs_json=["policy:settlement-purpose", "policy:no-raw-data-export"],
                approver_signatures_json=[
                    {
                        "did": "did:hiddenchain:org:org-exchange-t01",
                        "signature": sign_value(
                            rule_payload,
                            "did:hiddenchain:org:org-exchange-t01",
                        ),
                    }
                ],
                rule_hash=sha256_json(rule_payload),
                status="ACTIVE",
            )
            db.add(rule)
            db.flush()

        uploads = [
            _seed_upload(
                db,
                upload_id="upload-demo-generation-e2e",
                asset_type="GENERATION_DATA",
                owner_org_id="org-generator-t01",
                label="演示合成发电承诺（不含外部企业原始数据）",
                trade_batch_no=DEMO_BUSINESS_BATCH,
                payload={
                    "period": "2026-08",
                    "record_count": 31,
                    "energy_mwh": 12500.0,
                    "synthetic_data_only": True,
                },
            ),
            _seed_upload(
                db,
                upload_id="upload-demo-retail-e2e",
                asset_type="RETAIL_DATA",
                owner_org_id="org-retailer-t01",
                label="演示合成售电承诺（不含外部企业原始数据）",
                trade_batch_no=DEMO_BUSINESS_BATCH,
                payload={
                    "period": "2026-08",
                    "record_count": 31,
                    "energy_mwh": 12320.0,
                    "synthetic_data_only": True,
                },
            ),
            _seed_upload(
                db,
                upload_id="upload-demo-forecast-e2e",
                asset_type="RENEWABLE_FORECAST",
                owner_org_id="org-generator-t01",
                label="演示合成新能源预测（不含外部企业原始数据）",
                trade_batch_no=DEMO_BUSINESS_BATCH,
                payload={
                    "period": "2026-08",
                    "record_count": 31,
                    "forecast_energy_mwh": 12840.0,
                    "forecast_accuracy_pct": 92.6,
                    "synthetic_data_only": True,
                },
            ),
            _seed_upload(
                db,
                upload_id="upload-demo-vpp-e2e",
                asset_type="VPP_RESOURCE",
                owner_org_id="org-retailer-t01",
                label="演示合成虚拟电厂资源（不含外部企业原始数据）",
                trade_batch_no=DEMO_BUSINESS_BATCH,
                payload={
                    "period": "2026-08",
                    "record_count": 31,
                    "adjustable_capacity_mw": 18.6,
                    "storage_energy_mwh": 42.0,
                    "response_minutes": 5,
                    "synthetic_data_only": True,
                },
            ),
            _seed_upload(
                db,
                upload_id="upload-demo-grid-e2e",
                asset_type="GRID_CONSTRAINT",
                owner_org_id="org-exchange-t01",
                label="演示合成调度安全边界（不含外部企业原始数据）",
                trade_batch_no=DEMO_BUSINESS_BATCH,
                payload={
                    "period": "2026-08",
                    "record_count": 24,
                    "n_minus_one_passed": True,
                    "max_residual_imbalance_mwh": 90.0,
                    "congestion_margin_pct": 14.2,
                    "synthetic_data_only": True,
                },
            ),
            _seed_upload(
                db,
                upload_id="upload-demo-load-a-e2e",
                asset_type="USER_LOAD_CURVE",
                owner_org_id="org-retailer-t01",
                label="演示合成用户负荷曲线 A（不含外部企业原始数据）",
                trade_batch_no=DEMO_BUSINESS_BATCH,
                payload={
                    "period": "2026-08-18",
                    "record_count": 240,
                    "load_curve": [32, 30, 28, 27, 29, 35, 45, 58, 66, 72, 76, 79, 77, 74, 72, 75, 83, 91, 96, 90, 78, 62, 48, 38],
                    "synthetic_data_only": True,
                },
            ),
            _seed_upload(
                db,
                upload_id="upload-demo-load-b-e2e",
                asset_type="USER_LOAD_CURVE",
                owner_org_id="org-retailer-t01",
                label="演示合成用户负荷曲线 B（不含外部企业原始数据）",
                trade_batch_no=DEMO_BUSINESS_BATCH,
                payload={
                    "period": "2026-08-18",
                    "record_count": 180,
                    "load_curve": [22, 21, 20, 20, 22, 28, 38, 47, 54, 61, 65, 68, 67, 65, 64, 68, 75, 82, 88, 84, 72, 55, 40, 29],
                    "synthetic_data_only": True,
                },
            ),
        ]
        task = SettlementTask(
            task_id=DEMO_BUSINESS_TASK_ID,
            capsule_id="HC-CAPSULE-DEMO-202608-E2E",
            task_name="公开演示：2026年8月可信结算闭环",
            trade_batch_no=DEMO_BUSINESS_BATCH,
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
            rule_id=rule.rule_id,
            creator_org_id="org-exchange-t01",
            status="DRAFT",
            current_stage="任务创建",
            verification_profile_json={
                "scenario_code": "MARKET_SETTLEMENT",
                "business_description": "合成数据闭环演示；不代表外部企业生产数据已接入。",
                "compute_mode": "LOCAL_CONTROLLED",
                "algorithm_code": "CONTROLLED_SETTLEMENT_V1",
                "output_mode": "AGGREGATE_ONLY",
                "is_simulated": True,
            },
        )
        db.add(task)
        db.flush()
        db.add_all(
            [
                TaskParticipant(
                    task_id=task.task_id,
                    org_id="org-generator-t01",
                    role_in_task="GENERATOR",
                    data_status="READY",
                    confirm_status="PENDING",
                ),
                TaskParticipant(
                    task_id=task.task_id,
                    org_id="org-retailer-t01",
                    role_in_task="RETAILER",
                    data_status="READY",
                    confirm_status="PENDING",
                ),
            ]
        )
        for upload in uploads:
            upload.task_id = task.task_id
        db.commit()

    if task.status not in {"PENDING_CONFIRMATION", "PARTIALLY_CONFIRMED", "AUDITED"}:
        run_settlement_workflow(db, task_id=task.task_id, actor=None)

    if not db.scalar(
        select(PrivacyAnalysisJob.analysis_id).where(
            PrivacyAnalysisJob.analysis_name == "公开演示：两方负荷隐私分析"
        )
    ):
        dataset_ids = [
            "upload-demo-load-a-e2e",
            "upload-demo-load-b-e2e",
        ]
        analysis = PrivacyAnalysisJob(
            analysis_name="公开演示：两方负荷隐私分析",
            analysis_type="PEAK_VALLEY",
            dataset_ids_json=dataset_ids,
            privacy_level="DIFFERENTIAL_PRIVACY",
            privacy_budget=1.0,
            purpose="VPP_AGGREGATION",
            output_json={
                "recommended_strategy": AdaptivePrivacyRouter.recommend(
                    "VPP_AGGREGATION",
                    sensitivity_level="L4",
                    latency_requirement="MINUTE",
                    participant_count=2,
                )
            },
            status="RUNNING",
        )
        db.add(analysis)
        db.flush()
        run_privacy_analysis(db, analysis)


def _connector_public_keys() -> dict[str, str]:
    try:
        value = json.loads(settings.connector_public_keys_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _electricity_owner(resource: str) -> str:
    if resource == "generation":
        return "org-generator-t01"
    if resource == "price":
        return "org-exchange-t01"
    return "org-retailer-t01"


def _seed_participants(db: Session) -> None:
    public_keys = _connector_public_keys()
    for org_id, org_type, energy_domain, org_name, credit_code in ORGS:
        db.add(
            Organization(
                org_id=org_id,
                org_type=org_type,
                org_name=org_name,
                credit_code=credit_code,
                energy_domain=energy_domain,
                profile_json={
                    "demo": True,
                    "verified": True,
                    "responsible_person": "演示负责人",
                },
                status="ACTIVE",
            )
        )
        db.flush()
        public_key = public_keys.get(org_id, public_keys.get(energy_domain or "", ""))
        db.add(
            DidIdentity(
                did_id=f"did:hiddenchain:org:{org_id}",
                owner_type="ORG",
                owner_id=org_id,
                org_id=org_id,
                public_key_fingerprint=sha256_json(public_key or {"org_id": org_id, "demo": True}),
                chain_address=None,
                credential_status="VALID",
                credential_json={
                    "type": ["VerifiableCredential", "EnterpriseParticipantCredential"],
                    "issuer": "did:hiddenchain:demo:registrar",
                    "credentialSubject": {
                        "id": f"did:hiddenchain:org:{org_id}",
                        "orgType": org_type,
                        "energyDomain": energy_domain,
                    },
                },
            )
        )
    for user_id, org_id, username, password, display_name, role, permissions in USERS:
        db.add(
            User(
                user_id=user_id,
                org_id=org_id,
                username=username,
                password_hash=hash_password(password),
                display_name=display_name,
                role_code=role,
                permissions_json=list(permissions),
                is_org_owner=True,
                status="ACTIVE",
            )
        )
    db.flush()
    for org_id, org_type, _energy_domain, _org_name, _credit_code in ORGS:
        if org_type not in {"GENERATOR", "RETAILER", "COAL_ENTERPRISE", "HEAT_ENTERPRISE", "GAS_ENTERPRISE", "OIL_ENTERPRISE", "EXCHANGE"}:
            continue
        db.add(
            LocalSubjectNode(
                org_id=org_id,
                node_code=f"local-node-{org_id}",
                environment="DEMO_ADAPTER",
                status="ACTIVE",
                metadata_json={"raw_data_location": "subject_internal_server", "synthetic_data_only": True},
            )
        )
    db.add(
        AccessRule(
            owner_org_id="org-generator-t01",
            rule_code="GENERATION_DAILY_STATS",
            version_no=1,
            energy_domain="electricity",
            resource_id="generation",
            function_code="average",
            mode="AUTO_CALL",
            scope_json={"granularity": "DAY", "output_mode": "AGGREGATE_ONLY"},
            limits_json={"minimum_record_count": 3, "max_duration_days": 31, "granularity": "DAY", "output_mode": "AGGREGATE_ONLY"},
            status="ACTIVE",
            rule_hash=sha256_json({"owner_org_id": "org-generator-t01", "resource_id": "generation", "function_code": "average", "version_no": 1}),
            approved_by_user_id="user-generator",
        )
    )
    db.flush()


def _seed_catalog(db: Session) -> None:
    sources: dict[tuple[str, str], DataSource] = {}
    for domain, definitions in RESOURCE_DEFINITIONS.items():
        for resource, chinese_name, unit in definitions:
            owner_org_id = _electricity_owner(resource) if domain == "electricity" else OWNER_BY_DOMAIN[domain]
            source_key = (domain, owner_org_id)
            source = sources.get(source_key)
            if source is None:
                source = DataSource(
                    source_id=f"source-{domain}-{owner_org_id}",
                    source_code=f"DEMO-{domain.upper()}-{owner_org_id.upper()}",
                    source_name=f"{chinese_name}企业侧数据连接",
                    owner_org_id=owner_org_id,
                    source_type="ENTERPRISE_CONNECTOR",
                    connector_type="TRUSTED_DATA_SPACE_CONNECTOR",
                    endpoint_ref=f"connector://{owner_org_id}",
                    security_domain=domain,
                    capability_label="LOCAL_REAL",
                    status="ACTIVE",
                    metadata_json={
                        "demo": True,
                        "raw_data_centrally_stored": False,
                        "deployment": "isolated_enterprise_connector",
                    },
                )
                db.add(source)
                db.flush()
                sources[source_key] = source
            asset_id = f"asset-{domain}-{resource}"
            version_id = f"version-{domain}-{resource}-1"
            schema = {
                "fields": ["日期", "地区", "机构", chinese_name, "单位"],
                "granularity": "日度",
                "hourly_available": domain in {"electricity", "heat", "gas"} and resource in {"load", "supply"},
                "period_start": date(2025, 9, 1).isoformat(),
                "period_end": date(2026, 8, 31).isoformat(),
            }
            asset = DataAsset(
                asset_id=asset_id,
                source_id=source.source_id,
                owner_org_id=owner_org_id,
                asset_code=f"{domain.upper()}_{resource.upper()}",
                asset_name=chinese_name,
                asset_type=f"{domain.upper()}_METRIC",
                classification="ENTERPRISE_DATA_PRODUCT",
                sensitivity_level="L2" if resource not in {"price", "pressure"} else "L3",
                current_version_id=version_id,
                status="ACTIVE",
                metadata_json={
                    "domain": domain,
                    "resource_id": resource,
                    "unit": unit,
                    "raw_data_centrally_stored": False,
                    "publication_status": "目录已发布",
                    "chinese_name_complete": True,
                },
            )
            data_hash = sha256_json({"connector": owner_org_id, "domain": domain, "resource": resource, "schema": schema})
            version = DataAssetVersion(
                version_id=version_id,
                asset_id=asset_id,
                version_no=1,
                schema_version="2026.08",
                schema_json=schema,
                data_ref=f"connector://{owner_org_id}/{resource}",
                data_hash=data_hash,
                commitment=sha256_json({"data_hash": data_hash, "owner": owner_org_id}),
                record_count=1460,
                effective_from=datetime(2025, 9, 1),
                effective_until=datetime(2026, 8, 31, 23, 59, 59),
                immutable_hash=sha256_json({"asset": asset_id, "version": 1, "data_hash": data_hash}),
                status="ACTIVE",
            )
            passport = DataAssetPassport(
                passport_id=f"passport-{domain}-{resource}-1",
                asset_version_id=version_id,
                passport_version=1,
                owner_did=f"did:hiddenchain:org:{owner_org_id}",
                provenance_json={"source": "企业侧连接器", "raw_data_centrally_stored": False},
                classification_json={"level": asset.sensitivity_level},
                permitted_use_json={
                    "actions": ["允许查看", "汇总后查看", "延迟后查看", "仅参与计算、不提供明细", "禁止查看"],
                    "default_action": "仅参与计算、不提供明细",
                    "fixed_functions_only": True,
                    "raw_data_export": False,
                    "duration_policy": {"min_days": 1, "max_days": 180, "default_days": 30},
                },
                policy_refs_json=[f"enterprise-policy:{owner_org_id}"],
                evidence_refs_json=[],
                passport_hash=sha256_json({"asset": asset_id, "owner": owner_org_id, "schema": schema}),
                status="ACTIVE",
            )
            db.add(asset)
            db.flush()
            db.add(version)
            db.flush()
            db.add(passport)
    db.flush()


def seed_demo_catalog(db: Session) -> None:
    if db.scalar(select(Organization.org_id).limit(1)):
        return
    _seed_participants(db)
    _seed_catalog(db)
    db.commit()
