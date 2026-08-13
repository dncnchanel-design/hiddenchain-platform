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
    TaskParticipant,
    User,
)
from .security import hash_password, sha256_json, sign_value
from .services.adapters import AGENT_DEFINITIONS
from .services.vault import LocalDomainVault
from .services.workflow import run_settlement_workflow


ORGS = [
    ("org-generator-demo", "GENERATOR", "齐鲁新能源发电有限公司", "91370000GEN001"),
    ("org-retailer-demo", "RETAILER", "海岱售电服务有限公司", "91370000RET001"),
    ("org-exchange-demo", "EXCHANGE", "山东电力交易中心（演示）", "91370000EXC001"),
    ("org-regulator-demo", "REGULATOR", "能源交易监管单位（演示）", "91370000REG001"),
    ("org-admin-demo", "ADMIN", "隐链明算平台运维组织", "91370000ADM001"),
]

USERS = [
    ("user-generator", "org-generator-demo", "generator", "generator123", "发电企业业务员", "GENERATOR"),
    ("user-retailer", "org-retailer-demo", "retailer", "retailer123", "售电企业业务员", "RETAILER"),
    ("user-exchange", "org-exchange-demo", "exchange", "exchange123", "交易中心结算员", "EXCHANGE"),
    ("user-regulator", "org-regulator-demo", "regulator", "regulator123", "监管审计员", "REGULATOR"),
    ("user-admin", "org-admin-demo", "admin", "admin123", "平台系统管理员", "ADMIN"),
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
        signature_value=sign_value({"data_hash": data_hash}, f"did:hiddenchain:org:{owner_org_id}"),
        summary_json={
            "record_count": payload.get("record_count", 1),
            "period": payload.get("period", "2026-06"),
            "raw_data_stored_in_business_db": False,
        },
    )
    db.add(upload)
    return upload


def seed_demo(db: Session) -> None:
    if db.scalar(select(Organization.org_id).limit(1)):
        return

    for org_id, org_type, org_name, credit_code in ORGS:
        db.add(
            Organization(
                org_id=org_id,
                org_type=org_type,
                org_name=org_name,
                credit_code=credit_code,
                status="ACTIVE",
            )
        )
        credential = {
            "type": ["VerifiableCredential", "EnergyMarketParticipantCredential"],
            "issuer": "did:hiddenchain:regulator:demo",
            "credentialSubject": {"id": f"did:hiddenchain:org:{org_id}", "orgType": org_type},
        }
        db.add(
            DidIdentity(
                did_id=f"did:hiddenchain:org:{org_id}",
                owner_type="ORG",
                owner_id=org_id,
                org_id=org_id,
                public_key_fingerprint=sha256_json({"org_id": org_id, "key": "demo-public-key"}),
                chain_address=f"0x{sha256_json(org_id)[:40]}",
                credential_status="VALID",
                credential_json=credential,
            )
        )

    for user_id, org_id, username, password, display_name, role in USERS:
        db.add(
            User(
                user_id=user_id,
                org_id=org_id,
                username=username,
                password_hash=hash_password(password),
                display_name=display_name,
                role_code=role,
                status="ACTIVE",
            )
        )

    for definition in AGENT_DEFINITIONS:
        db.add(
            DidIdentity(
                did_id=definition["did"],
                owner_type="AGENT",
                owner_id=definition["code"],
                org_id="org-exchange-demo",
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
            rule_id="rule-settlement-demo",
            rule_name="山东电力交易月度结算演示规则",
            rule_version="SETTLE-2026-001",
            description="用于比赛MVP的确定性结算规则，所有参数均为假数据。",
            source_refs_json=["赛题方案-多方安全协同", "演示规则库-月度结算条款-01"],
            formula_dsl=formula,
            parameters_json=rule_parameters,
            policy_refs_json=["policy:settlement-purpose", "policy:no-raw-data-export"],
            approver_signatures_json=[
                {
                    "did": "did:hiddenchain:org:org-exchange-demo",
                    "signature": sign_value(rule_payload, "did:hiddenchain:org:org-exchange-demo"),
                }
            ],
            rule_hash=sha256_json(rule_payload),
            status="ACTIVE",
        )
    )

    _seed_upload(
        db,
        upload_id="upload-generation-demo",
        asset_type="GENERATION_DATA",
        owner_org_id="org-generator-demo",
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
        upload_id="upload-retail-demo",
        asset_type="RETAIL_DATA",
        owner_org_id="org-retailer-demo",
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
        owner_org_id="org-retailer-demo",
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
        owner_org_id="org-retailer-demo",
        label="园区用户群B脱敏负荷曲线",
        payload={
            "period": "2026-06-18",
            "record_count": 180,
            "load_curve": [22, 21, 20, 20, 22, 28, 38, 47, 54, 61, 65, 68, 67, 65, 64, 68, 75, 82, 88, 84, 72, 55, 40, 29],
        },
    )
    _seed_upload(
        db,
        upload_id="upload-generation-july-demo",
        asset_type="GENERATION_DATA",
        owner_org_id="org-generator-demo",
        label="2026年7月发电侧计量数据",
        trade_batch_no="TB-2026-07-DEMO",
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
        upload_id="upload-retail-july-demo",
        asset_type="RETAIL_DATA",
        owner_org_id="org-retailer-demo",
        label="2026年7月售电侧履约数据",
        trade_batch_no="TB-2026-07-DEMO",
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
        upload_id="upload-renewable-forecast-july-demo",
        asset_type="RENEWABLE_FORECAST",
        owner_org_id="org-generator-demo",
        label="2026年7月新能源出力预测",
        trade_batch_no="TB-2026-07-DEMO",
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
        upload_id="upload-vpp-resource-july-demo",
        asset_type="VPP_RESOURCE",
        owner_org_id="org-retailer-demo",
        label="2026年7月虚拟电厂可调资源池",
        trade_batch_no="TB-2026-07-DEMO",
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
        upload_id="upload-grid-constraint-july-demo",
        asset_type="GRID_CONSTRAINT",
        owner_org_id="org-exchange-demo",
        label="2026年7月调度安全边界",
        trade_batch_no="TB-2026-07-DEMO",
        payload={
            "period": "2026-07",
            "record_count": 24,
            "n_minus_one_passed": True,
            "max_residual_imbalance_mwh": 90.0,
            "congestion_margin_pct": 14.2,
            "boundary_source": "DEMO_DISPATCH_GATEWAY",
        },
    )

    for task_id, capsule_id, name, batch, period_start, period_end in [
        ("task-history-demo", "HC-CAPSULE-202606-001", "2026年6月月度交易结算", "TB-2026-06-001", date(2026, 6, 1), date(2026, 6, 30)),
        ("task-ready-demo", "HC-CAPSULE-202607-001", "2026年7月可信结算演示任务", "TB-2026-07-DEMO", date(2026, 7, 1), date(2026, 7, 31)),
    ]:
        task = SettlementTask(
            task_id=task_id,
            capsule_id=capsule_id,
            task_name=name,
            trade_batch_no=batch,
            period_start=period_start,
            period_end=period_end,
            rule_id="rule-settlement-demo",
            creator_org_id="org-exchange-demo",
            status="DRAFT",
            current_stage="任务创建",
        )
        db.add(task)
        db.add_all(
            [
                TaskParticipant(task_id=task_id, org_id="org-generator-demo", role_in_task="GENERATOR"),
                TaskParticipant(task_id=task_id, org_id="org-retailer-demo", role_in_task="RETAILER"),
            ]
        )

    db.commit()
    run_settlement_workflow(db, task_id="task-history-demo", actor=None)
