import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import asyncio
import logging
import time

from backend.routes import chat, odoo, agentic, health, executive_demo, auth as auth_routes
from backend.routes import import_routes
from backend.routes import config as config_routes
from backend.routes import quality as quality_routes
from backend.routes import workflow as workflow_routes
from backend.routes import rfq as rfq_routes
from backend.routes import amendments as amendments_routes
from backend.routes import rtv as rtv_routes
from backend.routes import quality_inspection as qc_routes
from backend.routes import reconciliation as recon_routes
from backend.routes import audit as audit_routes
from backend.routes import p2p_tracker as p2p_tracker_routes
from backend.routes import gap_features as gap_routes
from backend.routes import sessions as sessions_routes
from backend.routes import admin as admin_routes
from backend.routes import ocr as ocr_routes
from backend.services.rate_limiter import (
    check_rate_limit,
    get_user_identifier,
    RateLimitExceeded
)
from backend.services.cache import get_cache

logger = logging.getLogger(__name__)


def _get_allowed_origins() -> list[str]:
    """Return explicit allowed origins for CORS (no broad wildcard regex)."""
    default_origins = [
        "http://localhost:5173",      # Vite dev server
        "http://localhost:3000",      # Alternative dev
        "http://localhost:5000",      # Same-origin
        os.getenv("FRONTEND_URL", "https://procure-ai-frontend.onrender.com"),
    ]

    configured = os.getenv("CORS_ALLOWED_ORIGINS", "")
    if not configured.strip():
        return default_origins

    parsed = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return parsed or default_origins


class TimeoutMiddleware(BaseHTTPMiddleware):
    """
    Global timeout middleware for all API requests.
    Returns 504 Gateway Timeout if request exceeds limit.
    Prevents hanging requests from consuming server resources.
    """
    
    def __init__(self, app, timeout_seconds: int = 30):
        super().__init__(app)
        self.timeout_seconds = timeout_seconds
        logger.info(f"[TIMEOUT MIDDLEWARE] Initialized with {timeout_seconds}s timeout")
    
    async def dispatch(self, request: Request, call_next):
        # Skip timeout for SSE streaming endpoints
        if request.url.path.endswith('/stream'):
            return await call_next(request)
        
        try:
            # Race between request processing and timeout
            return await asyncio.wait_for(
                call_next(request),
                timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.error(f"[TIMEOUT] Request to {request.url.path} exceeded {self.timeout_seconds}s")
            return JSONResponse(
                status_code=504,
                content={
                    "error": "Request timeout",
                    "message": f"Request took longer than {self.timeout_seconds} seconds",
                    "suggestion": "Try simplifying your query or contact support",
                    "path": request.url.path
                }
            )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware to prevent API abuse.
    Enforces per-user rate limits on requests.
    """
    
    def __init__(self, app):
        super().__init__(app)
        logger.info("[RATE LIMIT MIDDLEWARE] Initialized")
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks, static files, and CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path.startswith("/health") or request.url.path.startswith("/assets"):
            return await call_next(request)

        # Sprint E fix (2026-04-11): explicit exemption list for endpoints the
        # SessionPage + ErpBadge + PhaseDetailAccordion poll on a short
        # interval. These are pure reads from the session event store / config
        # cache and would never be the target of a real DoS. Letting them
        # through avoids the 429 storm that locked the UI on load.
        _EXEMPT_PREFIXES = (
            "/api/sessions/",      # Session reads + SSE /events + /gates/pending
            "/api/config/",        # Data-source / departments / etc.
        )
        if any(request.url.path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        # Get user identifier
        user_id = get_user_identifier(request)

        # Determine endpoint type for appropriate limits
        endpoint_type = "default"
        # Polling endpoints (used by dashboards / badges / approval counters)
        # get the much-looser "polling" bucket.
        _POLLING_PATHS = (
            "/api/agentic/pending-approvals/count",
            "/api/agentic/approval-chains",
            "/api/agentic/agents",
        )
        if request.url.path in _POLLING_PATHS or any(
            request.url.path.startswith(p) for p in _POLLING_PATHS
        ):
            endpoint_type = "polling"
        elif "/api/agentic" in request.url.path:
            endpoint_type = "agentic"
        elif "/api/chat" in request.url.path:
            endpoint_type = "chat"
        
        # Check rate limit
        try:
            rate_limit_error = check_rate_limit(user_id, endpoint_type)
            if rate_limit_error:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Rate limit exceeded",
                        "message": str(rate_limit_error),
                        "limit_type": rate_limit_error.limit_type,
                        "limit_value": rate_limit_error.limit_value,
                        "retry_after": rate_limit_error.retry_after,
                        "user_id": user_id
                    },
                    headers={
                        "Retry-After": str(rate_limit_error.retry_after),
                        "X-RateLimit-Limit": str(rate_limit_error.limit_value),
                        "X-RateLimit-Reset": str(int(time.time()) + rate_limit_error.retry_after)
                    }
                )
        except Exception as e:
            logger.error(f"[RATE LIMIT] Error checking rate limit: {e}")
            # Don't block request on rate limit check error
        
        return await call_next(request)


app = FastAPI(title="Procurement AI Chatbot")

# IMPORTANT: FastAPI middleware runs in reverse registration order.
# Register CORS last so it runs FIRST (before rate limiting and timeout).
# This ensures OPTIONS preflight requests get correct CORS headers before any other middleware.

# Add global timeout middleware (30 seconds) - runs 3rd
app.add_middleware(TimeoutMiddleware, timeout_seconds=30)

# Add rate limiting middleware - runs 2nd
app.add_middleware(RateLimitMiddleware)

# Add CORS middleware - runs 1st (last registered = first executed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "X-User-ID",
        "X-Approver-Email",
        "X-Admin-Token",
    ],
)


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.middleware("http")
async def error_logging_middleware(request: Request, call_next):
    """Global error logging middleware to catch all unhandled exceptions"""
    try:
        print(f"\n[REQUEST] {request.method} {request.url.path}")
        response = await call_next(request)
        print(f"[RESPONSE] {request.method} {request.url.path} - Status: {response.status_code}")
        return response
    except Exception as e:
        print("\n" + "="*80)
        print(f"[GLOBAL ERROR] UNHANDLED EXCEPTION")
        print("="*80)
        print(f"[ERROR] Method: {request.method}")
        print(f"[ERROR] Path: {request.url.path}")
        print(f"[ERROR] Exception: {str(e)}")
        print(f"[ERROR] Type: {type(e).__name__}")
        import traceback
        print(f"[ERROR] Traceback:\n{traceback.format_exc()}")
        print("="*80 + "\n")

        # Re-raise to let FastAPI handle the HTTP error response
        raise


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Capture Pydantic validation errors with full context so we can see which
    field failed and what the raw body looked like. Without this, a 422 from
    FastAPI is opaque on the server side.
    """
    try:
        body_bytes = await request.body()
        body_preview = body_bytes.decode("utf-8", errors="replace")[:2000]
    except Exception:
        body_preview = "<unreadable body>"
    print("\n" + "=" * 80)
    print("[VALIDATION 422]")
    print("=" * 80)
    print(f"[422] Method: {request.method}")
    print(f"[422] Path:   {request.url.path}")
    print(f"[422] Errors: {exc.errors()}")
    print(f"[422] Body:   {body_preview}")
    print("=" * 80 + "\n")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body_preview": body_preview},
    )

