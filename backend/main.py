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
    query,
    semantics,
)

setup_logging()
logger = logging.getLogger(__name__)


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            if scope["method"] not in {"GET", "HEAD"}:
                raise
            if path.startswith("api/") or Path(path).suffix:
                raise
            return await super().get_response("index.html", scope)


def _frontend_static_dir() -> Path | None:
    candidates = []
    configured_static_dir = os.getenv("STATIC_DIR")

    if configured_static_dir:
        candidates.append(Path(configured_static_dir))

    candidates.extend([Path("/opt/static"), Path("static")])

    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate

    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(connections.router, prefix="/api")
app.include_router(query.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(semantics.router, prefix="/api")

api_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


@app.api_route("/api", methods=api_methods)
@app.api_route("/api/{path:path}", methods=api_methods)
async def api_not_found(path: str = ""):
    raise HTTPException(status_code=404, detail="API route not found")


frontend_static_dir = _frontend_static_dir()

if frontend_static_dir:
    app.mount(
        "/",
        SPAStaticFiles(directory=frontend_static_dir, html=True),
        name="static",
    )
