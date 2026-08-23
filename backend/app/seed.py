from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    DataUpload,
    DidIdentity,
    Organization,
    SettlementRule,
    SettlementTask,
    Signature,
    TaskParticipant,
    User,
)
from .security import hash_password, sha256_json, sign_value
from .services.adapters import AGENT_DEFINITIONS
from .services.vault import LocalDomainVault
from .services.workflow import run_settlement_workflow
from .services.tool_catalog import ensure_agent_tool_catalog
from .services.asset_registry import project_upload_to_asset_registry


BUSINESS_OWNER_PERMISSIONS = [
    "MANAGE_CATALOG",
    "MANAGE_CONNECTOR",
    "MANAGE_PUBLICATION_POLICY",
    "APPROVE_AUTHORIZATION",
    "CREATE_COMPUTE_TASK",
    "VIEW_COMPUTE_RESULT",
    "VIEW_AUDIT",
    "MANAGE_MEMBERS",
]

ORGS = [
    ("org-generator-t01", "GENERATOR", "electricity", "齐鲁新能源发电有限公司", "91370000GEN001"),
    ("org-retailer-t01", "RETAILER", "electricity", "海岱售电服务有限公司", "91370000RET001"),
    ("org-coal-t01", "COAL_ENTERPRISE", "coal", "山岳煤炭供应有限公司", "91370000COA001"),
    ("org-heat-t01", "HEAT_ENTERPRISE", "heat", "暖城热能服务有限公司", "91370000HEA001"),
    ("org-gas-t01", "GAS_ENTERPRISE", "gas", "清源天然气有限公司", "91370000GAS001"),
    ("org-oil-t01", "OIL_ENTERPRISE", "oil", "海陆石油供应有限公司", "91370000OIL001"),
    ("org-exchange-t01", "EXCHANGE", "electricity", "区域电力交易中心", "91370000EXC001"),
    ("org-exchange-coal-t01", "EXCHANGE", "coal", "区域煤炭交易中心", "91370000EXC002"),
    ("org-exchange-heat-t01", "EXCHANGE", "heat", "区域热能交易中心", "91370000EXC003"),
    ("org-exchange-gas-t01", "EXCHANGE", "gas", "区域天然气交易中心", "91370000EXC004"),
    ("org-exchange-oil-t01", "EXCHANGE", "oil", "区域石油交易中心", "91370000EXC005"),
    ("org-regulator-t01", "REGULATOR", None, "区域能源监管机构", "91370000REG001"),
    ("org-admin-t01", "ADMIN", None, "隐链明算平台运维组织", "91370000ADM001"),
]

USERS = [
    ("user-generator", "org-generator-t01", "generator", "generator123", "发电企业账户", "GENERATOR", BUSINESS_OWNER_PERMISSIONS),
    ("user-retailer", "org-retailer-t01", "retailer", "retailer123", "售电企业账户", "RETAILER", BUSINESS_OWNER_PERMISSIONS),
    ("user-coal", "org-coal-t01", "coal", "coal123", "煤炭企业账户", "COAL_ENTERPRISE", BUSINESS_OWNER_PERMISSIONS),
    ("user-heat", "org-heat-t01", "heat", "heat123", "热能企业账户", "HEAT_ENTERPRISE", BUSINESS_OWNER_PERMISSIONS),
    ("user-gas", "org-gas-t01", "gas", "gas123", "天然气企业账户", "GAS_ENTERPRISE", BUSINESS_OWNER_PERMISSIONS),
    ("user-oil", "org-oil-t01", "oil", "oil123", "石油企业账户", "OIL_ENTERPRISE", BUSINESS_OWNER_PERMISSIONS),
    ("user-exchange", "org-exchange-t01", "exchange", "exchange123", "交易中心账户", "EXCHANGE", BUSINESS_OWNER_PERMISSIONS),
    ("user-exchange-coal", "org-exchange-coal-t01", "exchange_coal", "exchange123", "交易中心账户", "EXCHANGE", BUSINESS_OWNER_PERMISSIONS),
    ("user-exchange-heat", "org-exchange-heat-t01", "exchange_heat", "exchange123", "交易中心账户", "EXCHANGE", BUSINESS_OWNER_PERMISSIONS),
    ("user-exchange-gas", "org-exchange-gas-t01", "exchange_gas", "exchange123", "交易中心账户", "EXCHANGE", BUSINESS_OWNER_PERMISSIONS),
    ("user-exchange-oil", "org-exchange-oil-t01", "exchange_oil", "exchange123", "交易中心账户", "EXCHANGE", BUSINESS_OWNER_PERMISSIONS),
    ("user-regulator", "org-regulator-t01", "regulator", "regulator123", "监管方账户", "REGULATOR", ["CREATE_CROSS_ENERGY_QUERY", "CREATE_COMPUTE_TASK", "VIEW_COMPUTE_RESULT", "VIEW_AUDIT"]),
    ("user-admin", "org-admin-t01", "admin", "admin123", "平台运维账户", "ADMIN", ["MANAGE_PLATFORM_OPERATIONS"]),
]


