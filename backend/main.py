import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import asyncio
import logging
import time

from backend.routes import chat, odoo, agentic, health, executive_demo, auth as auth_routes
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
        
        # Get user identifier
        user_id = get_user_identifier(request)
        
        # Determine endpoint type for appropriate limits
        endpoint_type = "default"
        if "/api/agentic" in request.url.path:
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
        print(f"[GLOBAL ERROR] ❌❌❌ UNHANDLED EXCEPTION")
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

app.include_router(auth_routes.router, prefix="/api/auth")  # JWT authentication routes
app.include_router(chat.router, prefix="/api")  # Conversational chatbot (Odoo + custom tables)
app.include_router(odoo.router)  # Odoo API routes
app.include_router(agentic.router)  # Agentic system routes (Sprint 1)
app.include_router(health.router, prefix="/api")  # Health check and circuit breaker status
app.include_router(executive_demo.router)  # Executive theater websocket + replay endpoints

@app.on_event("startup")
async def startup_event():
    """Startup event for Odoo + agentic runtime — Sprint 9: scheduler added."""
    print("\n" + "="*80)
    print("🚀 FASTAPI SERVER STARTING")
    print("="*80)
    print("📅 Startup Time:", datetime.utcnow().isoformat() + "Z")
    print("🐍 Python Environment: Loaded from .env")
    print("\n🔧 ENVIRONMENT CHECK:")
    print(f"  ✅ OPENAI_API_KEY: {'SET' if os.getenv('OPENAI_API_KEY') else '❌ MISSING'}")
    print(f"  ✅ DATABASE_URL: {'SET' if os.getenv('DATABASE_URL') else '❌ MISSING'}")
    print(f"  ✅ ODOO_URL: {os.getenv('ODOO_URL', 'http://localhost:8069')}")
    print(f"  ✅ ODOO_DB: {os.getenv('ODOO_DB', 'odoo_procurement_demo')}")
    print(f"  ✅ ODOO_USERNAME: {'SET' if os.getenv('ODOO_USERNAME') else '❌ MISSING'}")
    
    # Initialize cache system (FIX #4)
    print("\n💾 CACHE SYSTEM:")
    cache = get_cache()
    if cache.enabled:
        cache_type = "fakeredis" if os.getenv("USE_FAKEREDIS", "true").lower() == "true" else "Redis"
        print(f"  ✅ Cache enabled: {cache_type}")
        print(f"  📊 Cache backend: {type(cache.client).__name__}")
        print(f"  ⏱️  TTL configured: vendors=15min, products=15min, POs=1min")
    else:
        print(f"  ⚠️  Cache disabled (install redis or fakeredis)")
    
    # Initialize connection pool (FIX #5)
    print("\n🔌 DATABASE CONNECTION POOL:")
    try:
        from backend.services.db_pool import init_pool, get_pool_stats
        pool = init_pool(
            minconn=5,   # Keep 5 warm connections ready
            maxconn=20,  # Allow up to 20 during high load
            connection_timeout=30
        )
        stats = get_pool_stats()
        print(f"  ✅ Pool initialized: {stats['config']['minconn']}-{stats['config']['maxconn']} connections")
        print(f"  📊 Pool status: {stats['idle_connections']} idle, {stats['active_connections']} active")
        print(f"  ⏱️  Connection timeout: {stats['config']['connection_timeout']}s")
    except Exception as e:
        print(f"  ❌ Pool initialization failed: {e}")
        logger.exception("[STARTUP] Database connection pool initialization failed")
        raise RuntimeError("Critical startup failure: database connection pool could not be initialized") from e
    
    print("\n🎯 OPERATIONAL MODES:")
    print("   📊 Conversational: Odoo data + custom agentic tables")
    print("   🤖 Agentic: 11 AI agents (Budget, Approval, Vendor, Risk, Contract, etc.)")
    print("\n📡 API ROUTES REGISTERED:")
    print("   /api/auth/login (POST) - JWT login")
    print("   /api/auth/logout (POST) - JWT logout")
    print("   /api/auth/me (GET) - Current user")
    print("   /api/chat (POST) - Conversational chatbot")
    print("   /api/chat/stream (POST) - SSE streaming")
    print("   /api/suggestions (POST) - Query autocomplete")
    print("   /api/odoo/* - Odoo XML-RPC proxy")
    print("   /api/agentic/* - Agent system (12 endpoints)")
    print("="*80)
    print("✅ SERVER READY - Listening on port 5000")
    print("="*80 + "\n")

    # Start background scheduler (Sprint 9)
    try:
        from backend.services.scheduler_service import start_scheduler
        asyncio.create_task(start_scheduler())
        logger.info("[STARTUP] Background scheduler started.")
    except Exception as _sched_err:
        logger.warning("[STARTUP] Scheduler could not start: %s", _sched_err)


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

