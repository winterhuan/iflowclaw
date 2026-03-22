from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from croniter import croniter

from ..config import load_config
from ..tools import IpcToolWriter


def main() -> int:
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as e:
        raise SystemExit(f"mcp not installed: {e}")

    chat_jid = os.environ.get("IFLOWCLAW_CHAT_JID") or ""
    group_folder = os.environ.get("IFLOWCLAW_GROUP_FOLDER") or ""
    is_main = os.environ.get("IFLOWCLAW_IS_MAIN") == "1"
    ipc_dir = os.environ.get("IFLOWCLAW_IPC_DIR") or ""

    project_root: Path | None = None
    if ipc_dir:
        p = Path(ipc_dir).resolve()
        if p.name == group_folder and len(p.parents) >= 3:
            project_root = p.parents[2]
        elif p.name == "ipc" and len(p.parents) >= 2:
            project_root = p.parents[1]

    config = load_config(project_root)

    writer = IpcToolWriter(config, group_folder=group_folder, chat_jid=chat_jid, is_main=is_main)

    mcp = FastMCP(name="iflowclaw")

    @mcp.tool()
    def send_message(text: str, sender: str | None = None) -> str:
        writer.write_message(text=text, sender=sender)
        return "Message sent."

    @mcp.tool()
    def schedule_task(
        prompt: str,
        schedule_type: str,
        schedule_value: str,
        context_mode: str = "group",
        target_group_jid: str | None = None,
    ) -> str:
        if schedule_type == "cron":
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
            _ = dt.replace(tzinfo=ZoneInfo(config.timezone))
        else:
            raise ValueError(f"Unknown schedule_type: {schedule_type}")

        writer.write_task(
            {
                "type": "schedule_task",
                "prompt": prompt,
                "schedule_type": schedule_type,
                "schedule_value": schedule_value,
                "context_mode": context_mode,
                "targetJid": target_group_jid or chat_jid,
                "createdBy": group_folder,
            }
        )
        return f"Task scheduled: {schedule_type} - {schedule_value}"

    @mcp.tool()
    def list_tasks() -> str:
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

    @mcp.tool()
    def pause_task(task_id: str) -> str:
        writer.write_task({"type": "pause_task", "taskId": task_id})
        return f"Task {task_id} pause requested."

    @mcp.tool()
    def resume_task(task_id: str) -> str:
        writer.write_task({"type": "resume_task", "taskId": task_id})
        return f"Task {task_id} resume requested."

    @mcp.tool()
    def cancel_task(task_id: str) -> str:
        writer.write_task({"type": "cancel_task", "taskId": task_id})
        return f"Task {task_id} cancel requested."

    @mcp.tool()
    def update_task(
        task_id: str,
        prompt: str | None = None,
        schedule_type: str | None = None,
        schedule_value: str | None = None,
    ) -> str:
        if schedule_type == "cron" and schedule_value is not None:
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
            _ = dt.replace(tzinfo=ZoneInfo(config.timezone))

        payload: dict[str, str] = {"type": "update_task", "taskId": task_id}
        if prompt is not None:
            payload["prompt"] = prompt
        if schedule_type is not None:
            payload["schedule_type"] = schedule_type
        if schedule_value is not None:
            payload["schedule_value"] = schedule_value
        writer.write_task(payload)
        return f"Task {task_id} update requested."

    @mcp.tool()
    def register_group(jid: str, name: str, folder: str, trigger: str) -> str:
        if not is_main:
            raise PermissionError("Only the main group can register new groups.")
        writer.write_task(
            {"type": "register_group", "jid": jid, "name": name, "folder": folder, "trigger": trigger}
        )
        return f'Group "{name}" registered.'

    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
