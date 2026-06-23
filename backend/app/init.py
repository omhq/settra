import logging
import asyncio

from dataclasses import dataclass

from app.cube.model import sync_cube_model
from app.db import init_db

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InitResult:
    cube_model: dict


async def initialize_app() -> InitResult:
    await init_db()

    cube_model = await sync_cube_model()

    logger.info(
        "Initialized app database cube_model_files=%s",
        len(cube_model.get("files", [])),
    )

    return InitResult(
        cube_model=cube_model,
    )


async def _main() -> int:
    result = await initialize_app()

    logger.info("Cube model ready: " f"files={len(result.cube_model.get('files', []))}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
