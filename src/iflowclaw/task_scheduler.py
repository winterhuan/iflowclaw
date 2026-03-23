from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter

from .db import get_due_tasks, log_task_run, update_task_after_run
from .logging import get_logger
from .types import ScheduledTask, TaskRunLog

logger = get_logger(__name__)


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _to_utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def compute_next_run(task: ScheduledTask, *, now_utc: datetime, timezone_name: str) -> str | None:
    if task.schedule_type == "once":
        return None

    if task.schedule_type == "interval":
        interval_ms = int(task.schedule_value)
        interval = timedelta(milliseconds=interval_ms)

        if task.next_run:
            base = _parse_iso(task.next_run)
        elif task.last_run:
            base = _parse_iso(task.last_run)
        else:
            base = now_utc

        candidate = base + interval
        while candidate <= now_utc:
            candidate += interval
        return _to_utc_iso(candidate)

    tz = ZoneInfo(timezone_name)
    base_local = now_utc.astimezone(tz)
    it = croniter(task.schedule_value, base_local)
    next_local = it.get_next(datetime)
    if next_local.tzinfo is None:
        next_local = next_local.replace(tzinfo=tz)
    return _to_utc_iso(next_local)


async def start_scheduler_loop(
    *,
    timezone_name: str,
    poll_interval_ms: int,
    enqueue_task: Callable[[ScheduledTask], Awaitable[None]],
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        now = datetime.now(UTC)
        now_iso = _to_utc_iso(now)

        try:
            due = get_due_tasks(now_iso)
        except Exception as e:
            logger.exception("scheduler: get_due_tasks failed: %s", e)
            await asyncio.sleep(poll_interval_ms / 1000)
            continue

        for task in due:
            await enqueue_task(task)

        await asyncio.sleep(poll_interval_ms / 1000)


async def record_task_run(
    task: ScheduledTask,
    *,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    result: str | None,
    error: str | None,
    timezone_name: str,
) -> None:
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    run_at = _to_utc_iso(finished_at)

    entry = TaskRunLog(
        task_id=task.id,
        run_at=run_at,
        duration_ms=duration_ms,
        status="success" if status == "success" else "error",
        result=result,
        error=error,
    )
    try:
        log_task_run(entry)
    except Exception as e:
        logger.exception("scheduler: log_task_run failed: %s", e)

    next_run = compute_next_run(task, now_utc=finished_at.astimezone(UTC), timezone_name=timezone_name)
    new_status = "completed" if task.schedule_type == "once" else None
    try:
        update_task_after_run(
            task.id,
            last_run=run_at,
            last_result=result if status == "success" else error,
            next_run=next_run,
            status=new_status,
        )
    except Exception as e:
        logger.exception("scheduler: update_task_after_run failed: %s", e)
