import re

from typing import Any


def semantic_search_tokens(query: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9]+", query.lower()) if len(token) > 1
    ]


def semantic_search_score(query: str, tokens: list[str], text: str) -> int:
    lowered = text.lower()
    score = 0
    phrase = query.strip().lower()

    if phrase and phrase in lowered:
        score += 12

    for token in tokens:
        if token in lowered:
            score += 2
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            score += 3

    return score


def semantic_search_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(semantic_search_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(semantic_search_text(item) for item in value)
    if value is None:
        return ""

    return str(value)
