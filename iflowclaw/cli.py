from __future__ import annotations

import argparse
import asyncio
import json
import signal
import uuid
from datetime import datetime, timezone
from typing import Any

from .agents.runner import AgentRunner
from .channels.feishu import register_feishu_channel
from .channels.registry import get_channel_factory, get_registered_channel_names
from .config import AppConfig, load_config
from .db import (
    get_all_registered_groups,
    get_all_sessions,
    get_new_messages,
    get_router_state,
    get_messages_since,
  list_tasks,
    init_database,
    set_router_state,
    set_session,
    store_message,
)
from .logging import configure_logging, get_logger
from .router import find_channel, format_messages, format_outbound
from .sender_allowlist import is_sender_allowed, is_trigger_allowed, load_sender_allowlist, should_drop_message
from .group_queue import GroupQueue
from .ipc import start_ipc_watcher
from .snapshots import write_tasks_snapshot
from .task_scheduler import record_task_run, start_scheduler_loop
from .types import AgentConfig, AgentInput, NewMessage, RegisteredGroup, ScheduledTask

logger = get_logger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_state(config: AppConfig) -> tuple[str, dict[str, str], dict[str, str], dict[str, RegisteredGroup]]:
    last_ts = get_router_state("last_timestamp") or ""
    raw_agent_ts = get_router_state("last_agent_timestamp") or ""
    try:
        last_agent_ts = json.loads(raw_agent_ts) if raw_agent_ts else {}
        if not isinstance(last_agent_ts, dict):
            last_agent_ts = {}
    except Exception:
        last_agent_ts = {}
    sessions = get_all_sessions()
    groups = get_all_registered_groups()
    return last_ts, last_agent_ts, sessions, groups


def _save_state(last_ts: str, last_agent_ts: dict[str, str]) -> None:
    set_router_state("last_timestamp", last_ts)
    set_router_state("last_agent_timestamp", json.dumps(last_agent_ts, ensure_ascii=False))


def _try_auto_register_main_group(
    chat_jid: str,
    name: str,
    channel: str,
    registered_groups: dict[str, RegisteredGroup],
    config: AppConfig,
) -> bool:
    if any(g.is_main for g in registered_groups.values()):
        return False
    group = RegisteredGroup(
        name="main",
        folder="main",
        trigger=config.trigger_pattern.pattern,
        added_at=_utc_now_iso(),
        requires_trigger=False,
        is_main=True,
    )
    from .db import set_registered_group

    set_registered_group(chat_jid, group)
    registered_groups[chat_jid] = group
    return True


