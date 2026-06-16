import os

from pathlib import Path

from app.common.config import CONFIG_DIR, DATA_DIR


def _default_connectors_dir() -> Path:
    config_path = CONFIG_DIR / "connectors"

    if config_path.exists():
        return config_path

    repo_path = Path(__file__).resolve().parents[3] / "connectors"

    if repo_path.exists():
        return repo_path

    return Path(__file__).resolve().parents[2] / "connectors"


CONNECTORS_DIR = Path(os.getenv("CONNECTORS_DIR", str(_default_connectors_dir())))
STEAMPIPE_CONFIG_DIR = Path(
    os.getenv("STEAMPIPE_CONFIG_DIR", "/home/steampipe/.steampipe/config")
)
STEAMPIPE_HOST = os.getenv("STEAMPIPE_HOST", "steampipe")
STEAMPIPE_PORT = int(os.getenv("STEAMPIPE_PORT", "9193"))
STEAMPIPE_DB_PASSWORD = os.getenv("STEAMPIPE_DB_PASSWORD", "")
STEAMPIPE_RESTART_COMMAND = os.getenv("STEAMPIPE_RESTART_COMMAND", "").strip()
STEAMPIPE_RESTART_TIMEOUT_SECONDS = int(
    os.getenv("STEAMPIPE_RESTART_TIMEOUT_SECONDS", "120")
)
