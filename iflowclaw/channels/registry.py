from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..types import Channel, OnChatMetadata, OnInboundMessage, RegisteredGroup

ChannelOpts = dict[str, Any]
ChannelFactory = Callable[[ChannelOpts], Channel | None]

_factories: dict[str, ChannelFactory] = {}


def register_channel(name: str, factory: ChannelFactory) -> None:
    _factories[name] = factory


def get_registered_channel_names() -> list[str]:
    return sorted(_factories.keys())


def get_channel_factory(name: str) -> ChannelFactory | None:
    return _factories.get(name)
