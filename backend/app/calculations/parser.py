from typing import Any

import yaml
from pydantic import ValidationError

from app.calculations.constants import MAX_CALCULATION_YAML_BYTES
from app.calculations.models import CalculationDefinition
from app.errors import InvalidInputError


def parse_calculation(content: str) -> CalculationDefinition:
    document = _load_calculation_yaml(content)

    try:
        return CalculationDefinition.model_validate(document)
    except ValidationError as exc:
        messages = [_validation_message(error) for error in exc.errors()[:5]]
        suffix = (
            f"; plus {len(exc.errors()) - 5} more errors"
            if len(exc.errors()) > 5
            else ""
        )
        raise InvalidInputError(
            "Invalid calculation definition: " + "; ".join(messages) + suffix,
        ) from exc


def validate_calculation_yaml_draft(content: str) -> str:
    _load_calculation_yaml(content)
    return content.rstrip() + "\n"


def _load_calculation_yaml(content: str) -> dict[str, Any]:
    if len(content.encode("utf-8")) > MAX_CALCULATION_YAML_BYTES:
        raise InvalidInputError("Calculation YAML must be 256 KB or smaller")

    if not content.strip():
        raise InvalidInputError("Calculation YAML cannot be empty")

    try:
        document: Any = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        problem = str(getattr(exc, "problem", "") or "invalid syntax")
        mark = getattr(exc, "problem_mark", None)
        location = (
            f" at line {mark.line + 1}, column {mark.column + 1}"
            if mark is not None
            else ""
        )
        raise InvalidInputError(
            f"Invalid calculation YAML{location}: {problem}",
        ) from exc

    if not isinstance(document, dict):
        raise InvalidInputError("Calculation YAML must contain a mapping")
    return document


def _validation_message(error: dict[str, Any]) -> str:
    location = ".".join(str(part) for part in error.get("loc", ())) or "document"
    message = str(error.get("msg") or "is invalid")
    return f"{location}: {message}"
