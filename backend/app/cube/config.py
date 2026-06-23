import os

from pathlib import Path

CUBE_CONF_DIR = Path(os.getenv("CUBE_CONF_DIR", "/cube/conf"))
CUBE_MODEL_DIR = Path(os.getenv("CUBE_MODEL_DIR", str(CUBE_CONF_DIR / "model")))
CUBE_API_URL = os.getenv("CUBE_API_URL", "http://cube:4000/cubejs-api").rstrip("/")
CUBE_API_SECRET = os.getenv("CUBE_API_SECRET", "")
CUBE_API_TIMEOUT_SECONDS = float(os.getenv("CUBE_API_TIMEOUT_SECONDS", "10"))
