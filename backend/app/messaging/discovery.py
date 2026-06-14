import os
import yaml
import importlib.util

from typing import Any
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass

from app.common.config import CONFIG_DIR
from app.messaging.base import MessagingProvider, MessagingProviderError


@dataclass(frozen=True)
class ChannelDefinition:
    key: str
    name: str
    description: str
    path: Path
    provider_module: str
    provider_class: str
    delivery_modes: list[str]
    fields: list[dict[str, Any]]
    manifest: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "delivery_modes": self.delivery_modes,
            "fields": self.fields,
        }


def channels_dir() -> Path:
    configured = os.getenv("CHANNELS_DIR")

    if configured:
        return Path(configured)

    default_path = CONFIG_DIR / "channels"

    if default_path.exists():
        return default_path

    return Path(__file__).resolve().parents[3] / "channels"


def list_channel_definitions() -> list[ChannelDefinition]:
    root = channels_dir()

    if not root.exists():
        return []

    definitions: list[ChannelDefinition] = []

    for manifest_path in sorted(
        [*root.glob("*/channel.yaml"), *root.glob("*/channel.yml")]
    ):
        definition = _load_definition(manifest_path)

        if definition:
            definitions.append(definition)

    return definitions


def get_channel_definition(key: str) -> ChannelDefinition:
    definitions = {
        definition.key: definition for definition in list_channel_definitions()
    }

    try:
        return definitions[key]
    except KeyError as exc:
        raise MessagingProviderError(f"Unknown messaging channel: {key}") from exc


@lru_cache(maxsize=32)
def load_provider(key: str) -> MessagingProvider:
    definition = get_channel_definition(key)
    module_path = definition.path / f"{definition.provider_module}.py"

    if not module_path.exists():
        raise MessagingProviderError(
            f"Messaging channel {key} is missing {definition.provider_module}.py"
        )

    module_name = f"settra_channel_{key}_{abs(hash(module_path))}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)

    if spec is None or spec.loader is None:
        raise MessagingProviderError(f"Could not load messaging channel: {key}")

    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    provider_class = getattr(module, definition.provider_class, None)

    if provider_class is None:
        raise MessagingProviderError(
            f"Messaging channel {key} is missing class {definition.provider_class}"
        )

    provider = provider_class()

    if not isinstance(provider, MessagingProvider):
        raise MessagingProviderError(
            f"Messaging channel {key} provider must extend MessagingProvider"
        )

    return provider


def _load_definition(manifest_path: Path) -> ChannelDefinition | None:
    data = yaml.safe_load(manifest_path.read_text()) or {}
    key = str(data.get("key") or manifest_path.parent.name).strip()

    if not key:
        return None

    return ChannelDefinition(
        key=key,
        name=str(data.get("name") or key),
        description=str(data.get("description") or ""),
        path=manifest_path.parent,
        provider_module=str(data.get("provider_module") or "provider"),
        provider_class=str(data.get("provider_class") or "Provider"),
        delivery_modes=list(data.get("delivery_modes") or []),
        fields=list(data.get("fields") or []),
        manifest=data,
    )