app.include_router(auth_routes.router, prefix="/api/auth")  # JWT authentication routes
app.include_router(chat.router, prefix="/api")  # Conversational chatbot (Odoo + custom tables)
app.include_router(odoo.router)  # Odoo API routes
app.include_router(agentic.router)  # Agentic system routes (Sprint 1)
app.include_router(health.router, prefix="/api")  # Health check and circuit breaker status
app.include_router(executive_demo.router)  # Executive theater websocket + replay endpoints
app.include_router(import_routes.router, prefix="/api/import")  # File upload & data import (Sprint 11)
app.include_router(config_routes.router, prefix="/api/config")  # ERP data source switching
app.include_router(quality_routes.router, prefix="/api/quality")  # Data quality scanning
app.include_router(workflow_routes.router, prefix="/api/workflow")  # P2P workflow engine
app.include_router(p2p_tracker_routes.router, prefix="/api/p2p")  # P2P tracker & journey view
app.include_router(rfq_routes.router, prefix="/api/rfq")  # RFQ management
app.include_router(amendments_routes.router, prefix="/api/amendments")  # PO amendments
app.include_router(rtv_routes.router, prefix="/api/rtv")  # Returns to vendor
app.include_router(qc_routes.router, prefix="/api/qc")  # Quality inspection
app.include_router(recon_routes.router, prefix="/api/reconciliation")  # Payment reconciliation
app.include_router(audit_routes.router, prefix="/api/audit")  # Audit trail export
app.include_router(gap_routes.router)  # Dev Spec 2.0 gap features (G-01 through G-14)
app.include_router(sessions_routes.router)  # Layer 1: Execution session orchestration (P0)
app.include_router(admin_routes.router)  # P1.5: Admin tooling (drift reports, HF-5 / R18)
app.include_router(ocr_routes.router)  # OCR document processing & email inbox scanning

