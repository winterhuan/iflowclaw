from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

# --- Constants ---
MAIN_GROUP_NAME = "main"
MAIN_GROUP_FOLDER = "main"

STATUS_SUCCESS = "success"
STATUS_ERROR = "error"

EXECUTION_MODE_DIRECT = "direct"
EXECUTION_MODE_CONTAINER = "container"

# --- Type Aliases ---
ScheduleType = Literal["cron", "interval", "once"]
ContextMode = Literal["group", "isolated"]
TaskStatus = Literal["active", "paused", "running", "completed"]
ExecutionMode = Literal["direct", "container"]


@dataclass(slots=True)
class AgentConfig:
    timeout: int | None = None
    backend: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    execution_mode: ExecutionMode | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RegisteredGroup:
    name: str
    folder: str
    trigger: str
    added_at: str
    requires_trigger: bool | None = True
    is_main: bool | None = None
    agent_config: AgentConfig | None = None


@dataclass(slots=True)
class AvailableGroup:
    jid: str
    name: str
    last_activity: str
    is_registered: bool


@dataclass(slots=True)
class NewMessage:
    id: str
    chat_jid: str
    sender: str
    sender_name: str
    content: str
    timestamp: str
    is_from_me: bool = False
    is_bot_message: bool = False


@dataclass(slots=True)
class ScheduledTask:
    id: str
    group_folder: str
    chat_jid: str
    prompt: str
    schedule_type: ScheduleType
    schedule_value: str
    context_mode: ContextMode
    next_run: str | None
    last_run: str | None
    last_result: str | None
    status: TaskStatus
    created_at: str


@dataclass(slots=True)
class TaskRunLog:
    task_id: str
    run_at: str
    duration_ms: int
    status: Literal["success", "error"]
    result: str | None
    error: str | None


@dataclass(slots=True)
class ChatInfo:
    jid: str
    name: str
    last_message_time: str
    channel: str | None
    is_group: int


@dataclass(slots=True)
class AgentInput:
    prompt: str
    group_folder: str
    chat_jid: str
    is_main: bool
    session_id: str | None = None
    is_scheduled_task: bool = False
    assistant_name: str | None = None
    extension_input: dict[str, Any] = field(default_factory=dict)


class Channel(Protocol):
    name: str

    async def connect(self) -> None: ...

    async def send_message(self, jid: str, text: str) -> None: ...

    def is_connected(self) -> bool: ...

    def owns_jid(self, jid: str) -> bool: ...

    async def disconnect(self) -> None: ...

    async def set_typing(self, jid: str, is_typing: bool) -> None: ...


OnInboundMessage = Callable[[str, NewMessage], None]
OnChatMetadata = Callable[[str, str, str | None, str | None, bool | None], None]
