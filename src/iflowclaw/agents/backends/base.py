from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


class BackendError(Exception):
    """Base exception for all backend errors."""

    def __init__(self, message: str, *, recoverable: bool = True, partial_output: str = "") -> None:
        super().__init__(message)
        self.recoverable = recoverable
        self.partial_output = partial_output


class BackendNotInstalledError(BackendError):
    """Raised when a backend SDK is not installed."""

    def __init__(self, backend_name: str, package_name: str) -> None:
        super().__init__(
            f"{backend_name} backend requires '{package_name}' package",
            recoverable=False,
        )
        self.backend_name = backend_name
        self.package_name = package_name


class BackendConfigError(BackendError):
    """Raised when backend configuration is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, recoverable=False)


class BackendExecutionError(BackendError):
    """Raised when backend execution fails."""

    def __init__(self, message: str, *, partial_output: str = "") -> None:
        super().__init__(message, recoverable=True, partial_output=partial_output)


class BackendTimeoutError(BackendError):
    """Raised when backend execution times out."""

    def __init__(self, timeout_s: float, *, partial_output: str = "") -> None:
        super().__init__(
            f"Backend execution timed out after {timeout_s}s",
            recoverable=True,
            partial_output=partial_output,
        )
        self.timeout_s = timeout_s


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
