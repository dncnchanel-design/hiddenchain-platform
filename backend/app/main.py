from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings, settings, validate_runtime_settings
from .database import SessionLocal, database_readiness, ensure_runtime_schema
from .production import assert_production_database_clean
from .routers import assistant, audit, auth, data, energy, evidence, execution, prototype, system, trade, trust, trust_domain, trust_space, trusted_query
from .services.adapters import OPAPolicyAdapter, PandapowerGridAdapter
from .services.arrow_connector import ArrowConnectorAdapter
from .services.credentials import JsonLdCredentialAdapter
from .services.correlation import correlation_status
from .services.datapackage import FrictionlessCatalogAdapter
from .services.dataspace import DataspaceProtocolAdapter
from .services.duckdb_connector import DuckDBMetadataAdapter
from .services.lineage import lineage_status
from .services.odcs_connector import OpenDataContractAdapter
from .services.observability import observability_status, setup_observability
from .services.paillier import status as paillier_status
from .services.privacy import OpenDPAdapter
from .services.prometheus import observe_http_request, prometheus_status
from .services.rate_limit import limiter, rate_limit_status
from .services.solar import PvlibSolarAdapter
from .services.trust_execution import DynamicPolicyEngine
from .services.tool_catalog import agent_tool_catalog_readiness, ensure_agent_tool_catalog
from .services.evidence_outbox import LocalHashAnchorAdapter
from .services.mpc import AdditiveSecretSharingMPC
from .version import VERSION, version_payload
from .services.common import trace_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_runtime_settings()
    ensure_runtime_schema()
    with SessionLocal() as db:
        assert_production_database_clean(db, settings)
        if settings.test_fixture_seed:
            from .seed import seed_test_fixtures

            seed_test_fixtures(db)
        if settings.demo_catalog_seed:
            from .demo_seed import seed_demo_authorization_request, seed_demo_catalog

            seed_demo_catalog(db)
            seed_demo_authorization_request(db)
        from .seed import ensure_agent_identities

        ensure_agent_identities(db)
        ensure_agent_tool_catalog(db)
        if settings.demo_business_seed:
            from .demo_seed import seed_demo_business

            seed_demo_business(db)
        db.commit()
    yield


app = FastAPI(
    title=settings.app_name,
    version=VERSION,
    description="面向多能源企业的数据目录、授权、受控计算、结果交付与审计追溯服务",
    docs_url=f"{settings.api_prefix}/docs",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    lifespan=lifespan,
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def structured_rate_limit_error(
    request: Request,
    exc: RateLimitExceeded,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "detail": "Rate limit exceeded: 操作过于频繁，请稍后重试",
            "code": "RATE_LIMIT_EXCEEDED",
            "message": "操作过于频繁，请稍后重试",
            "trace_id": trace_id(),
            "retryable": True,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def structured_http_error(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code") or f"HTTP_{exc.status_code}")
        message = str(detail.get("message") or detail)
        retryable = bool(detail.get("retryable", False))
    else:
        code = f"HTTP_{exc.status_code}"
        message = str(detail)
        retryable = False
    retryable = retryable or exc.status_code in {408, 425, 429, 502, 503, 504}
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "detail": detail,
            "code": code,
            "message": message,
            "trace_id": trace_id(),
            "retryable": retryable,
        },
    )


@app.exception_handler(RequestValidationError)
async def structured_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    field_errors = [
        {
            "location": [str(item) for item in error.get("loc", ())],
            "message": error.get("msg", "invalid value"),
            "type": error.get("type", "validation_error"),
        }
        for error in exc.errors()
    ]
    missing_if_match = any(
        error.get("type") == "missing"
        and tuple(error.get("loc", ())) == ("header", "If-Match")
        for error in exc.errors()
    )
    if missing_if_match:
        return JSONResponse(
            status_code=428,
            content={
                "detail": "必须提供 If-Match 任务状态版本号",
                "code": "PRECONDITION_REQUIRED",
                "message": "必须提供 If-Match 任务状态版本号",
                "trace_id": trace_id(),
                "retryable": False,
                "field_errors": field_errors,
            },
        )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": field_errors,
            "code": "VALIDATION_ERROR",
            "message": "请求参数校验失败",
            "trace_id": trace_id(),
            "retryable": False,
            "field_errors": field_errors,
        },
    )


@app.exception_handler(Exception)
async def structured_internal_error(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    # Exception details stay in server-side telemetry.  Database statements,
    # filesystem locations, secrets and stack traces must not cross the API.
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "服务执行失败，请稍后重试",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "服务执行失败，请稍后重试",
            "trace_id": trace_id(),
            "retryable": True,
        },
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Idempotency-Replayed", "ETag"],
)
app.add_middleware(CorrelationIdMiddleware)
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

