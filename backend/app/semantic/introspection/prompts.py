import json

from pathlib import Path
from typing import Any

from app.common.config import CONFIG_DIR
from app.connector_prompts import connector_prompt_instructions

PROMPT_DIR = CONFIG_DIR / "prompts" / "semantic" / "introspection"


class SemanticPromptConfigError(RuntimeError):
    pass


def _prompt_path(name: str) -> Path:
    if not PROMPT_DIR.exists():
        raise SemanticPromptConfigError(
            f"Semantic introspection prompt directory does not exist: {PROMPT_DIR}. "
            "Mount or copy prompts/semantic/introspection to /config/prompts."
        )

    path = PROMPT_DIR / name

    if not path.exists():
        raise SemanticPromptConfigError(
            f"Missing semantic introspection prompt template: {path}"
        )

    return path


def render_prompt_messages(
    flow: str,
    context_payload: dict[str, Any],
    *,
    connector_plugins: list[str],
) -> list[dict[str, str]]:
    variables = {
        "context_json": json.dumps(context_payload, separators=(",", ":")),
        "connector_prompt_instructions": connector_prompt_instructions(
            connector_plugins,
            "introspection",
            flow,
        ),
    }

    return [
        {
            "role": "system",
            "content": _render_template(f"{flow}_system.txt", variables),
        },
        {
            "role": "user",
            "content": _render_template(f"{flow}_user.txt", variables),
        },
    ]


def _render_template(name: str, variables: dict[str, str]) -> str:
    content = _prompt_path(name).read_text()

    for key, value in variables.items():
        content = content.replace(f"{{{{{key}}}}}", value)

    return "\n".join(line for line in content.strip().splitlines() if line.strip())
