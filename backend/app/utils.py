import json
import re

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import aiofiles
import yaml


def slugify_name(name: str, *, prefix: str = "conn") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

    if not slug or slug[0].isdigit():
        slug = f"{prefix}_{slug}"

    return slug


def escape_hcl(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def unescape_hcl(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return (
            value.replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\\\", "\\")
        )


def parse_spc_credentials(content: str) -> dict[str, str]:
    creds = {}

    for line in content.splitlines():
        match = re.match(r"^\s+(\w+)\s*=\s*(.+?)\s*$", line)

        if not match or match.group(1) == "plugin":
            continue

        key, raw_value = match.group(1), match.group(2)

        if raw_value.startswith('"') and raw_value.endswith('"'):
            creds[key] = unescape_hcl(raw_value[1:-1])
        elif raw_value.startswith("["):
            try:
                value = json.loads(raw_value)
                if isinstance(value, list):
                    creds[key] = ", ".join(map(str, value))
            except json.JSONDecodeError:
                continue

    return creds


async def load_yaml_file(path: Path) -> dict[str, Any]:
    async with aiofiles.open(path) as f:
        return yaml.safe_load(await f.read()) or {}


def parse_json_payload(payload: str | None) -> dict[str, Any] | None:
    if not payload:
        return None

    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def sse_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(jsonable(payload), default=str)}\n\n"


def extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")

        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])

        raise


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(value))

    for method_name in ("model_dump", "dict", "to_dict"):
        method = getattr(value, method_name, None)
        if not callable(method):
            continue
        try:
            return jsonable(method())
        except Exception:
            continue

    if hasattr(value, "__dict__"):
        try:
            return jsonable(vars(value))
        except Exception:
            pass

    return str(value)
