import json

from pathlib import Path
from string import Template
from typing import Any

import yaml
import aiosqlite

from app.common.config import CONFIG_DIR, DB_PATH
from app.connector_prompts import connector_prompt_instructions

AGENT_PROMPT_SEED_PATH = CONFIG_DIR / "prompts" / "agent.yaml"
PROMPT_KEYS = {
    "intent_router",
    "table_selector",
    "sql_agent_step",
    "sql_planner",
    "sql_repairer",
    "sql_reviewer",
    "answer_writer",
}
PROMPT_ROLES = {"system", "user", "assistant"}


class PromptConfigError(RuntimeError):
    pass


async def render_prompt_messages(
    prompt_key: str,
    variables: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            """
            SELECT role, content
            FROM agent_prompts
            WHERE prompt_key = ?
            ORDER BY position ASC, id ASC
            """,
            (prompt_key,),
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        raise PromptConfigError(
            f"Missing agent prompt '{prompt_key}'. "
            "Run make init after adding a local prompt seed file."
        )

    prompt_variables = dict(variables or {})
    prompt_variables.setdefault(
        "connector_prompt_instructions",
        connector_prompt_instructions(
            _connector_plugins_from_variables(prompt_variables),
            "agent",
            prompt_key,
        ),
    )
    substitutions = _stringify_prompt_variables(prompt_variables)
    messages = []

    for row in rows:
        content = Template(row["content"]).safe_substitute(substitutions)
        messages.append({"role": row["role"], "content": content})

    return messages


async def seed_agent_prompts(path: Path) -> int:
    data = yaml.safe_load(path.read_text()) or {}
    rows = _prompt_rows(data)

    if not rows:
        raise PromptConfigError("Prompt seed did not contain any prompt messages.")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM agent_prompts")
        await db.executemany(
            """
            INSERT INTO agent_prompts (prompt_key, role, content, position)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )
        await db.commit()

    return len(rows)


def _prompt_rows(data: dict[str, Any]) -> list[tuple[str, str, str, int]]:
    prompt_map = data.get("prompts", data)

    if not isinstance(prompt_map, dict):
        raise PromptConfigError(
            "Prompt seed must be a mapping or contain a prompts mapping."
        )

    missing = PROMPT_KEYS - set(prompt_map)

    if missing:
        raise PromptConfigError(
            f"Prompt seed is missing required prompts: {', '.join(sorted(missing))}."
        )

    rows: list[tuple[str, str, str, int]] = []

    for prompt_key, raw_prompt in prompt_map.items():
        if not isinstance(prompt_key, str) or not prompt_key.strip():
            raise PromptConfigError("Prompt keys must be non-empty strings.")

        messages = _messages_for_prompt(raw_prompt)
        used_positions: set[int] = set()

        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                raise PromptConfigError(
                    f"Prompt '{prompt_key}' message {index} must be a mapping."
                )

            role = str(message.get("role") or "").strip()
            content = str(message.get("content") or "")
            position = int(message.get("position", index))

            if role not in PROMPT_ROLES:
                raise PromptConfigError(
                    f"Prompt '{prompt_key}' message {index} "
                    f"has unsupported role '{role}'."
                )
            if not content.strip():
                raise PromptConfigError(
                    f"Prompt '{prompt_key}' message {index} has empty content."
                )
            if position in used_positions:
                raise PromptConfigError(
                    f"Prompt '{prompt_key}' has duplicate position {position}."
                )

            used_positions.add(position)
            rows.append((prompt_key, role, content, position))

    return rows


def _messages_for_prompt(raw_prompt: Any) -> list[dict[str, Any]]:
    if isinstance(raw_prompt, list):
        return raw_prompt

    if isinstance(raw_prompt, dict):
        if isinstance(raw_prompt.get("messages"), list):
            return raw_prompt["messages"]
        if "role" in raw_prompt or "content" in raw_prompt:
            return [raw_prompt]

    raise PromptConfigError(
        "Each prompt must be a message list, a mapping with messages, "
        "or a single message mapping."
    )


def _stringify_prompt_variables(variables: dict[str, Any]) -> dict[str, str]:
    rendered: dict[str, str] = {}

    for key, value in variables.items():
        if value is None:
            rendered[key] = ""
        elif isinstance(value, str):
            rendered[key] = value
        elif isinstance(value, (dict, list, tuple)):
            rendered[key] = json.dumps(value, indent=2, default=str)
        else:
            rendered[key] = str(value)

    return rendered


def _connector_plugins_from_variables(variables: dict[str, Any]) -> list[str]:
    for key in ("connector_plugins", "plugins"):
        value = variables.get(key)
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value if str(item or "").strip()]

    connections = variables.get("connections")
    if isinstance(connections, list):
        return [
            str(connection.get("plugin"))
            for connection in connections
            if isinstance(connection, dict) and connection.get("plugin")
        ]

    return []
