from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import BUSINESS_ROLES, require_roles
from ..models import User
from ..services import electricity_calculation as service

router = APIRouter(prefix="/trust-space/assistant/electricity", tags=["electricity-calculation"])
actor = require_roles(*BUSINESS_ROLES)


class PrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=36)
    question: str = Field(min_length=1, max_length=4000)
    scenario: Literal["zhejiang_spot", "generation_cost"] | None = None
    based_on: str | None = Field(default=None, max_length=36)


class CalculateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameters: dict[str, str] = Field(max_length=20)
    confirmed: bool
    state_version: int = Field(ge=1)


def _call(function, *args):
    try:
        return function(*args)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/catalog")
def catalog(user: User = Depends(actor)):
    return service.catalog()


@router.get("/sessions/{session_id}")
def history(session_id: str, user: User = Depends(actor), db: Session = Depends(get_db)):
    return _call(service.history, db, session_id, user)


@router.get("/cases")
def cases(user: User = Depends(actor), db: Session = Depends(get_db)):
    return service.cases(db, user)


@router.post("/prepare")
def prepare(payload: PrepareRequest, idempotency_key: str = Header(min_length=1, max_length=128, alias="Idempotency-Key"), user: User = Depends(actor), db: Session = Depends(get_db)):
    return _call(service.prepare, db, user, payload.session_id, payload.question.strip(), payload.scenario, payload.based_on, idempotency_key)


@router.post("/{plan_id}/calculate")
def calculate(plan_id: str, payload: CalculateRequest, user: User = Depends(actor), db: Session = Depends(get_db)):
    return _call(service.calculate, db, user, plan_id, payload.parameters, payload.confirmed, payload.state_version)


@router.post("/{plan_id}/save")
def save_case(plan_id: str, user: User = Depends(actor), db: Session = Depends(get_db)):
    return _call(service.save_case, db, user, plan_id)