def _seed_upload(
    db: Session,
    *,
    upload_id: str,
    asset_type: str,
    owner_org_id: str,
    label: str,
    payload: dict,
    trade_batch_no: str = "TB-2026-06-001",
) -> DataUpload:
    data_ref, data_hash, commitment = LocalDomainVault.write(owner_org_id, upload_id, payload)
    signer_did = f"did:hiddenchain:org:{owner_org_id}"
    signature_value = sign_value({"data_hash": data_hash}, signer_did)
    upload = DataUpload(
        upload_id=upload_id,
        asset_type=asset_type,
        owner_org_id=owner_org_id,
        trade_batch_no=trade_batch_no,
        label=label,
        data_ref=data_ref,
        data_hash=data_hash,
        commitment=commitment,
        schema_version="v1.0",
        validation_status="PASSED",
        signature_value=signature_value,
        ingress_json={
            "source_type": "SIMULATION_EDGE_GATEWAY",
            "protocol": "HTTPS",
            "stage": "EDGE",
            "encryption": "TLS1.3",
            "attestation": "虚拟仿真采集源证明",
        },
        summary_json={
            "record_count": payload.get("record_count", 1),
            "period": payload.get("period", "2026-06"),
            "raw_data_stored_in_business_db": False,
            "trusted_acquisition": True,
            "secure_transport": {"protocol": "HTTPS", "encryption": "TLS1.3"},
        },
    )
    db.add(upload)
    db.add(
        Signature(
            signer_org_id=owner_org_id,
            signer_did=signer_did,
            target_type="DATA_UPLOAD",
            target_id=upload_id,
            target_hash=data_hash,
            signature_value=signature_value,
            verify_status="VALID",
        )
    )
    db.flush()
    project_upload_to_asset_registry(db, upload)
    return upload


