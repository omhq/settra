import os
import logging

from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.logging import setup_logging
from app.init import initialize_app
from app.routers import (
    connections,
    health,
    mcp,
    mcp_requests,
    oauth,
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
        yield


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
        content={
            "detail": {
                "message": "Unexpected server error.",
                "operation": "api_request",
                "error": f"{exc.__class__.__name__}: {exc}",
                "retryable": False,
            }
        },
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=_csv_env("CORS_ALLOWED_ORIGINS", DEFAULT_CORS_ALLOWED_ORIGINS),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def normalize_and_authorize_mcp_path(request: Request, call_next):
    if request.scope.get("path") == "/mcp":
        request.scope["path"] = "/mcp/"
        request.scope["raw_path"] = b"/mcp/"

    if str(request.scope.get("path", "")).startswith("/mcp"):
        auth_response = oauth.authorize_mcp_request(request)
        if auth_response is not None:
            return auth_response

    return await call_next(request)


app.include_router(oauth.router)
app.include_router(connections.router, prefix="/api")
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
