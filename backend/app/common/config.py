import os

from pathlib import Path

CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/config"))
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "app.db")))
