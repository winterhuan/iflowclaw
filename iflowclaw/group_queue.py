from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from .logging import get_logger
from .types import ScheduledTask

logger = get_logger(__name__)


@dataclass(slots=True)
class MessageCheckEvent:
    kind: Literal["message_check"] = "message_check"


@dataclass(slots=True)
class ScheduledTaskEvent:
    task: ScheduledTask
    kind: Literal["scheduled_task"] = "scheduled_task"


Event = MessageCheckEvent | ScheduledTaskEvent


class GroupQueue:
    def __init__(
        self,
        *,
        max_concurrent: int,
        idle_timeout_ms: int,
    ) -> None:
        self._sem = asyncio.Semaphore(max(1, int(max_concurrent)))
        self._idle_timeout_s = max(1.0, idle_timeout_ms / 1000)
        self._queues: dict[str, asyncio.Queue[Event]] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._stop_event = asyncio.Event()
        self._process_message_check: Callable[[str], Awaitable[None]] | None = None
        self._process_task: Callable[[ScheduledTask], Awaitable[None]] | None = None

    def set_handlers(
        self,
        *,
        process_message_check: Callable[[str], Awaitable[None]],
        process_task: Callable[[ScheduledTask], Awaitable[None]],
    ) -> None:
        self._process_message_check = process_message_check
        self._process_task = process_task

    async def enqueue_message_check(self, chat_jid: str) -> None:
        await self._enqueue(chat_jid, MessageCheckEvent())

    async def enqueue_task(self, task: ScheduledTask) -> None:
        await self._enqueue(task.chat_jid, ScheduledTaskEvent(task=task))

    async def shutdown(self) -> None:
        self._stop_event.set()
        for task in list(self._workers.values()):
            task.cancel()
        await asyncio.gather(*self._workers.values(), return_exceptions=True)
        self._workers.clear()
        self._queues.clear()

    async def _enqueue(self, chat_jid: str, event: Event) -> None:
        if self._stop_event.is_set():
            return
        q = self._queues.get(chat_jid)
        if q is None:
            q = asyncio.Queue()
            self._queues[chat_jid] = q
        await q.put(event)
        if chat_jid not in self._workers or self._workers[chat_jid].done():
            self._workers[chat_jid] = asyncio.create_task(self._worker(chat_jid))

    async def _worker(self, chat_jid: str) -> None:
        q = self._queues[chat_jid]
        while not self._stop_event.is_set():
            try:
                event = await asyncio.wait_for(q.get(), timeout=self._idle_timeout_s)
            except asyncio.TimeoutError:
                if q.empty():
                    self._queues.pop(chat_jid, None)
                    self._workers.pop(chat_jid, None)
                    return
                continue

            try:
                async with self._sem:
                    if event.kind == "message_check":
                        if self._process_message_check is None:
                            raise RuntimeError("process_message_check not configured")
                        await self._process_message_check(chat_jid)
                    else:
                        if self._process_task is None:
                            raise RuntimeError("process_task not configured")
                        await self._process_task(event.task)
            except Exception as e:
                logger.exception("group queue worker failed: %s", e)
            finally:
                q.task_done()
