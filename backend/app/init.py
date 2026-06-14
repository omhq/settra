import asyncio
import logging

from dataclasses import dataclass

from app.agent.prompts import (
    AGENT_PROMPT_SEED_PATH,
    PromptConfigError,
    seed_agent_prompts,
)
from app.db import init_db
from app.semantic.loader import load_semantic_layer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InitResult:
    prompt_messages: int
    semantic_counts: dict[str, int]


async def initialize_app() -> InitResult:
    await init_db()

    if not AGENT_PROMPT_SEED_PATH.exists():
        raise PromptConfigError(
            "No agent prompt seed file found. "
            f"Mount or copy prompts/agent.yaml to {AGENT_PROMPT_SEED_PATH}."
        )

    prompt_messages = await seed_agent_prompts(AGENT_PROMPT_SEED_PATH)
    semantic_counts = await load_semantic_layer()

    logger.info(
        "Initialized app database prompt_messages=%s semantic_metadata=%s",
        prompt_messages,
        _format_semantic_counts(semantic_counts),
    )

    return InitResult(
        prompt_messages=prompt_messages,
        semantic_counts=semantic_counts,
    )


async def _main() -> int:
    try:
        result = await initialize_app()
    except PromptConfigError as exc:
        logger.error(f"Could not initialize app: {exc}")
        return 1

    logger.info(
        f"Seeded {result.prompt_messages} agent prompt messages "
        f"from {AGENT_PROMPT_SEED_PATH}"
    )
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
