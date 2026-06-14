import os

from app.common.config import CONFIG_DIR

SEMANTIC_DIR = os.getenv("SEMANTIC_DIR")
CONNECTORS_PATH = os.getenv("CONNECTORS_PATH", str(CONFIG_DIR / "connectors"))
SEMANTICS_PATH = os.getenv("SEMANTICS_PATH", str(CONFIG_DIR / "semantics"))

TEXT_DATA_TYPES = {
    "char",
    "character",
    "character varying",
    "citext",
    "text",
    "varchar",
}
BOOLEAN_DATA_TYPES = {"bool", "boolean"}
NUMERIC_DATA_TYPES = {
    "bigint",
    "decimal",
    "double precision",
    "integer",
    "numeric",
    "real",
    "smallint",
}
