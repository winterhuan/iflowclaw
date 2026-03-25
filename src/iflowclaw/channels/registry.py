from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..types import Channel


@dataclass(slots=True)
class ChannelOpts:
    onMessage: Callable[..., Any] | None = None
    onChatMetadata: Callable[..., Any] | None = None
    registeredGroups: Callable[..., Any] | None = None
    autoRegisterGroup: Callable[..., Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return self.extra.get(key)

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            val = getattr(self, key)
            return val if val is not None else default
        return self.extra.get(key, default)


ChannelFactory = Callable[[ChannelOpts], Channel | None]

_factories: dict[str, ChannelFactory] = {}


def register_channel(name: str, factory: ChannelFactory) -> None:
    _factories[name] = factory


def get_registered_channel_names() -> list[str]:
    return sorted(_factories.keys())


def get_channel_factory(name: str) -> ChannelFactory | None:
    return _factories.get(name)
