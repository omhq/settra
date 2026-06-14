from typing import Any
from pathlib import Path
from string import Template

from app.semantic.consts import CONNECTORS_PATH, SEMANTIC_DIR


def connectors_dir() -> Path:
    config_path = Path(CONNECTORS_PATH)
    repo_path = Path(__file__).resolve().parents[2] / "connectors"

    if SEMANTIC_DIR:
        return Path(SEMANTIC_DIR)

    if config_path.exists():
        return config_path

    if repo_path.exists():
        return repo_path

    return Path(__file__).resolve().parents[1] / "connectors"


def connector_prompt_instructions(
    plugins: list[str] | tuple[str, ...] | set[str],
    scope: str,
    name: str | None = None,
    variables: dict[str, Any] | None = None,
) -> str:
    snippets = connector_prompt_snippets(
        plugins,
        scope,
        name,
        variables=variables,
    )
    if not snippets:
        return ""

    return "Connector-specific instructions:\n" + "\n\n".join(snippets)


def connector_prompt_snippets(
    plugins: list[str] | tuple[str, ...] | set[str],
    scope: str,
    name: str | None = None,
    variables: dict[str, Any] | None = None,
    *,
    include_common: bool = True,
    include_headers: bool = True,
) -> list[str]:
    snippets: list[str] = []
    file_names = [f"{scope}_common.txt"] if include_common else []

    if name:
        file_names.append(f"{scope}_{name}.txt")

    substitutions = _stringify_prompt_variables(variables or {})

    for plugin in _unique_plugins(plugins):
        prompt_dir = connectors_dir() / plugin / "prompts"

        if not prompt_dir.exists():
            continue

        for file_name in file_names:
            path = prompt_dir / file_name

            if not path.exists():
                continue

            content = Template(path.read_text()).safe_substitute(substitutions).strip()

            if content:
                if include_headers:
                    snippets.append(f"[{plugin}]\n{content}")
                else:
                    snippets.append(content)

    return snippets


def _unique_plugins(
    plugins: list[str] | tuple[str, ...] | set[str],
) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []

    for plugin in plugins:
        normalized = str(plugin or "").strip()

        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        unique.append(normalized)

    return unique


def _stringify_prompt_variables(variables: dict[str, Any]) -> dict[str, str]:
    rendered: dict[str, str] = {}

    for key, value in variables.items():
        if value is None:
            rendered[key] = ""
        else:
            rendered[key] = str(value)

    return rendered
