def test_distinct_task_names_do_not_change_settlement_identity(client, auth_headers):
    payload = {'task_name': '重复检查一', 'trade_batch_no': 'TB-2026-07-T01', 'period_start': '2026-07-01', 'period_end': '2026-07-31', 'rule_id': 'rule-settlement-v1', 'participants': [{'org_id':'org-generator-t01','role_in_task':'GENERATOR'}, {'org_id':'org-retailer-t01','role_in_task':'RETAILER'}]}
    first = client.post('/api/settlement/tasks', headers=auth_headers['exchange'], json=payload).json()
    second = client.post('/api/settlement/tasks', headers=auth_headers['exchange'], json={**payload, 'task_name': '重复检查二'}).json()
    for task in (first, second):
        view = client.get('/api/settlement/tasks/' + task['task_id'], headers=auth_headers['exchange'])
        result = client.post('/api/settlement/tasks/' + task['task_id'] + '/run', headers={**auth_headers['exchange'], 'If-Match': view.headers['etag']}, json={'compute_mode':'LOCAL_CONTROLLED','algorithm_code':'CONTROLLED_SETTLEMENT_V1'})
        if task is first:
            assert result.status_code == 200, result.text
        else:
            assert result.status_code == 409, result.text



def test_identity_lock_concurrent_transactions_are_atomic(client, auth_headers):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import SettlementTask, TaskParticipant
    from app.services.settlement_guard import reserve_settlement_identity, SettlementConflict

    payload = {'task_name': '并发身份 A', 'trade_batch_no': 'PARALLEL-IDENTITY-NEW', 'period_start': '2026-07-01', 'period_end': '2026-07-31', 'rule_id': 'rule-settlement-v1', 'participants': [{'org_id':'org-generator-t01','role_in_task':'GENERATOR'}, {'org_id':'org-retailer-t01','role_in_task':'RETAILER'}]}
    ids = []
    for name in ('并发身份 A', '并发身份 B'):
        response = client.post('/api/settlement/tasks', headers=auth_headers['exchange'], json={**payload, 'task_name': name})
        assert response.status_code == 201
        ids.append(response.json()['task_id'])
    gate = Barrier(2, timeout=15)
    def attempt(task_id):
        with SessionLocal() as db:
            task = db.get(SettlementTask, task_id)
            parties = db.scalars(select(TaskParticipant).where(TaskParticipant.task_id == task_id)).all()
            gate.wait()
            try:
                reserve_settlement_identity(db, task, parties)
                db.commit()
                return 'success'
            except SettlementConflict:
                db.rollback()
                return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ids)) == ['conflict', 'success']
    from app.models import SettlementIdentityLock
    with SessionLocal() as db:
        lock = db.scalars(select(SettlementIdentityLock).where(SettlementIdentityLock.task_id.in_(ids))).one()
        task = db.get(SettlementTask, lock.task_id)
        task.status = 'EXCEPTION'
        db.commit()
        parties = db.scalars(select(TaskParticipant).where(TaskParticipant.task_id == lock.task_id)).all()
        reserve_settlement_identity(db, task, parties)  # Same task can resume an interrupted attempt.


def test_historical_duplicate_without_lock_is_blocked(client, auth_headers):
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import SettlementIdentityLock, SettlementTask, TaskParticipant
    from app.services.settlement_guard import reserve_settlement_identity, SettlementConflict
    import pytest

    payload = {'task_name': '旧结算记录', 'trade_batch_no': 'HISTORY-IDENTITY-NEW', 'period_start': '2026-07-01', 'period_end': '2026-07-31', 'rule_id': 'rule-settlement-v1', 'participants': [{'org_id':'org-generator-t01','role_in_task':'GENERATOR'}, {'org_id':'org-retailer-t01','role_in_task':'RETAILER'}]}
    ids = []
    for name in ('旧结算记录', '新任务'):
        response = client.post('/api/settlement/tasks', headers=auth_headers['exchange'], json={**payload, 'task_name': name})
        assert response.status_code == 201
        ids.append(response.json()['task_id'])
    with SessionLocal() as db:
        db.get(SettlementTask, ids[0]).status = 'AUDITED'
        db.commit()
        current = db.get(SettlementTask, ids[1])
        parties = db.scalars(select(TaskParticipant).where(TaskParticipant.task_id == ids[1])).all()
        with pytest.raises(SettlementConflict):
            reserve_settlement_identity(db, current, parties)
        db.rollback()
        assert db.get(SettlementTask, ids[0]).status == 'AUDITED'
        assert db.scalars(select(SettlementIdentityLock).where(SettlementIdentityLock.task_id == ids[1])).first() is None


