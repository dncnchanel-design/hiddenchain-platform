from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import SessionLocal, engine, ensure_runtime_schema
from .models import Base
from .routers import audit, auth, data, energy, execution, system, trade, trust
from .seed import seed_demo
from .services.adapters import OPAPolicyAdapter, PandapowerGridAdapter
from .services.arrow_connector import ArrowConnectorAdapter
from .services.credentials import JsonLdCredentialAdapter
from .services.datapackage import FrictionlessCatalogAdapter
from .services.dataspace import DataspaceProtocolAdapter
from .services.duckdb_connector import DuckDBMetadataAdapter
from .services.lineage import lineage_status
from .services.observability import observability_status, setup_observability
from .services.privacy import OpenDPAdapter
from .services.prometheus import observe_http_request, prometheus_status
from .services.solar import PvlibSolarAdapter
from .services.trust_execution import DynamicPolicyEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_runtime_schema()
    if settings.demo_seed:
        with SessionLocal() as db:
            seed_demo(db)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="以可信数据调用与隐私计算为核心、以能源电力为验证场景的 Agent 原生可信数据空间 MVP",
    docs_url=f"{settings.api_prefix}/docs",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
setup_observability(app)


@app.middleware("http")
async def collect_prometheus_metrics(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        route = request.scope.get("route")
        observe_http_request(
            method=request.method,
            path=getattr(route, "path", "/unmatched"),
            status_code=500,
            duration_seconds=time.perf_counter() - started,
        )
        raise
    route = request.scope.get("route")
    observe_http_request(
        method=request.method,
        path=getattr(route, "path", "/unmatched"),
        status_code=response.status_code,
        duration_seconds=time.perf_counter() - started,
    )
    return response

for router in [auth.router, data.router, trade.router, trust.router, audit.router, system.router, execution.router, energy.router]:
    app.include_router(router, prefix=settings.api_prefix)


@app.get("/api/health", tags=["health"])
def health() -> dict:
    return {
        "status": "ok",
        "service": settings.app_name,
        "mode": "MVP_WITH_REPLACEABLE_ADAPTERS",
        "security_boundary": "Agent orchestration is separated from deterministic execution.",
        "mvp_adapters": {
            "policy": OPAPolicyAdapter.status(),
            "grid": PandapowerGridAdapter.status(),
            "differential_privacy": OpenDPAdapter.status(),
            "solar_resource": PvlibSolarAdapter.status(),
        },
        "integrations": {
            "observability": observability_status(),
            "lineage": lineage_status(),
            "prometheus": prometheus_status(),
            "data_package": FrictionlessCatalogAdapter.status(),
            "columnar_connector": ArrowConnectorAdapter.status(),
            "metadata_analytics": DuckDBMetadataAdapter.status(),
            "credential_canonicalization": JsonLdCredentialAdapter.status(),
            "dataspace_protocol": DataspaceProtocolAdapter.status(),
        },
        "trusted_execution": {
            "controller": "TRUSTWORTHY_EXECUTION_CONTROLLER_V1",
            "policy_version": DynamicPolicyEngine().version,
            "workflow_steps": [
                "INGEST",
                "AUTHENTICATE",
                "RESOLVE",
                "ARBITRATE",
                "EXECUTE",
                "AUDIT",
                "DELIVER",
                "LOG",
            ],
            "raw_data_transferred": False,
            "async_blockchain_audit": True,
        },
    }


# The Docker/Render deployment can serve the Vite build from the same origin as
# the API.  This keeps /api requests same-origin and avoids a second public
# service just for the frontend.  Local development still uses Vite directly.
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend_dist"
if FRONTEND_DIR.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIR / "assets"),
        name="frontend-assets",
    )

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend_app(path: str):
        requested = FRONTEND_DIR / path
        if requested.is_file():
            return FileResponse(requested)
        return FileResponse(FRONTEND_DIR / "index.html")
