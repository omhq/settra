import os

from pathlib import Path

from app.common.config import (
    CONFIG_DIR,
    DATA_DIR,
    POSTGRES_DATABASE,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)


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
LEGACY_GOOGLE_DRIVE_KEY = "googlesheets"
LEGACY_GOOGLE_DRIVE_CONFIG_DIR = CONNECTORS_DIR / LEGACY_GOOGLE_DRIVE_KEY
CONNECTION_CONFIG_DIR = Path(
    os.getenv("CONNECTION_CONFIG_DIR", str(DATA_DIR / "connections"))
)
DLT_PIPELINES_DIR = Path(os.getenv("DLT_PIPELINES_DIR", str(DATA_DIR / "dlt")))
GOOGLE_OAUTH_CREDENTIALS_PATH = Path(
    os.getenv(
        "GOOGLE_OAUTH_CREDENTIALS_PATH",
        str(DATA_DIR / "secrets" / "google_oauth.enc"),
    )
)