def seed_test_fixtures(db: Session) -> None:
    if db.scalar(select(Organization.org_id).limit(1)):
        return

    for org_id, org_type, energy_domain, org_name, credit_code in ORGS:
        db.add(
            Organization(
                org_id=org_id,
                org_type=org_type,
                org_name=org_name,
                credit_code=credit_code,
                energy_domain=energy_domain,
                profile_json={"demo": True, "verified": True},
                status="ACTIVE",
            )
        )
        # Explicit ordering is required when SQLite foreign-key enforcement is
        # enabled because these models intentionally have no ORM relationship.
        db.flush()
        credential = {
            "type": ["VerifiableCredential", "EnergyMarketParticipantCredential"],
            "issuer": "did:hiddenchain:regulator:test",
            "credentialSubject": {"id": f"did:hiddenchain:org:{org_id}", "orgType": org_type},
        }
        db.add(
            DidIdentity(
                did_id=f"did:hiddenchain:org:{org_id}",
                owner_type="ORG",
                owner_id=org_id,
                org_id=org_id,
                public_key_fingerprint=sha256_json({"org_id": org_id, "key": "test-public-key"}),
                chain_address=f"0x{sha256_json(org_id)[:40]}",
                credential_status="VALID",
                credential_json=credential,
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

    for definition in AGENT_DEFINITIONS:
        db.add(
            DidIdentity(
                did_id=definition["did"],
                owner_type="AGENT",
                owner_id=definition["code"],
                org_id="org-exchange-t01",
                public_key_fingerprint=sha256_json({"agent": definition["code"], "tools": definition["tools"]}),
                chain_address=f"0x{sha256_json(definition['did'])[:40]}",
                credential_status="VALID",
                credential_json={
                    "type": ["VerifiableCredential", "AgentCapabilityCredential"],
                    "capabilities": definition["tools"],
                    "toolAllowlist": definition["tools"],
                },
            )
        )

    db.flush()
    ensure_agent_tool_catalog(db)

    rule_parameters = {
        "contract_price": 420.0,
        "deviation_threshold_mwh": 100.0,
        "deviation_penalty_rate": 150.0,
        "service_fee_rate": 3.2,
        "rounding": 2,
    }
    formula = "PAYABLE = MIN(GENERATION, RETAIL) * PRICE - MAX(ABS(GENERATION-RETAIL)-THRESHOLD,0) * PENALTY_RATE - SETTLEMENT_ENERGY * SERVICE_FEE_RATE"
    rule_payload = {"formula": formula, "parameters": rule_parameters, "version": "SETTLE-2026-001"}
    db.add(
        SettlementRule(
            rule_id="rule-settlement-v1",
            rule_name="山东能源场景可信验证规则",
            rule_version="SETTLE-2026-001",
            description="用于自动化验收的确定性测试规则；所有参数均为非生产夹具数据。",
            source_refs_json=["测试规则库-月度结算条款-01"],
            formula_dsl=formula,
            parameters_json=rule_parameters,
            policy_refs_json=["policy:settlement-purpose", "policy:no-raw-data-export"],
            approver_signatures_json=[
                {
                    "did": "did:hiddenchain:org:org-exchange-t01",
                    "signature": sign_value(rule_payload, "did:hiddenchain:org:org-exchange-t01"),
                }
            ],
            rule_hash=sha256_json(rule_payload),
            status="ACTIVE",
        )
    )

    _seed_upload(
        db,
        upload_id="upload-generation-t01",
        asset_type="GENERATION_DATA",
        owner_org_id="org-generator-t01",
        label="2026年6月发电侧计量数据",
        payload={
            "contract_id": "CONTRACT-2026-Q2",
            "period": "2026-06",
            "energy_mwh": 12500.0,
            "record_count": 30,
            "meter_point": "GEN-METER-A-001",
        },
    )
    _seed_upload(
        db,
        upload_id="upload-retail-t01",
        asset_type="RETAIL_DATA",
        owner_org_id="org-retailer-t01",
        label="2026年6月售电侧履约数据",
        payload={
            "contract_id": "CONTRACT-2026-Q2",
            "period": "2026-06",
            "energy_mwh": 12320.0,
            "record_count": 1200,
            "customer_group": "MASKED-GROUP-01",
        },
    )
    _seed_upload(
        db,
        upload_id="upload-load-curve-a",
        asset_type="USER_LOAD_CURVE",
        owner_org_id="org-retailer-t01",
        label="园区用户群A脱敏负荷曲线",
        payload={
            "period": "2026-06-18",
            "record_count": 240,
            "load_curve": [32, 30, 28, 27, 29, 35, 45, 58, 66, 72, 76, 79, 77, 74, 72, 75, 83, 91, 96, 90, 78, 62, 48, 38],
        },
    )
    _seed_upload(
        db,
        upload_id="upload-load-curve-b",
        asset_type="USER_LOAD_CURVE",
        owner_org_id="org-retailer-t01",
        label="园区用户群B脱敏负荷曲线",
        payload={
            "period": "2026-06-18",
            "record_count": 180,
            "load_curve": [22, 21, 20, 20, 22, 28, 38, 47, 54, 61, 65, 68, 67, 65, 64, 68, 75, 82, 88, 84, 72, 55, 40, 29],
        },
    )
    _seed_upload(
        db,
        upload_id="upload-generation-july-t01",
        asset_type="GENERATION_DATA",
        owner_org_id="org-generator-t01",
        label="2026年7月发电侧计量数据",
        trade_batch_no="TB-2026-07-T01",
        payload={
            "contract_id": "CONTRACT-2026-Q3",
            "period": "2026-07",
            "energy_mwh": 12680.0,
            "record_count": 31,
            "meter_point": "GEN-METER-A-001",
        },
    )
    _seed_upload(
        db,
        upload_id="upload-retail-july-t01",
        asset_type="RETAIL_DATA",
        owner_org_id="org-retailer-t01",
        label="2026年7月售电侧履约数据",
        trade_batch_no="TB-2026-07-T01",
        payload={
            "contract_id": "CONTRACT-2026-Q3",
            "period": "2026-07",
            "energy_mwh": 12490.0,
            "record_count": 1380,
            "customer_group": "MASKED-GROUP-02",
        },
    )
    _seed_upload(
        db,
        upload_id="upload-renewable-forecast-july-t01",
        asset_type="RENEWABLE_FORECAST",
        owner_org_id="org-generator-t01",
        label="2026年7月新能源出力预测",
        trade_batch_no="TB-2026-07-T01",
        payload={
            "period": "2026-07",
            "record_count": 31,
            "forecast_energy_mwh": 12840.0,
            "forecast_accuracy_pct": 92.6,
            "weather_source": "MASKED_METEOROLOGICAL_FEATURES",
        },
    )
    _seed_upload(
        db,
        upload_id="upload-vpp-resource-july-t01",
        asset_type="VPP_RESOURCE",
        owner_org_id="org-retailer-t01",
        label="2026年7月虚拟电厂可调资源池",
        trade_batch_no="TB-2026-07-T01",
        payload={
            "period": "2026-07",
            "record_count": 1860,
            "adjustable_capacity_mw": 18.6,
            "storage_energy_mwh": 42.0,
            "response_minutes": 5,
            "resource_mix": "MASKED_STORAGE_AND_FLEXIBLE_LOAD",
        },
    )
    _seed_upload(
        db,
        upload_id="upload-grid-constraint-july-t01",
        asset_type="GRID_CONSTRAINT",
        owner_org_id="org-exchange-t01",
        label="2026年7月调度安全边界",
        trade_batch_no="TB-2026-07-T01",
        payload={
            "period": "2026-07",
            "record_count": 24,
            "n_minus_one_passed": True,
            "max_residual_imbalance_mwh": 90.0,
            "congestion_margin_pct": 14.2,
            "boundary_source": "TEST_DISPATCH_GATEWAY",
        },
    )

    for task_id, capsule_id, name, batch, period_start, period_end in [
        ("task-history-t01", "HC-CAPSULE-202606-001", "2026年6月月度结算任务", "TB-2026-06-001", date(2026, 6, 1), date(2026, 6, 30)),
        ("task-ready-t01", "HC-CAPSULE-202607-001", "2026年7月月度结算任务", "TB-2026-07-T01", date(2026, 7, 1), date(2026, 7, 31)),
    ]:
        task = SettlementTask(
            task_id=task_id,
            capsule_id=capsule_id,
            task_name=name,
            trade_batch_no=batch,
            period_start=period_start,
            period_end=period_end,
            rule_id="rule-settlement-v1",
            creator_org_id="org-exchange-t01",
            status="READY" if task_id == "task-ready-t01" else "DRAFT",
            current_stage="待启动结算" if task_id == "task-ready-t01" else "任务创建",
        )
        db.add(task)
        db.add_all(
            [
                TaskParticipant(task_id=task_id, org_id="org-generator-t01", role_in_task="GENERATOR"),
                TaskParticipant(task_id=task_id, org_id="org-retailer-t01", role_in_task="RETAILER"),
            ]
        )

    db.commit()
    run_settlement_workflow(db, task_id="task-history-t01", actor=None)
