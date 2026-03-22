from __future__ import annotations

import json
from pathlib import Path

from .config import AppConfig
from .types import RegisteredGroup, ScheduledTask


def write_tasks_snapshot(config: AppConfig, tasks: list[ScheduledTask]) -> None:
    path = (config.data_dir / "ipc" / "current_tasks.json").resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "id": t.id,
            "groupFolder": t.group_folder,
            "chatJid": t.chat_jid,
            "prompt": t.prompt,
            "schedule_type": t.schedule_type,
            "schedule_value": t.schedule_value,
            "context_mode": t.context_mode,
            "next_run": t.next_run,
            "last_run": t.last_run,
            "last_result": t.last_result,
            "status": t.status,
            "created_at": t.created_at,
        }
        for t in tasks
    ]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_groups_snapshot(
    config: AppConfig,
    *,
    is_main_group: bool,
    current_group: RegisteredGroup,
    available_groups: list[dict],
    registered_groups_by_jid: dict[str, RegisteredGroup],
) -> None:
    group_ipc = (config.data_dir / "ipc" / current_group.folder).resolve()
    group_ipc.mkdir(parents=True, exist_ok=True)
    path = group_ipc / "groups.json"

    payload = {
        "isMainGroup": bool(is_main_group),
        "currentGroup": {
            "jid": None,
            "name": current_group.name,
            "folder": current_group.folder,
            "isMain": bool(current_group.is_main),
        },
        "availableGroups": available_groups,
        "registeredGroups": [
            {"jid": jid, "name": g.name, "folder": g.folder, "isMain": bool(g.is_main)}
            for jid, g in registered_groups_by_jid.items()
        ],
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
