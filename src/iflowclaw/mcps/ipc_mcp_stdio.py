"""
Stdio MCP Server for iFlowClaw
Standalone process that agent backends connect to.
Reads context from environment variables, writes IPC files for the host.
"""

from __future__ import annotations

import json
import os
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Context from environment variables
CHAT_JID = os.environ.get("IFLOWCLAW_CHAT_JID") or ""
GROUP_FOLDER = os.environ.get("IFLOWCLAW_GROUP_FOLDER") or ""
IS_MAIN = os.environ.get("IFLOWCLAW_IS_MAIN") == "1"
IPC_DIR = os.environ.get("IFLOWCLAW_IPC_DIR") or "/workspace/ipc"

MESSAGES_DIR = Path(IPC_DIR) / "messages"
TASKS_DIR = Path(IPC_DIR) / "tasks"


def write_ipc_file(dir_path: Path, data: dict[str, Any]) -> str:
    """原子写入 IPC 文件"""
    dir_path.mkdir(parents=True, exist_ok=True)
    filename = f"{int(time.time() * 1000)}-{random.random():.8f}".replace(".", "") + ".json"
    file_path = dir_path / filename
    tmp = file_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(file_path)
    return filename


def read_tasks_snapshot() -> list[dict[str, Any]]:
    """读取任务快照"""
    path = Path(IPC_DIR) / "current_tasks.json"
    if not path.exists():
        path = Path(IPC_DIR).parent / "current_tasks.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, Exception):
        return []


def _require_croniter():
    try:
        from croniter import croniter
    except ImportError as e:
        raise RuntimeError("cron schedules require the 'croniter' package") from e
    return croniter


def main() -> int:
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as e:
        raise SystemExit(f"mcp not installed: {e}")

    mcp = FastMCP(name="iflowclaw")

    @mcp.tool()
    def send_message(text: str, sender: str | None = None) -> str:
        """Send a message to the user or group immediately while you're still running."""
        data: dict[str, Any] = {
            "type": "message",
            "chatJid": CHAT_JID,
            "text": text,
            "sender": sender,
            "groupFolder": GROUP_FOLDER,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        write_ipc_file(MESSAGES_DIR, data)
        return "Message sent."

    @mcp.tool()
    def schedule_task(
        prompt: str,
        schedule_type: str,
        schedule_value: str,
        context_mode: str = "group",
        target_group_jid: str | None = None,
    ) -> str:
        """Schedule a recurring or one-time task."""
        if schedule_type == "cron":
            croniter = _require_croniter()
            if not croniter.is_valid(schedule_value):
                raise ValueError(f'Invalid cron: "{schedule_value}"')
        elif schedule_type == "interval":
            ms = int(schedule_value)
            if ms <= 0:
                raise ValueError(f'Invalid interval: "{schedule_value}"')
        elif schedule_type == "once":
            if schedule_value.endswith("Z") or "+" in schedule_value or "-" in schedule_value[10:]:
                raise ValueError("Timestamp must be local time without timezone suffix")
            dt = datetime.fromisoformat(schedule_value)
            if dt.tzinfo is not None:
                raise ValueError("Timestamp must be naive local time")
        else:
            raise ValueError(f"Unknown schedule_type: {schedule_type}")

        data = {
            "type": "schedule_task",
            "prompt": prompt,
            "schedule_type": schedule_type,
            "schedule_value": schedule_value,
            "context_mode": context_mode,
            "targetJid": target_group_jid or CHAT_JID,
            "createdBy": GROUP_FOLDER,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        write_ipc_file(TASKS_DIR, data)
        return f"Task scheduled: {schedule_type} - {schedule_value}"

    @mcp.tool()
    def list_tasks() -> str:
        """List all scheduled tasks."""
        tasks = read_tasks_snapshot()
        if not IS_MAIN:
            tasks = [t for t in tasks if t.get("groupFolder") == GROUP_FOLDER]
        if not tasks:
            return "No scheduled tasks found."
        lines = []
        for t in tasks:
            prompt = str(t.get("prompt", ""))[:50]
            sched = t.get("schedule_type")
            val = t.get("schedule_value")
            status = t.get("status")
            next_run = t.get("next_run") or "N/A"
            lines.append(f"- [{t.get('id')}] {prompt}... ({sched}: {val}) - {status}, next: {next_run}")
        return "Scheduled tasks:\n" + "\n".join(lines)

    @mcp.tool()
    def pause_task(task_id: str) -> str:
        """Pause a scheduled task."""
        data = {
            "type": "pause_task",
            "taskId": task_id,
            "groupFolder": GROUP_FOLDER,
            "isMain": IS_MAIN,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        write_ipc_file(TASKS_DIR, data)
        return f"Task {task_id} pause requested."

    @mcp.tool()
    def resume_task(task_id: str) -> str:
        """Resume a paused task."""
        data = {
            "type": "resume_task",
            "taskId": task_id,
            "groupFolder": GROUP_FOLDER,
            "isMain": IS_MAIN,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        write_ipc_file(TASKS_DIR, data)
        return f"Task {task_id} resume requested."

    @mcp.tool()
    def cancel_task(task_id: str) -> str:
        """Cancel and delete a scheduled task."""
        data = {
            "type": "cancel_task",
            "taskId": task_id,
            "groupFolder": GROUP_FOLDER,
            "isMain": IS_MAIN,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        write_ipc_file(TASKS_DIR, data)
        return f"Task {task_id} cancellation requested."

    @mcp.tool()
    def update_task(
        task_id: str,
        prompt: str | None = None,
        schedule_type: str | None = None,
        schedule_value: str | None = None,
    ) -> str:
        """Update an existing scheduled task."""
        if schedule_type == "cron" and schedule_value is not None:
            croniter = _require_croniter()
            if not croniter.is_valid(schedule_value):
                raise ValueError(f'Invalid cron: "{schedule_value}"')
        if schedule_type == "interval" and schedule_value is not None:
            ms = int(schedule_value)
            if ms <= 0:
                raise ValueError(f'Invalid interval: "{schedule_value}"')
        if schedule_type == "once" and schedule_value is not None:
            if schedule_value.endswith("Z") or "+" in schedule_value or "-" in schedule_value[10:]:
                raise ValueError("Timestamp must be local time without timezone suffix")
            dt = datetime.fromisoformat(schedule_value)
            if dt.tzinfo is not None:
                raise ValueError("Timestamp must be naive local time")

        data: dict[str, Any] = {
            "type": "update_task",
            "taskId": task_id,
            "groupFolder": GROUP_FOLDER,
            "isMain": IS_MAIN,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        if prompt is not None:
            data["prompt"] = prompt
        if schedule_type is not None:
            data["schedule_type"] = schedule_type
        if schedule_value is not None:
            data["schedule_value"] = schedule_value
        write_ipc_file(TASKS_DIR, data)
        return f"Task {task_id} update requested."

    @mcp.tool()
    def register_group(jid: str, name: str, folder: str, trigger: str) -> str:
        """Register a new chat/group (main group only)."""
        if not IS_MAIN:
            raise PermissionError("Only the main group can register new groups.")
        data = {
            "type": "register_group",
            "jid": jid,
            "name": name,
            "folder": folder,
            "trigger": trigger,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        write_ipc_file(TASKS_DIR, data)
        return f'Group "{name}" registered.'

    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
