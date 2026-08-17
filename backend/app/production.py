from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import Settings
from .models import BlockchainEvidence, Organization, PrivacyComputeJob, SettlementTask, User


NON_PRODUCTION_USERNAMES = {
    "generator",
    "retailer",
    "exchange",
    "regulator",
    "admin",
}
def assert_production_database_clean(db: Session, settings: Settings) -> None:
    """Refuse to expose a database that still contains known fixture identities."""

    if settings.app_env != "production":
        return

    fixture_orgs = db.scalar(
        select(func.count(Organization.org_id)).where(
            or_(
                Organization.org_id.ilike("%demo%"),
                Organization.org_id.ilike("%test%"),
                Organization.org_id.ilike("%-t01%"),
                Organization.org_name.contains("演示"),
                Organization.org_name.contains("测试"),
                Organization.org_name.contains("模拟"),
            )
        )
    ) or 0
    fixture_tasks = db.scalar(
        select(func.count(SettlementTask.task_id)).where(
            or_(
                SettlementTask.task_id.ilike("%demo%"),
                SettlementTask.task_id.ilike("%test%"),
                SettlementTask.task_id.ilike("%-t01%"),
                SettlementTask.trade_batch_no.ilike("%demo%"),
                SettlementTask.trade_batch_no.ilike("%test%"),
                SettlementTask.trade_batch_no.ilike("%t01%"),
                SettlementTask.task_name.contains("演示"),
                SettlementTask.task_name.contains("测试"),
                SettlementTask.task_name.contains("模拟"),
            )
        )
    ) or 0
    fixture_users = db.scalar(
        select(func.count(User.user_id)).where(User.username.in_(NON_PRODUCTION_USERNAMES))
    ) or 0
    unsupported_compute_records = db.scalar(
        select(func.count(PrivacyComputeJob.job_id)).where(
            PrivacyComputeJob.adapter_code != "LOCAL_CONTROLLED_SETTLEMENT_V1"
        )
    ) or 0
    unsupported_evidence_records = db.scalar(
        select(func.count(BlockchainEvidence.evidence_id)).where(
            BlockchainEvidence.chain_code != "LOCAL_EVIDENCE_LEDGER_V1"
        )
    ) or 0

    findings = []
    if fixture_orgs:
        findings.append(f"{fixture_orgs} fixture organizations")
    if fixture_tasks:
        findings.append(f"{fixture_tasks} fixture settlement tasks")
    if fixture_users:
        findings.append(f"{fixture_users} default test accounts")
    if unsupported_compute_records:
        findings.append(f"{unsupported_compute_records} unsupported compute records")
    if unsupported_evidence_records:
        findings.append(f"{unsupported_evidence_records} unsupported evidence records")
    if findings:
        raise RuntimeError(
            "Production database contains non-production records: "
            + ", ".join(findings)
            + ". Use an isolated production database; records were not deleted automatically."
        )