async def run_service(config: AppConfig) -> None:
    init_database(config)
    last_ts, last_agent_ts, sessions, registered_groups = _load_state(config)
    write_tasks_snapshot(config, list_tasks())

    register_feishu_channel(config)

    channels = []

    def _registered_groups() -> dict[str, RegisteredGroup]:
        return registered_groups

    def on_chat_metadata(
        chat_jid: str,
        timestamp: str,
        name: str | None,
        channel: str | None,
        is_group: bool | None,
    ) -> None:
        from .db import store_chat_metadata

        store_chat_metadata(chat_jid, timestamp, name=name, channel=channel, is_group=is_group)

    def on_message(chat_jid: str, msg: NewMessage) -> None:
        if not msg.is_from_me and not msg.is_bot_message and chat_jid in registered_groups:
            cfg = load_sender_allowlist(config.sender_allowlist_path)
            if should_drop_message(chat_jid, cfg) and not is_sender_allowed(chat_jid, msg.sender, cfg):
                return
        store_message(msg)

    channel_opts = {
        "onMessage": on_message,
        "onChatMetadata": on_chat_metadata,
        "registeredGroups": _registered_groups,
        "autoRegisterGroup": lambda jid, name, channel: _try_auto_register_main_group(
            jid, name, channel, registered_groups, config
        ),
    }

    for name in get_registered_channel_names():
        factory = get_channel_factory(name)
        if factory is None:
            continue
        ch = factory(channel_opts)
        if ch is None:
            continue
        channels.append(ch)
        await ch.connect()

    if not channels:
        raise RuntimeError("No channels connected")

    queue = GroupQueue(max_concurrent=config.max_concurrent_agents, idle_timeout_ms=config.idle_timeout_ms)
    runner = AgentRunner(config)

    stop_event = asyncio.Event()

    async def send_message(jid: str, text: str) -> None:
        ch = find_channel(channels, jid)
        if not ch:
            raise RuntimeError(f"No channel owns JID: {jid}")
        outbound = format_outbound(text)
        if outbound:
            await ch.send_message(jid, outbound)

    async def process_message_check(chat_jid: str) -> None:
        group = registered_groups.get(chat_jid)
        if not group:
            return
        ch = find_channel(channels, chat_jid)
        if not ch:
            return

        since = last_agent_ts.get(chat_jid, "")
        missed = get_messages_since(chat_jid, since, config.assistant_name)
        if not missed:
            return

        is_main = bool(group.is_main)
        needs_trigger = (not is_main) and (group.requires_trigger is not False)
        if needs_trigger:
            allow_cfg = load_sender_allowlist(config.sender_allowlist_path)
            has_trigger = any(
                config.trigger_pattern.search(m.content.strip())
                and (m.is_from_me or is_trigger_allowed(chat_jid, m.sender, allow_cfg))
                for m in missed
            )
            if not has_trigger:
                return

        prompt = format_messages(missed, config.timezone)

        write_tasks_snapshot(config, list_tasks())

        previous_cursor = last_agent_ts.get(chat_jid, "")
        last_agent_ts[chat_jid] = missed[-1].timestamp
        _save_state(last_ts, last_agent_ts)

        await ch.set_typing(chat_jid, True)
        output = await runner.run(
            agent_input=AgentInput(
                prompt=prompt,
                group_folder=group.folder,
                chat_jid=chat_jid,
                is_main=is_main,
                session_id=sessions.get(group.folder),
                is_scheduled_task=False,
                assistant_name=config.assistant_name,
            ),
            agent_config=group.agent_config or AgentConfig(),
            user_prompt=prompt,
        )
        await ch.set_typing(chat_jid, False)

        if output.status != "success" or not output.result:
            last_agent_ts[chat_jid] = previous_cursor
            _save_state(last_ts, last_agent_ts)
            return

        if output.new_session_id:
            sessions[group.folder] = output.new_session_id
            set_session(group.folder, output.new_session_id)

        await send_message(chat_jid, output.result)
        store_message(
            NewMessage(
                id=str(uuid.uuid4()),
                chat_jid=chat_jid,
                sender=config.assistant_name,
                sender_name=config.assistant_name,
                content=output.result,
                timestamp=_utc_now_iso(),
                is_from_me=True,
                is_bot_message=True,
            )
        )

    async def process_task(task: ScheduledTask) -> None:
        started = datetime.now(timezone.utc)
        group = next((g for g in registered_groups.values() if g.folder == task.group_folder), None)
        if group is None:
            finished = datetime.now(timezone.utc)
            await record_task_run(
                task,
                started_at=started,
                finished_at=finished,
                status="error",
                result=None,
                error="group not found",
                timezone_name=config.timezone,
            )
            return

        ch = find_channel(channels, task.chat_jid)
        if not ch:
            finished = datetime.now(timezone.utc)
            await record_task_run(
                task,
                started_at=started,
                finished_at=finished,
                status="error",
                result=None,
                error="channel not found",
                timezone_name=config.timezone,
            )
            return

        user_prompt = task.prompt
        output = await runner.run(
            agent_input=AgentInput(
                prompt=user_prompt,
                group_folder=task.group_folder,
                chat_jid=task.chat_jid,
                is_main=bool(group.is_main),
                session_id=sessions.get(task.group_folder),
                is_scheduled_task=True,
                assistant_name=config.assistant_name,
            ),
            agent_config=group.agent_config or AgentConfig(),
            user_prompt=user_prompt,
        )
        finished = datetime.now(timezone.utc)

        if output.status == "success" and output.result:
            await send_message(task.chat_jid, output.result)
            store_message(
                NewMessage(
                    id=str(uuid.uuid4()),
                    chat_jid=task.chat_jid,
                    sender=config.assistant_name,
                    sender_name=config.assistant_name,
                    content=output.result,
                    timestamp=_utc_now_iso(),
                    is_from_me=True,
                    is_bot_message=True,
                )
            )

        await record_task_run(
            task,
            started_at=started,
            finished_at=finished,
            status="success" if output.status == "success" else "error",
            result=output.result if output.status == "success" else None,
            error=output.error if output.status != "success" else None,
            timezone_name=config.timezone,
        )

        write_tasks_snapshot(config, list_tasks())

    queue.set_handlers(process_message_check=process_message_check, process_task=process_task)

    async def enqueue_task(task: ScheduledTask) -> None:
        await queue.enqueue_task(task)

    async def message_loop() -> None:
        nonlocal last_ts
        while not stop_event.is_set():
            msgs = get_new_messages(last_ts, config.assistant_name, limit=200)
            if msgs:
                last_ts = msgs[-1].timestamp
                _save_state(last_ts, last_agent_ts)
                for m in msgs:
                    if m.chat_jid in registered_groups and not m.is_bot_message and not m.is_from_me:
                        await queue.enqueue_message_check(m.chat_jid)
            await asyncio.sleep(config.poll_interval_ms / 1000)

    ipc_task = asyncio.create_task(
        start_ipc_watcher(
            config,
            send_message=send_message,
            registered_groups=lambda: registered_groups,
            stop_event=stop_event,
        )
    )
    sched_task = asyncio.create_task(
        start_scheduler_loop(
            timezone_name=config.timezone,
            poll_interval_ms=config.scheduler_poll_interval_ms,
            enqueue_task=enqueue_task,
            stop_event=stop_event,
        )
    )
    msg_task = asyncio.create_task(message_loop())

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await asyncio.gather(ipc_task, sched_task, msg_task)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iflowclaw")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run")
    args = parser.parse_args(argv)

    config = load_config()
    configure_logging(config.logs_dir)

    cmd = args.cmd or "run"
    if cmd != "run":
        raise SystemExit(2)

    asyncio.run(run_service(config))
    return 0
