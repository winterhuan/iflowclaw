from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AppConfig
from .group_folder import resolve_group_ipc_path


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


def get_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="send_message",
            description="Send a message immediately while the agent is still running.",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "sender": {"type": "string"},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="schedule_task",
            description="Schedule a recurring or one-time task.",
            input_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "schedule_type": {"type": "string", "enum": ["cron", "interval", "once"]},
                    "schedule_value": {"type": "string"},
                    "context_mode": {"type": "string", "enum": ["group", "isolated"]},
                    "target_group_jid": {"type": "string"},
                },
                "required": ["prompt", "schedule_type", "schedule_value"],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="list_tasks",
            description="List scheduled tasks.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        ToolSpec(
            name="pause_task",
            description="Pause a scheduled task.",
            input_schema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="resume_task",
            description="Resume a paused task.",
            input_schema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="cancel_task",
            description="Cancel a scheduled task.",
            input_schema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="update_task",
            description="Update an existing scheduled task.",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "prompt": {"type": "string"},
                    "schedule_type": {"type": "string", "enum": ["cron", "interval", "once"]},
                    "schedule_value": {"type": "string"},
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="register_group",
            description="Register a new group chat (main group only).",
            input_schema={
                "type": "object",
                "properties": {
                    "jid": {"type": "string"},
                    "name": {"type": "string"},
                    "folder": {"type": "string"},
                    "trigger": {"type": "string"},
                },
                "required": ["jid", "name", "folder", "trigger"],
                "additionalProperties": False,
            },
        ),
    ]


def anthropic_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in get_tool_specs()
    ]


class IpcToolWriter:
    def __init__(
        self,
        config: AppConfig,
        *,
        group_folder: str,
        chat_jid: str,
        is_main: bool,
    ) -> None:
        self._config = config
        self._group_folder = group_folder
        self._chat_jid = chat_jid
        self._is_main = is_main

        ipc_override = os.environ.get("IFLOWCLAW_IPC_DIR")
        base = Path(ipc_override).resolve() if ipc_override else resolve_group_ipc_path(config, group_folder)
        self._messages_dir = (base / "messages").resolve()
        self._tasks_dir = (base / "tasks").resolve()

    def write_message(self, *, text: str, sender: str | None = None) -> None:
        payload: dict[str, Any] = {
            "type": "message",
            "chatJid": self._chat_jid,
            "text": text,
            "sender": sender,
            "groupFolder": self._group_folder,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        }
        self._write_json(self._messages_dir, payload)

    def write_task(self, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload.setdefault("groupFolder", self._group_folder)
        payload.setdefault("isMain", bool(self._is_main))
        payload.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z")
        self._write_json(self._tasks_dir, payload)

    def read_tasks_snapshot(self) -> list[dict[str, Any]]:
        ipc_override = os.environ.get("IFLOWCLAW_IPC_DIR")
        if ipc_override:
            base = Path(ipc_override).resolve()
            path = (base.parent / "current_tasks.json") if base.name == self._group_folder else (base / "current_tasks.json")
        else:
            path = (self._config.data_dir / "ipc" / "current_tasks.json").resolve()
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except Exception:
            return []

    def _write_json(self, dir_path: Path, data: dict[str, Any]) -> str:
        dir_path.mkdir(parents=True, exist_ok=True)
        filename = f"{int(time.time() * 1000)}-{random.random():.8f}".replace(".", "") + ".json"
        file_path = dir_path / filename
        tmp = file_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(file_path)
        return filename


def execute_local_tool(
    *,
    config: AppConfig,
    group_folder: str,
    chat_jid: str,
    is_main: bool,
    tool_name: str,
    tool_input: dict[str, Any],
) -> str:
    writer = IpcToolWriter(config, group_folder=group_folder, chat_jid=chat_jid, is_main=is_main)

    if tool_name == "send_message":
        text = tool_input.get("text")
        sender = tool_input.get("sender")
        if not isinstance(text, str) or not text:
            raise ValueError("send_message.text required")
        writer.write_message(text=text, sender=sender if isinstance(sender, str) else None)
        return "Message sent."

    if tool_name == "schedule_task":
        writer.write_task(
            {
                "type": "schedule_task",
                "prompt": tool_input.get("prompt"),
                "schedule_type": tool_input.get("schedule_type"),
                "schedule_value": tool_input.get("schedule_value"),
                "context_mode": tool_input.get("context_mode") or "group",
                "target_group_jid": tool_input.get("target_group_jid"),
            }
        )
        return "Task scheduled."

    if tool_name == "list_tasks":
        tasks = writer.read_tasks_snapshot()
        if not is_main:
            tasks = [t for t in tasks if t.get("groupFolder") == group_folder]
        if not tasks:
            return "No scheduled tasks found."
        lines = []
        for t in tasks:
            lines.append(
                f"- [{t.get('id')}] {str(t.get('prompt',''))[:50]}... "
                f"({t.get('schedule_type')}: {t.get('schedule_value')}) - {t.get('status')}, next: {t.get('next_run') or 'N/A'}"
            )
        return "Scheduled tasks:\n" + "\n".join(lines)

    if tool_name in {"pause_task", "resume_task", "cancel_task"}:
        task_id = tool_input.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id required")
        typ = {"pause_task": "pause_task", "resume_task": "resume_task", "cancel_task": "cancel_task"}[tool_name]
        writer.write_task({"type": typ, "taskId": task_id})
        return f"Task {task_id} {tool_name} requested."

    if tool_name == "update_task":
        task_id = tool_input.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id required")
        payload: dict[str, Any] = {"type": "update_task", "taskId": task_id}
        for k in ("prompt", "schedule_type", "schedule_value"):
            if k in tool_input:
                payload[k] = tool_input[k]
        writer.write_task(payload)
        return f"Task {task_id} update requested."

    if tool_name == "register_group":
        if not is_main:
            raise PermissionError("Only main group can register new groups")
        writer.write_task(
            {
                "type": "register_group",
                "jid": tool_input.get("jid"),
                "name": tool_input.get("name"),
                "folder": tool_input.get("folder"),
                "trigger": tool_input.get("trigger"),
            }
        )
        return "Group registered."

    raise ValueError(f"unknown tool: {tool_name}")
