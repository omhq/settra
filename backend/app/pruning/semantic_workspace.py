from typing import Any

from app.pruning.consts import (
    SEMANTIC_WORKSPACE_KEYS_BY_TYPE,
    SEMANTIC_WORKSPACE_VALUE_LIMIT,
)
from app.pruning.utils import compact_dict, compact_value


def prune_semantic_workspace_result_for_prompt(
    result: dict[str, Any],
) -> dict[str, Any]:
    return SemanticWorkspaceResultPruner(result).payload()


class SemanticWorkspaceResultPruner:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    def payload(self) -> dict[str, Any]:
        result_type = str(self.result.get("type") or "semantic")
        keys = SEMANTIC_WORKSPACE_KEYS_BY_TYPE.get(
            result_type,
            tuple(key for key in self.result.keys() if key not in {"type", "title"}),
        )

        return compact_dict(
            {
                key: compact_value(
                    self.result.get(key),
                    max_chars=SEMANTIC_WORKSPACE_VALUE_LIMIT,
                )
                for key in keys
                if key in self.result
            }
        )