application_routers = [
    auth.router,
    data.router,
    trade.router,
    trust.router,
    trust_domain.router,
    trust_space.router,
    trusted_query.router,
    assistant.router,
    evidence.router,
    audit.router,
    system.router,
    execution.router,
    energy.router,
    prototype.router,
]
if settings.app_env in {"development", "test"}:
    from .routers import test_support

    application_routers.append(test_support.router)

for router in application_routers:
    app.include_router(router, prefix=settings.api_prefix)


@app.get("/api/version", tags=["health"])
def version() -> dict[str, object]:
    return version_payload()


@app.get("/api/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    return {"status": "UP", "service": settings.app_name, "version": VERSION}


def policy_decision_point_readiness(
    settings_value: Settings = settings,
) -> dict[str, object]:
    """Probe the configured production OPA without exposing its URL."""

    remote_configured = bool(settings_value.opa_url)
    local_fallback = bool(settings_value.opa_local_fallback)
    remote_ready = False
    latency_ms: int | None = None
    error_code: str | None = None
    if remote_configured:
        started = time.perf_counter()
        try:
            response = httpx.get(
                f"{settings_value.opa_url}/health?plugins",
                timeout=max(0.1, min(settings_value.opa_timeout_seconds, 3.0)),
            )
            response.raise_for_status()
            remote_ready = True
        except Exception:
            error_code = "OPA_UNAVAILABLE"
        latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    else:
        error_code = "OPA_NOT_CONFIGURED"

    fallback_allowed = settings_value.app_env != "production" and local_fallback
    ready = remote_ready or fallback_allowed
    return {
        "status": "READY" if ready else "NOT_READY",
        "mode": "REMOTE_OPA" if remote_ready else "LOCAL_FALLBACK" if fallback_allowed else "BLOCKED",
        "remote_configured": remote_configured,
        "remote_status": (
            "READY" if remote_ready else "UNAVAILABLE" if remote_configured else "NOT_CONFIGURED"
        ),
        "local_fallback_enabled": local_fallback,
        "policy_path": settings_value.opa_policy_path,
        "latency_ms": latency_ms,
        "error_code": None if ready else error_code,
    }


@app.get("/api/health/ready", tags=["health"])
def readiness(response: Response) -> dict[str, object]:
    database = database_readiness()
    policy = policy_decision_point_readiness()
    if settings.app_env == "demo":
        agent_tools = {
            "status": "READY",
            "mode": "OPTIONAL_CAPABILITY_BLOCKED",
            "capability_state": "BLOCKED",
            "issue_count": 0,
            "issues": [],
        }
    else:
        try:
            with SessionLocal() as db:
                agent_tools = agent_tool_catalog_readiness(db)
        except Exception:
            agent_tools = {
                "status": "NOT_READY",
                "issue_count": 1,
                "issues": ["AGENT_TOOL_CATALOG_UNAVAILABLE"],
            }
    ready = (
        database["status"] == "READY"
        and policy["status"] == "READY"
        and agent_tools["status"] == "READY"
    )
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "READY" if ready else "NOT_READY",
        "checks": {
            "database_migrations": database,
            "policy_decision_point": policy,
            "agent_tool_catalog": agent_tools,
        },
    }


@app.get("/api/health", tags=["health"])
def health() -> dict:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": version_payload(),
        "environment": settings.app_env,
        "database": database_readiness(),
        "calculation_services": {
            "policy": OPAPolicyAdapter.status(),
            "grid": PandapowerGridAdapter.status(),
            "differential_privacy": OpenDPAdapter.status(),
            "solar_resource": PvlibSolarAdapter.status(),
            "mpc_aggregate": AdditiveSecretSharingMPC.status(),
            "paillier": paillier_status(),
        },
        "integrations": {
            "observability": observability_status(),
            "lineage": lineage_status(),
            "prometheus": prometheus_status(),
            "correlation_id": correlation_status(),
            "rate_limiting": rate_limit_status(),
            "data_package": FrictionlessCatalogAdapter.status(),
            "columnar_connector": ArrowConnectorAdapter.status(),
            "metadata_analytics": DuckDBMetadataAdapter.status(),
            "data_contract": OpenDataContractAdapter.status(),
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
            "async_evidence_recording": "TRANSACTIONAL_OUTBOX_POST_COMMIT_WORKER",
            "evidence_backend": "MERKLE_BATCH_WITH_TRANSACTIONAL_OUTBOX_V1",
            "anchor_adapter": LocalHashAnchorAdapter.status(),
            "legacy_evidence_backend": "LOCAL_EVIDENCE_LEDGER_V1",
            "data_boundary_statement": "Each execution must be evaluated from its recorded protocol and attestation.",
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
