import os
import re

from pathlib import Path

CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/config"))
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DATABASE = os.getenv("POSTGRES_DATABASE", "settra")
POSTGRES_USER = os.getenv("POSTGRES_USER", "settra")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "settra")

APP_DB_HOST = os.getenv("APP_DB_HOST") or POSTGRES_HOST
APP_DB_PORT = int(os.getenv("APP_DB_PORT") or POSTGRES_PORT)
APP_DB_DATABASE = os.getenv("APP_DB_DATABASE") or POSTGRES_DATABASE
APP_DB_USER = os.getenv("APP_DB_USER") or POSTGRES_USER
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD") or POSTGRES_PASSWORD
APP_DB_SCHEMA = os.getenv("APP_DB_SCHEMA", "settra_app").strip()

if not re.fullmatch(r"[a-z_][a-z0-9_]*", APP_DB_SCHEMA):
    raise RuntimeError(
        "APP_DB_SCHEMA must be a lowercase PostgreSQL identifier "
        "containing only letters, numbers, and underscores"
    )


def deployment_mode() -> str:
    configured = os.getenv("DEPLOYMENT_MODE", "self_hosted").strip().lower()

    return "managed" if configured == "managed" else "self_hosted"
