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

SETTRA_DB_HOST = os.getenv("SETTRA_DB_HOST") or POSTGRES_HOST
SETTRA_DB_PORT = int(os.getenv("SETTRA_DB_PORT") or POSTGRES_PORT)
SETTRA_DB_DATABASE = os.getenv("SETTRA_DB_DATABASE") or POSTGRES_DATABASE
SETTRA_DB_USER = os.getenv("SETTRA_DB_USER") or POSTGRES_USER
SETTRA_DB_PASSWORD = os.getenv("SETTRA_DB_PASSWORD") or POSTGRES_PASSWORD
SETTRA_DB_SCHEMA = os.getenv("SETTRA_DB_SCHEMA", "settra_app").strip()

if not re.fullmatch(r"[a-z_][a-z0-9_]*", SETTRA_DB_SCHEMA):
    raise RuntimeError(
        "SETTRA_DB_SCHEMA must be a lowercase PostgreSQL identifier "
        "containing only letters, numbers, and underscores"
    )
