import os
import logging

TRUE_VALUES = {"1", "true", "yes", "on"}


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in TRUE_VALUES


def setup_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    # logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    # logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    # logging.getLogger("litellm").setLevel(logging.WARNING)
