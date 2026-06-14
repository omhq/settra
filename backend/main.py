import os
import asyncio

from pathlib import Path
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.chat_jobs import run_chat_worker
from app.common.logging import setup_logging
from app.init import initialize_app
from app.messaging.worker import run_messaging_worker
from app.routers import (
    chat,
    connections,
    health,
    messaging,
    model_configs,
    query,
    runtime_config,
    semantics,
)

setup_logging()


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

    worker_tasks = []

    if os.getenv("CHAT_WORKER", "true").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }:
        worker_tasks.append(asyncio.create_task(run_chat_worker()))

    if os.getenv("MESSAGING_WORKER", "true").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }:
        worker_tasks.append(asyncio.create_task(run_messaging_worker()))

    try:
        yield
    finally:
        for worker_task in worker_tasks:
            worker_task.cancel()
        for worker_task in worker_tasks:
            with suppress(asyncio.CancelledError):
                await worker_task


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(connections.router, prefix="/api")
app.include_router(model_configs.router, prefix="/api")
app.include_router(messaging.router, prefix="/api")
app.include_router(query.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(runtime_config.router, prefix="/api")
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