def test_same_task_retries_are_atomically_claimed(client, auth_headers):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import SettlementTask, TaskParticipant
    from app.services.settlement_guard import reserve_settlement_identity, SettlementConflict

    payload = {'task_name': '同任务并发', 'trade_batch_no': 'SAME-TASK-RETRY', 'period_start': '2026-07-01', 'period_end': '2026-07-31', 'rule_id': 'rule-settlement-v1', 'participants': [{'org_id':'org-generator-t01','role_in_task':'GENERATOR'}, {'org_id':'org-retailer-t01','role_in_task':'RETAILER'}]}
    response = client.post('/api/settlement/tasks', headers=auth_headers['exchange'], json=payload)
    assert response.status_code == 201
    task_id = response.json()['task_id']
    with SessionLocal() as db:
        task = db.get(SettlementTask, task_id)
        parties = db.scalars(select(TaskParticipant).where(TaskParticipant.task_id == task_id)).all()
        reserve_settlement_identity(db, task, parties)
        task.status = 'EXCEPTION'
        db.commit()
    gate = Barrier(2, timeout=15)
    def attempt():
        with SessionLocal() as db:
            task = db.get(SettlementTask, task_id)
            parties = db.scalars(select(TaskParticipant).where(TaskParticipant.task_id == task_id)).all()
            gate.wait()
            try:
                reserve_settlement_identity(db, task, parties)
                db.commit()
                return 'success'
            except SettlementConflict:
                db.rollback()
                return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == ['conflict', 'success']


def test_http_concurrent_same_task_executes_once(client, auth_headers, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import SettlementTask, TaskParticipant
    from app.services import workflow
    from app.services.settlement_guard import reserve_settlement_identity

    payload = {'task_name': '并发 API', 'trade_batch_no': 'TB-2026-07-T01', 'period_start': '2026-07-01', 'period_end': '2026-07-31', 'rule_id': 'rule-settlement-v1', 'participants': [{'org_id':'org-generator-t01','role_in_task':'GENERATOR'}, {'org_id':'org-retailer-t01','role_in_task':'RETAILER'}]}
    created = client.post('/api/settlement/tasks', headers=auth_headers['exchange'], json=payload)
    assert created.status_code == 201
    task_id = created.json()['task_id']
    with SessionLocal() as db:
        task = db.get(SettlementTask, task_id)
        parties = db.scalars(select(TaskParticipant).where(TaskParticipant.task_id == task_id)).all()
        reserve_settlement_identity(db, task, parties)
        db.flush()
        task.status = 'READY'
        db.commit()
    view = client.get('/api/settlement/tasks/' + task_id, headers=auth_headers['exchange'])
    headers = {**auth_headers['exchange'], 'If-Match': view.headers['etag']}
    gate = Barrier(2, timeout=20)
    def synchronized(*args):
        gate.wait()
        return reserve_settlement_identity(*args)
    monkeypatch.setattr(workflow, 'reserve_settlement_identity', synchronized)
    def run(_):
        result = client.post('/api/settlement/tasks/' + task_id + '/run', headers=headers, json={'compute_mode':'LOCAL_CONTROLLED','algorithm_code':'CONTROLLED_SETTLEMENT_V1'})
        return result.status_code, result.json().get('detail')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
        assert sorted(code for code, _ in results) == [200, 409], results
