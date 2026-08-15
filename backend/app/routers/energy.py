from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import require_roles
from ..models import User
from ..schemas import SolarEvaluationRequest
from ..services.solar import PvlibSolarAdapter


router = APIRouter(prefix="/energy", tags=["energy"])


@router.post("/solar/evaluate")
def evaluate_solar_resource(
    payload: SolarEvaluationRequest,
    user: User = Depends(require_roles("GENERATOR", "EXCHANGE", "REGULATOR", "ADMIN")),
) -> dict:
    try:
        return PvlibSolarAdapter.evaluate(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="新能源资源参数不满足安全边界") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="新能源模型暂不可用") from exc
