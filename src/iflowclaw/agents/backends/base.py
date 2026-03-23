from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class BackendContext:
    group_folder: str
    chat_jid: str
    is_main: bool
    session_id: str | None
    group_dir: str
    ipc_dir: str
    system_prompt: str | None
    timeout_s: float


StreamCallback = Callable[[str], Awaitable[None]]


class AgentBackend(Protocol):
    name: str

    async def run(
        self,
        *,
        user_prompt: str,
        context: BackendContext,
        on_stream: StreamCallback | None = None,
    ) -> BackendResult: ...


@dataclass(slots=True)
class BackendResult:
    status: str
    text: str
    new_session_id: str | None = None
    error: str | None = None
