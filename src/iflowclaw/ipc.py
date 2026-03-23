from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import AppConfig
from .db import create_task, delete_task, list_tasks, set_registered_group, set_task_status, update_task
from .logging import get_logger
from .snapshots import write_tasks_snapshot
from .task_scheduler import compute_next_run
from .types import RegisteredGroup, ScheduledTask

logger = get_logger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _move_to_errors(config: AppConfig, source_path: Path, error: Exception) -> None:
    errors_dir = (config.data_dir / "ipc" / "errors").resolve()
    errors_dir.mkdir(parents=True, exist_ok=True)
    dest = errors_dir / f"{source_path.name}"
    try:
        shutil.move(str(source_path), str(dest))
        (errors_dir / f"{source_path.name}.error.txt").write_text(str(error), encoding="utf-8")
    except Exception:
        try:
            source_path.unlink(missing_ok=True)
        except Exception:
            pass


def _is_main_group(source_folder: str, registered_groups_by_jid: dict[str, RegisteredGroup]) -> bool:
    for g in registered_groups_by_jid.values():
        if g.folder == source_folder and g.is_main:
            return True
    return False


def _task_belongs_to_group(task_id: str, group_folder: str) -> bool:
    return any(t.id == task_id and t.group_folder == group_folder for t in list_tasks())


def _parse_once_local_to_utc_iso(value: str, timezone_name: str) -> str:
    if value.endswith("Z") or "+" in value or "-" in value[10:]:
        raise ValueError("once schedule_value must be local time without timezone suffix")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        raise ValueError("once schedule_value must be naive local time")
    local = dt.replace(tzinfo=ZoneInfo(timezone_name))
    return local.astimezone(UTC).isoformat().replace("+00:00", "Z")


async def start_ipc_watcher(
    config: AppConfig,
    *,
    send_message: Callable[[str, str], Awaitable[None]],
    registered_groups: Callable[[], dict[str, RegisteredGroup]],
    stop_event: asyncio.Event,
) -> None:
    ipc_root = (config.data_dir / "ipc").resolve()
    ipc_root.mkdir(parents=True, exist_ok=True)

    while not stop_event.is_set():
        try:
            await _poll_once(config, send_message=send_message, registered_groups=registered_groups)
        except Exception as e:
            logger.exception("ipc: poll failed: %s", e)
        await asyncio.sleep(config.ipc_poll_interval_ms / 1000)


async def _poll_once(
    config: AppConfig,
    *,
    send_message: Callable[[str, str], Awaitable[None]],
    registered_groups: Callable[[], dict[str, RegisteredGroup]],
) -> None:
    ipc_root = (config.data_dir / "ipc").resolve()
    groups = registered_groups()

    for group_dir in sorted([p for p in ipc_root.iterdir() if p.is_dir()]):
        source_folder = group_dir.name
        if source_folder in {"errors"}:
            continue

        for subdir in ("messages", "tasks"):
            d = group_dir / subdir
            if not d.exists():
                continue
            for file_path in sorted(d.glob("*.json")):
                try:
                    data = _read_json(file_path)
                    await _handle_ipc_file(
                        config,
                        source_folder=source_folder,
                        payload=data,
                        send_message=send_message,
                        registered_groups_by_jid=groups,
                    )
                    file_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning("ipc: failed processing %s: %s", file_path, e)
                    _move_to_errors(config, file_path, e)


async def _handle_ipc_file(
    config: AppConfig,
    *,
    source_folder: str,
    payload: dict,
    send_message: Callable[[str, str], Awaitable[None]],
    registered_groups_by_jid: dict[str, RegisteredGroup],
) -> None:
    typ = payload.get("type")
    is_main = _is_main_group(source_folder, registered_groups_by_jid)

    if typ == "message":
        chat_jid = payload.get("chatJid") or payload.get("chat_jid")
        text = payload.get("text")
        if not isinstance(chat_jid, str) or not isinstance(text, str):
            raise ValueError("invalid message payload")
        await send_message(chat_jid, text)
        return

    if typ == "register_group":
        if not is_main:
            raise PermissionError("only main group can register groups")
        jid = payload.get("jid")
        name = payload.get("name")
        folder = payload.get("folder")
        trigger = payload.get("trigger")
        if not all(isinstance(x, str) for x in (jid, name, folder, trigger)):
            raise ValueError("invalid register_group payload")
        group = RegisteredGroup(
            name=name,
            folder=folder,
            trigger=trigger,
            added_at=_utc_now_iso(),
            requires_trigger=True,
            is_main=False,
        )
        set_registered_group(jid, group)
        return

    if typ == "schedule_task":
        prompt = payload.get("prompt")
        schedule_type = payload.get("schedule_type")
        schedule_value = payload.get("schedule_value")
        context_mode = payload.get("context_mode") or "group"
        target_jid = payload.get("targetJid") or payload.get("target_group_jid") or payload.get("chatJid")

        if not all(isinstance(x, str) for x in (prompt, schedule_type, schedule_value, context_mode, target_jid)):
            raise ValueError("invalid schedule_task payload")

        if not is_main and source_folder != _resolve_folder_by_jid(target_jid, registered_groups_by_jid):
            raise PermissionError("cannot schedule task for another group")

        now_utc = datetime.now(UTC)
        if schedule_type == "once":
            next_run = _parse_once_local_to_utc_iso(schedule_value, config.timezone)
        else:
            tmp_task = ScheduledTask(
                id="tmp",
                group_folder=_resolve_folder_by_jid(target_jid, registered_groups_by_jid),
                chat_jid=target_jid,
                prompt=prompt,
                schedule_type=schedule_type,  # type: ignore[assignment]
                schedule_value=schedule_value,
                context_mode=context_mode,  # type: ignore[assignment]
                next_run=None,
                last_run=None,
                last_result=None,
                status="active",
                created_at=_utc_now_iso(),
            )
            next_run = compute_next_run(tmp_task, now_utc=now_utc, timezone_name=config.timezone)

        create_task(
            group_folder=_resolve_folder_by_jid(target_jid, registered_groups_by_jid),
            chat_jid=target_jid,
            prompt=prompt,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            context_mode=context_mode,
            next_run=next_run,
        )

        tasks = list_tasks()
        write_tasks_snapshot(config, tasks)
        return

    if typ in {"pause_task", "resume_task", "cancel_task", "update_task"}:
        task_id = payload.get("taskId") or payload.get("task_id")
        if not isinstance(task_id, str):
            raise ValueError("invalid task control payload")

        if not is_main and not _task_belongs_to_group(task_id, source_folder):
            raise PermissionError("cannot manage task from another group")

        if typ == "pause_task":
            set_task_status(task_id, "paused")
        elif typ == "resume_task":
            set_task_status(task_id, "active")
        elif typ == "cancel_task":
            delete_task(task_id)
        else:
            update_task(
                task_id,
                prompt=payload.get("prompt"),
                schedule_type=payload.get("schedule_type"),
                schedule_value=payload.get("schedule_value"),
            )

        write_tasks_snapshot(config, list_tasks())
        return

    raise ValueError(f"unknown ipc type: {typ}")


def _resolve_folder_by_jid(target_jid: str, registered_groups_by_jid: dict[str, RegisteredGroup]) -> str:
    group = registered_groups_by_jid.get(target_jid)
    if not group:
        raise ValueError(f"target group not registered: {target_jid}")
    return group.folder
