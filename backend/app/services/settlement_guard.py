"""Prevent concurrent or historical duplicate settlement executions."""
from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import PrivacyComputeJob, SettlementIdentityLock, SettlementTask, TaskParticipant
from ..security import sha256_json


class SettlementConflict(ValueError):
    pass


def _identity_hash(task: SettlementTask, participants: list[TaskParticipant]) -> str:
    parties = sorted((p.role_in_task, p.org_id) for p in participants)
    batch = task.trade_batch_no.strip().upper()
    return sha256_json({"batch": batch, "start": task.period_start.isoformat(),
                        "end": task.period_end.isoformat(), "parties": parties})


def settlement_identity_conflict(db: Session, task: SettlementTask, participants: list[TaskParticipant]) -> str | None:
    """Read the execution guard's blockers without reserving or changing a task."""
    parties = sorted((p.role_in_task, p.org_id) for p in participants)
    batch = task.trade_batch_no.strip().upper()
    with db.no_autoflush:
        reservation = db.get(SettlementIdentityLock, _identity_hash(task, participants))
        if reservation is not None and reservation.task_id != task.task_id:
            return "该批次、期间及参与方已有结算任务，请勿重复结算"

        # Existing installations may have executions predating reservations.
        # Keep every historical row intact and block rather than pick a winner.
        candidates = db.scalars(select(SettlementTask).where(
            SettlementTask.task_id != task.task_id,
            SettlementTask.period_start == task.period_start,
            SettlementTask.period_end == task.period_end,
            (SettlementTask.status.in_(("RUNNING", "PENDING_CONFIRMATION", "PARTIALLY_CONFIRMED", "AUDITED", "ARCHIVED")) |
             exists(select(PrivacyComputeJob.task_id).where(
                 PrivacyComputeJob.task_id == SettlementTask.task_id,
                 PrivacyComputeJob.status.in_(("RUNNING", "SUCCESS")),
             ))),
        )).all()
        for prior in candidates:
            if prior.trade_batch_no.strip().upper() != batch:
                continue
            prior_parties = db.scalars(select(TaskParticipant).where(TaskParticipant.task_id == prior.task_id)).all()
            if (len(prior_parties) != 2 or {p.role_in_task for p in prior_parties} != {"GENERATOR", "RETAILER"}
                    or sorted((p.role_in_task, p.org_id) for p in prior_parties) == parties):
                return "发现相同结算身份的历史执行记录，请人工核查"
    return None


def reserve_settlement_identity(db: Session, task: SettlementTask, participants: list[TaskParticipant]) -> None:
    if task.status == "RUNNING":
        raise SettlementConflict("该结算任务正在执行，请勿重复提交")
    identity = _identity_hash(task, participants)
    reservation = db.get(SettlementIdentityLock, identity)
    if reservation is None:
        db.add(SettlementIdentityLock(identity_hash=identity, task_id=task.task_id))
        try:
            db.flush()
        except IntegrityError as exc:
            raise SettlementConflict("该批次、期间及参与方已有结算任务，请勿重复结算") from exc
    conflict = settlement_identity_conflict(db, task, participants)
    if conflict is not None:
        raise SettlementConflict(conflict)

    # The reservation belongs to the task, so it cannot by itself serialize
    # two retries of that same task. Claim its current state atomically too.
    claimed = db.execute(update(SettlementTask).where(
        SettlementTask.task_id == task.task_id,
        SettlementTask.status == task.status,
        SettlementTask.state_version == task.state_version,
        SettlementTask.status != "RUNNING",
    ).values(status="RUNNING"), execution_options={"synchronize_session": False})
    if claimed.rowcount != 1:
        raise SettlementConflict("该结算任务状态已变化或正在执行，请重新查询")
    task.status = "RUNNING"
