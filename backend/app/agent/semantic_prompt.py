import json

from typing import Any

from app.pruning import prune_semantics_for_prompt


def format_semantics_for_prompt(semantics: dict[str, Any]) -> str:
    prompt_semantics = prune_semantics_for_prompt(semantics)
    return json.dumps(prompt_semantics, separators=(",", ":"), default=str)
