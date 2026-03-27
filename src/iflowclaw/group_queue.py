from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from .config import AppConfig
from .types import ScheduledTask

logger = logging.getLogger(__name__)


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
        config: AppConfig | None = None,
    ) -> None:
        self._sem = asyncio.Semaphore(max(1, int(max_concurrent)))
        self._idle_timeout_s = max(1.0, idle_timeout_ms / 1000)
        self._queues: dict[str, asyncio.Queue[Event]] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._stop_event = asyncio.Event()
        self._process_message_check: Callable[[str], Awaitable[None]] | None = None
        self._process_task: Callable[[ScheduledTask], Awaitable[None]] | None = None
        self._active_pipes: dict[str, asyncio.Queue[str]] = {}
        self._container_groups: set[str] = set()
        self._config = config

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

    def send_message(self, chat_jid: str, text: str) -> bool:
        pipe = self._active_pipes.get(chat_jid)
        if pipe is None:
            return False
        try:
            pipe.put_nowait(text)
            return True
        except asyncio.QueueFull:
            return False

    def register_pipe(self, chat_jid: str, pipe: asyncio.Queue[str]) -> None:
        self._active_pipes[chat_jid] = pipe

    def unregister_pipe(self, chat_jid: str) -> None:
        self._active_pipes.pop(chat_jid, None)

    def register_container(self, chat_jid: str) -> None:
        self._container_groups.add(chat_jid)

    def unregister_container(self, chat_jid: str) -> None:
        self._container_groups.discard(chat_jid)

    def is_container_active(self, chat_jid: str) -> bool:
        return chat_jid in self._container_groups

    def close_container(self, chat_jid: str) -> bool:
        if chat_jid not in self._container_groups:
            return False
        return self._write_close_sentinel(chat_jid)

    def _write_container_ipc_input(self, chat_jid: str, text: str) -> bool:
        if self._config is None:
            return False
        group_folder = self._resolve_group_folder(chat_jid)
        if group_folder is None:
            return False
        ipc_input_dir = self._config.data_dir / "ipc" / group_folder / "input"
        ipc_input_dir.mkdir(parents=True, exist_ok=True)
        import random  # noqa: PLC0415
        import time  # noqa: PLC0415

        filename = f"{int(time.time() * 1000)}-{random.random():.8f}".replace(".", "") + ".json"
        filepath = ipc_input_dir / filename
        payload = {
            "type": "message",
            "text": text,
            "chatJid": chat_jid,
            "groupFolder": group_folder,
        }
        try:
            tmp = filepath.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(filepath)
            return True
        except Exception as e:
            logger.warning("Failed to write container IPC input: %s", e)
            return False

    def _write_close_sentinel(self, chat_jid: str) -> bool:
        if self._config is None:
            return False
        group_folder = self._resolve_group_folder(chat_jid)
        if group_folder is None:
            return False
        ipc_input_dir = self._config.data_dir / "ipc" / group_folder / "input"
        ipc_input_dir.mkdir(parents=True, exist_ok=True)
        sentinel = ipc_input_dir / "_close"
        try:
            sentinel.write_text("", encoding="utf-8")
            return True
        except Exception as e:
            logger.warning("Failed to write close sentinel: %s", e)
            return False

    def _resolve_group_folder(self, chat_jid: str) -> str | None:
        if self._config is None:
            return None
        try:
            from .db import get_registered_group  # noqa: PLC0415

            group = get_registered_group(chat_jid)
            return group.folder if group else None
        except Exception:
            return None

    async def shutdown(self, timeout_s: float = 10.0) -> None:
        self._stop_event.set()
        for chat_jid in list(self._container_groups):
            self._write_close_sentinel(chat_jid)
        for task in list(self._workers.values()):
            task.cancel()
        if self._workers:
            await asyncio.gather(*self._workers.values(), return_exceptions=True)
        self._workers.clear()
        self._queues.clear()
        self._active_pipes.clear()
        self._container_groups.clear()

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
            except TimeoutError:
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
