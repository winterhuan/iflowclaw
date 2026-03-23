from __future__ import annotations

import json

from .config import AppConfig
from .types import ScheduledTask


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