@app.on_event("startup")
async def startup_event():
    """Startup event for Odoo + agentic runtime — Sprint 9: scheduler added."""
    logger.info("=" * 80)
    logger.info("FASTAPI SERVER STARTING")
    logger.info("=" * 80)
    logger.info("Startup Time: %s", datetime.utcnow().isoformat() + "Z")
    logger.info("ENVIRONMENT CHECK:")
    logger.info("  OPENAI_API_KEY: %s", "SET" if os.getenv("OPENAI_API_KEY") else "MISSING")
    logger.info("  DATABASE_URL: %s", "SET" if os.getenv("DATABASE_URL") else "MISSING")
    logger.info("  DATA_SOURCE: %s", os.getenv("DATA_SOURCE", "not set"))
    logger.info("  ODOO_URL: %s", os.getenv("ODOO_URL", "http://localhost:8069"))

    # Sprint D / Oracle-focus (2026-04-11): actively resolve the adapter at boot
    # so the log clearly shows which class is bound and whether it's in demo or
    # live mode. If this fails, we fail loud rather than at the first request.
    try:
        from backend.services.adapters.factory import get_adapter
        _active = get_adapter()
        logger.info(
            "[ADAPTER-BOOT] Active data-source adapter: %s -> %s",
            _active.__class__.__name__, _active.source_name(),
        )
    except Exception as _adapter_err:
        logger.error("[ADAPTER-BOOT] Failed to resolve adapter at startup: %s", _adapter_err)

    # Initialize cache system
    cache = get_cache()
    if cache.enabled:
        cache_type = "fakeredis" if os.getenv("USE_FAKEREDIS", "true").lower() == "true" else "Redis"
        logger.info("CACHE: %s (%s)", cache_type, type(cache.client).__name__)
    else:
        logger.warning("CACHE: disabled")

    # Initialize connection pool
    try:
        from backend.services.db_pool import init_pool, get_pool_stats
        pool = init_pool(minconn=5, maxconn=20, connection_timeout=30)
        stats = get_pool_stats()
        logger.info("DB POOL: %s-%s connections, %s idle",
                     stats["config"]["minconn"], stats["config"]["maxconn"], stats["idle_connections"])
    except Exception as e:
        logger.error("DB POOL FAILED: %s", e)
        raise RuntimeError("Database connection pool could not be initialized") from e

    logger.info("ROUTES: %d total (/api/auth, /api/chat, /api/agentic, /api/import, /api/odoo, /api/health)",
                len(app.routes))
    logger.info("=" * 80)
    logger.info("SERVER READY - port 5000")
    logger.info("=" * 80)

    # Start background scheduler (Sprint 9)
    try:
        from backend.services.scheduler_service import start_scheduler
        asyncio.create_task(start_scheduler())
        logger.info("[STARTUP] Background scheduler started.")
    except Exception as _sched_err:
        logger.warning("[STARTUP] Scheduler could not start: %s", _sched_err)

    # P1.5 / HF-5 / R18 — Drift reconciliation loop.
    # Hybrid mode default interval = 15 minutes. Disable by setting
    # DRIFT_RECONCILIATION_ENABLED=false (e.g. in local dev or tests).
    if os.getenv("DRIFT_RECONCILIATION_ENABLED", "true").lower() not in ("false", "0", "no"):
        try:
            from backend.jobs.drift_reconciliation import drift_reconciliation_loop
            interval = int(os.getenv("DRIFT_RECONCILIATION_INTERVAL_SECONDS", "900"))
            asyncio.create_task(drift_reconciliation_loop(interval_seconds=interval))
            logger.info("[STARTUP] Drift reconciliation loop started (interval=%ds).", interval)
        except Exception as _drift_err:
            logger.warning("[STARTUP] Drift reconciliation could not start: %s", _drift_err)
    else:
        logger.info("[STARTUP] Drift reconciliation disabled via env var.")

    # P1.5 / HF-2 / R12 — Outbox pump.
    # Moves session_event_outbox rows into session_events on a short interval
    # so NOTIFY fires and SSE listeners see the event. Disable by setting
    # OUTBOX_PUMP_ENABLED=false. Default interval 100ms keeps publish latency
    # imperceptible in healthy conditions.
    if os.getenv("OUTBOX_PUMP_ENABLED", "true").lower() not in ("false", "0", "no"):
        try:
            from backend.jobs.outbox_pump import outbox_pump_loop
            pump_interval = float(os.getenv("OUTBOX_PUMP_INTERVAL_SECONDS", "0.1"))
            pump_batch = int(os.getenv("OUTBOX_PUMP_BATCH_SIZE", "100"))
            asyncio.create_task(
                outbox_pump_loop(interval_seconds=pump_interval, batch_size=pump_batch)
            )
            logger.info(
                "[STARTUP] Outbox pump started (interval=%.3fs batch=%d).",
                pump_interval, pump_batch,
            )
        except Exception as _pump_err:
            logger.warning("[STARTUP] Outbox pump could not start: %s", _pump_err)
    else:
        logger.info("[STARTUP] Outbox pump disabled via env var.")


CLIENT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
DIST_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dist")

if os.path.exists(DIST_PATH):
    if os.path.exists(os.path.join(DIST_PATH, "assets")):
        app.mount("/assets", StaticFiles(directory=os.path.join(DIST_PATH, "assets")), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api"):
            return None
        file_path = os.path.join(DIST_PATH, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        index_path = os.path.join(DIST_PATH, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"error": "Frontend not built. Run 'npm run build' first."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=5000, reload=True)

