import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import (
    CSRF_COOKIE_NAME,
    SAFE_METHODS,
    SESSION_COOKIE_NAME,
    load_session,
    reset_current_identity,
    set_current_identity,
    valid_csrf,
)
from app.common.logging import setup_logging
from app.db import close_db
from app.init import initialize_app
from app.sync.scheduler import sync_scheduler
from app.routers import (
    calculations,
    collections,
    connections,
    destinations,
    auth,
    google_login,
    google_oauth,
    health,
    mcp,
    mcp_requests,
    oauth,
    organizations,
    query,
    semantics,
    settings,
)

API_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
SPA_ALLOWED_METHODS = ["GET", "HEAD", "OPTIONS"]
STATIC_DIR = os.getenv("STATIC_DIR")
STATIC_DIR_CANDIDATES = [STATIC_DIR, "/opt/static", "static"]
DEFAULT_CORS_ALLOWED_ORIGINS = ["*"]


setup_logging()
logger = logging.getLogger(__name__)


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            if scope["method"] not in SPA_ALLOWED_METHODS:
                raise
            if path.startswith("api/") or Path(path).suffix:
                raise

            return await super().get_response("index.html", scope)


def _frontend_static_dir() -> Path | None:
    seen = set()

    for static_dir in STATIC_DIR_CANDIDATES:
        if not static_dir:
            continue

        candidate = Path(static_dir)

        if candidate in seen:
            continue

        seen.add(candidate)

        if (candidate / "index.html").is_file():
            return candidate

    return None


def _csv_env(name: str, default: list[str]) -> list[str]:
    configured = [
        item.strip() for item in os.getenv(name, "").split(",") if item.strip()
    ]

    return configured or default


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.mcp_server.session_manager.run():
        await initialize_app()
        await sync_scheduler.start()
        try:
            yield
        finally:
            await sync_scheduler.stop()
            await close_db()


app = FastAPI(lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled request exception method=%s path=%s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Unexpected server error."},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=_csv_env("CORS_ALLOWED_ORIGINS", DEFAULT_CORS_ALLOWED_ORIGINS),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

PUBLIC_API_PATHS = {
    "/api/auth/config",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/google/start",
    "/api/auth/google/callback",
    "/api/google-oauth/callback",
    "/api/settings/product",
}


@app.middleware("http")
async def normalize_and_authorize_mcp_path(request: Request, call_next):
    if request.scope.get("path") == "/mcp":
        request.scope["path"] = "/mcp/"
        request.scope["raw_path"] = b"/mcp/"

    if str(request.scope.get("path", "")).startswith("/mcp"):
        if request.method == "OPTIONS":
            return await call_next(request)

        auth_response = await oauth.authorize_mcp_request(request)
        if auth_response is not None:
            return auth_response

        identity = getattr(request.state, "identity", None)
        if identity is None:
            return oauth.mcp_auth_challenge(request)

        identity_token = set_current_identity(identity)
        try:
            return await call_next(request)
        finally:
            reset_current_identity(identity_token)

    path = str(request.scope.get("path", ""))
    if path.startswith("/api") and path not in PUBLIC_API_PATHS:
        if request.method == "OPTIONS":
            return await call_next(request)

        session = await load_session(request.cookies.get(SESSION_COOKIE_NAME, ""))
        if session is None:
            return JSONResponse(
                status_code=401, content={"detail": "Authentication required"}
            )

        if request.method not in SAFE_METHODS and not valid_csrf(
            session,
            request.cookies.get(CSRF_COOKIE_NAME, ""),
            request.headers.get("x-csrf-token", ""),
        ):
            return JSONResponse(
                status_code=403, content={"detail": "Invalid CSRF token"}
            )

        request.state.identity = session.identity
        request.state.session = session
        identity_token = set_current_identity(session.identity)
        try:
            response = await call_next(request)
            response.headers.setdefault("Cache-Control", "private, no-store")
            return response
        finally:
            reset_current_identity(identity_token)

    return await call_next(request)


app.include_router(oauth.router)
app.include_router(auth.router, prefix="/api")
app.include_router(google_login.router, prefix="/api")
app.include_router(organizations.router, prefix="/api")
app.include_router(google_oauth.router, prefix="/api")
app.include_router(calculations.router, prefix="/api")
app.include_router(collections.router, prefix="/api")
app.include_router(connections.router, prefix="/api")
app.include_router(destinations.router, prefix="/api")
app.include_router(query.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(semantics.router, prefix="/api")
app.include_router(mcp_requests.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.mount("/mcp", mcp.mcp_app)


@app.api_route("/api", methods=API_METHODS)
@app.api_route("/api/{path:path}", methods=API_METHODS)
async def api_not_found(path: str = ""):
    raise HTTPException(status_code=404, detail="API route not found")


frontend_static_dir = _frontend_static_dir()

if frontend_static_dir:
    app.mount(
        "/",
        SPAStaticFiles(directory=frontend_static_dir, html=True),
        name="static",
    )
