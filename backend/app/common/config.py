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


def _default_connectors_dir() -> Path:
    config_path = CONFIG_DIR / "connectors"
    if config_path.exists():
        return config_path

    repo_path = Path(__file__).resolve().parents[3] / "connectors"
    if repo_path.exists():
        return repo_path

    return Path(__file__).resolve().parents[2] / "connectors"


CONNECTORS_DIR = Path(os.getenv("CONNECTORS_DIR", str(_default_connectors_dir())))
GOOGLE_DRIVE_KEY = "googledrive"
GOOGLE_DRIVE_CONFIG_DIR = CONNECTORS_DIR / GOOGLE_DRIVE_KEY
CONNECTION_CONFIG_DIR = Path(
    os.getenv("CONNECTION_CONFIG_DIR", str(DATA_DIR / "connections"))
)
DLT_PIPELINES_DIR = Path(os.getenv("DLT_PIPELINES_DIR", str(DATA_DIR / "dlt")))
GOOGLE_OAUTH_CREDENTIALS_DIR = Path(
    os.getenv(
        "GOOGLE_OAUTH_CREDENTIALS_DIR",
        str(DATA_DIR / "secrets" / "organizations"),
    )
)

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
