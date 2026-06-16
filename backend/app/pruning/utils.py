import re

from typing import Any

from pydantic import BaseModel

from app.pruning.consts import GENERIC_TOKENS


def model_to_prompt_dict(model: BaseModel) -> dict[str, Any]:
    value = model.model_dump(mode="python", by_alias=True, exclude_none=True)
    compacted = strip_empty(value)

    return compacted if isinstance(compacted, dict) else {}


def strip_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return compact_dict({key: strip_empty(item) for key, item in value.items()})
    if isinstance(value, list):
        return [
            item
            for item in (strip_empty(item) for item in value)
            if item not in (None, "", [], {})
        ]

    return value


def compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}


def compact_text(value: Any, max_chars: int) -> str | None:
    if value in (None, ""):
        return None

    text = re.sub(r"\s+", " ", str(value)).strip()

    if not text:
        return None

    if len(text) <= max_chars:
        return text

    return f"{text[: max_chars - 3]}..."


def compact_value(value: Any, *, max_chars: int) -> Any:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, str):
        return compact_text(value, max_chars)
    if isinstance(value, list):
        return [
            item
            for item in (compact_value(item, max_chars=max_chars) for item in value[:8])
            if item not in (None, "", [], {})
        ]
    if isinstance(value, dict):
        return compact_dict(
            {
                key: compact_value(item, max_chars=max_chars)
                for key, item in value.items()
            }
        )

    text = str(value)

    return compact_text(text, max_chars) if len(text) > max_chars else value


def compact_list(value: Any, limit: int) -> list[Any]:
    if not isinstance(value, list):
        return []

    return [
        item
        for item in (compact_value(item, max_chars=90) for item in value[:limit])
        if item not in (None, "", [], {})
    ]


def compact_label(name: Any, label: Any) -> str | None:
    if not label:
        return None

    text = compact_text(label, 80)

    if not text:
        return None

    normalized_name = re.sub(r"[_\s]+", " ", str(name or "")).strip().lower()

    if text.lower() == normalized_name:
        return None

    return text


def tokens(value: str) -> set[str]:
    return {
        singularize(token)
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 1 and token not in GENERIC_TOKENS
    }


def singularize(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def column_flags(column: dict[str, Any]) -> list[str]:
    flags = column.get("flags")

    if isinstance(flags, list):
        return [str(flag) for flag in flags if flag]

    return [
        role
        for key, role in (
            ("is_dimension", "dimension"),
            ("is_measure", "measure"),
            ("is_time", "time"),
            ("is_id", "id"),
            ("is_foreign_key", "foreign_key"),
        )
        if column.get(key)
    ]
