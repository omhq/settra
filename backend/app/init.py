import asyncio
import logging

from dataclasses import dataclass

from app.db import init_db
from app.semantic.loader import load_semantic_layer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InitResult:
    semantic_counts: dict[str, int]


async def initialize_app() -> InitResult:
    await init_db()

    semantic_counts = await load_semantic_layer()

    logger.info(
        "Initialized app database semantic_metadata=%s",
        _format_semantic_counts(semantic_counts),
    )

    return InitResult(
        semantic_counts=semantic_counts,
    )


async def _main() -> int:
    result = await initialize_app()

    logger.info(
        "Loaded semantic metadata: "
        f"{_format_semantic_counts(result.semantic_counts)}"
    )
    return 0


def _format_semantic_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "no semantic files found"

    return ", ".join(f"{plugin}={count}" for plugin, count in sorted(counts.items()))


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
