"""CLI entry point and service main loop.

This module provides the command-line interface for iFlowClaw and manages
the main service loop including message processing, task scheduling, and
channel communication.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .agents.runner import AgentRunner, _resolve_execution_mode
from .channels.feishu import register_feishu_channel
from .channels.registry import ChannelOpts, get_channel_factory, get_registered_channel_names
from .config import AppConfig, load_config
from .credential_proxy import start_credential_proxy
from .db import (
    get_all_registered_groups,
    get_all_sessions,
    get_available_groups,
    get_messages_since,
    get_new_messages,
    get_router_state,
    init_database,
    list_tasks,
    set_registered_group,
    set_router_state,
    set_session,
    store_chat_metadata,
    store_message,
)
from .group_folder import resolve_group_ipc_path
from .group_queue import GroupQueue
from .ipc import start_ipc_watcher
from .logging import configure_logging, get_logger
from .router import find_channel, format_messages, format_outbound
from .sender_allowlist import (
    is_sender_allowed,
    is_trigger_allowed,
    load_sender_allowlist,
    should_drop_message,
)
from .snapshots import write_tasks_snapshot
from .task_scheduler import record_task_run, start_scheduler_loop
from .types import (
    AgentConfig,
    AgentInput,
    Channel,
    NewMessage,
    RegisteredGroup,
    ScheduledTask,
)

logger = get_logger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class ServiceState:
    """Service runtime state.

    Attributes:
        last_ts: Timestamp of the last processed message.
        last_agent_ts: Per-group timestamps of last agent interactions.
        sessions: Mapping of group folders to session IDs.
        registered_groups: All registered groups.
    """

    last_ts: str = ""
    last_agent_ts: dict[str, str] = field(default_factory=dict)
    sessions: dict[str, str] = field(default_factory=dict)
    registered_groups: dict[str, RegisteredGroup] = field(default_factory=dict)

    @classmethod
    def load(cls) -> ServiceState:
        """Load state from database."""
        last_ts = get_router_state("last_timestamp") or ""
        raw_agent_ts = get_router_state("last_agent_timestamp") or ""
        try:
            last_agent_ts = json.loads(raw_agent_ts) if raw_agent_ts else {}
            if not isinstance(last_agent_ts, dict):
                last_agent_ts = {}
        except Exception:
            last_agent_ts = {}
        return cls(
            last_ts=last_ts,
            last_agent_ts=last_agent_ts,
            sessions=get_all_sessions(),
            registered_groups=get_all_registered_groups(),
        )

    def save(self) -> None:
        """Persist state to database."""
        set_router_state("last_timestamp", self.last_ts)
        set_router_state("last_agent_timestamp", json.dumps(self.last_agent_ts, ensure_ascii=False))


class ServiceManager:
    """Main service manager coordinating all components.

    Manages channels, message processing, task scheduling, and agent execution.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.state = ServiceState()
        self.channels: list[Channel] = []
        self.queue: GroupQueue | None = None
        self.runner: AgentRunner | None = None
        self.stop_event = asyncio.Event()
        self.proxy_server: Any = None

    async def initialize(self) -> None:
        """Initialize database, load state, and set up components."""
        init_database(self.config)
        self.state = ServiceState.load()
        write_tasks_snapshot(self.config, list_tasks())
        self.proxy_server = await start_credential_proxy(self._config)
        self._check_container_runtime()
        self._register_channels()
        self.queue = GroupQueue(
            max_concurrent=self.config.max_concurrent_agents,
            idle_timeout_ms=self.config.idle_timeout_ms,
            config=self.config,
        )
        self.runner = AgentRunner(self.config)

    def _check_container_runtime(self) -> None:
        if self.config.default_execution_mode == "container" or any(
            _resolve_execution_mode(g.agent_config or AgentConfig(), self.config, bool(g.is_main)) == "container"
            for g in self.state.registered_groups.values()
        ):
            try:
                from .agents.backends.container import _cleanup_orphans, _get_runtime

                _get_runtime()
                _cleanup_orphans()
            except Exception as e:
                logger.warning("Container runtime check failed: %s (container mode unavailable)", e)

    def _register_channels(self) -> None:
        register_feishu_channel(self.config)
        channel_opts = ChannelOpts(
            on_message=self._on_message,
            on_chat_metadata=self._on_chat_metadata,
            registered_groups=lambda: self.state.registered_groups,
            auto_register_group=self._try_auto_register_main_group,
        )
        for name in get_registered_channel_names():
            factory = get_channel_factory(name)
            if factory is None:
                continue
            ch = factory(channel_opts)
            if ch is None:
                continue
            self.channels.append(ch)

    async def connect_channels(self) -> None:
        for ch in self.channels:
            await ch.connect()
        if not self.channels:
            raise RuntimeError("No channels connected")

    def _on_chat_metadata(
        self,
        chat_jid: str,
        timestamp: str,
        name: str | None,
        channel: str | None,
        is_group: bool | None,
    ) -> None:
        store_chat_metadata(chat_jid, timestamp, name=name, channel=channel, is_group=is_group)

    def _on_message(self, chat_jid: str, msg: NewMessage) -> None:
        if not msg.is_from_me and not msg.is_bot_message and chat_jid in self.state.registered_groups:
            cfg = load_sender_allowlist(self.config.sender_allowlist_path)
            if should_drop_message(chat_jid, cfg) and not is_sender_allowed(chat_jid, msg.sender, cfg):
                return
        store_message(msg)

    def _try_auto_register_main_group(self, chat_jid: str, name: str, channel: str) -> bool:
        if any(g.is_main for g in self.state.registered_groups.values()):
            return False
        group = RegisteredGroup(
            name="main",
            folder="main",
            trigger=self.config.trigger_pattern.pattern,
            added_at=_utc_now_iso(),
            requires_trigger=False,
            is_main=True,
        )
        set_registered_group(chat_jid, group)
        self.state.registered_groups[chat_jid] = group
        return True

    async def send_message(self, jid: str, text: str) -> None:
        ch = find_channel(self.channels, jid)
        if not ch:
            raise RuntimeError(f"No channel owns JID: {jid}")
        outbound = format_outbound(text)
        if outbound:
            await ch.send_message(jid, outbound)

    async def process_group_messages(self, chat_jid: str) -> None:
        group = self.state.registered_groups.get(chat_jid)
        if not group:
            return
        ch = find_channel(self.channels, chat_jid)
        if not ch:
            return

        since = self.state.last_agent_ts.get(chat_jid, "")
        missed = get_messages_since(chat_jid, since, self.config.assistant_name)
        if not missed:
            return

        is_main = bool(group.is_main)
        if self._needs_trigger_check(group, is_main, missed):
            return

        prompt = format_messages(missed, self.config.timezone)
        write_tasks_snapshot(self.config, list_tasks())
        self._write_groups_snapshot(group.folder, is_main)

        previous_cursor = self.state.last_agent_ts.get(chat_jid, "")
        self.state.last_agent_ts[chat_jid] = missed[-1].timestamp
        self.state.save()

        await ch.set_typing(chat_jid, True)
        agent_cfg = group.agent_config or AgentConfig()
        use_container = _resolve_execution_mode(agent_cfg, self.config, is_main) == "container"

        if use_container and self.queue:
            self.queue.register_container(chat_jid)

        try:
            output = await self.runner.run(
                agent_input=AgentInput(
                    prompt=prompt,
                    group_folder=group.folder,
                    chat_jid=chat_jid,
                    is_main=is_main,
                    session_id=self.state.sessions.get(group.folder),
                    is_scheduled_task=False,
                    assistant_name=self.config.assistant_name,
                ),
                agent_config=agent_cfg,
                user_prompt=prompt,
            )
        finally:
            if use_container and self.queue:
                self.queue.unregister_container(chat_jid)
            await ch.set_typing(chat_jid, False)

        if output.status != "success" or not output.text:
            self.state.last_agent_ts[chat_jid] = previous_cursor
            self.state.save()
            return

        if output.new_session_id:
            self.state.sessions[group.folder] = output.new_session_id
            set_session(group.folder, output.new_session_id)

        await self.send_message(chat_jid, output.text)
        self._store_bot_message(chat_jid, output.text)

    def _needs_trigger_check(self, group: RegisteredGroup, is_main: bool, missed: list[NewMessage]) -> bool:
        if is_main or group.requires_trigger is False:
            return False
        allow_cfg = load_sender_allowlist(self.config.sender_allowlist_path)
        return not any(
            self.config.trigger_pattern.search(m.content.strip())
            and (m.is_from_me or is_trigger_allowed(group.folder, m.sender, allow_cfg))
            for m in missed
        )

    def _write_groups_snapshot(self, group_folder: str, is_main: bool) -> None:
        ipc_dir = resolve_group_ipc_path(self.config, group_folder)
        ipc_dir.mkdir(parents=True, exist_ok=True)
        path = ipc_dir / "available_groups.json"
        available = get_available_groups(self.state.registered_groups)
        visible = available if is_main else []
        payload = {
            "groups": [
                {"jid": g.jid, "name": g.name, "lastActivity": g.last_activity, "isRegistered": g.is_registered}
                for g in visible
            ],
            "lastSync": _utc_now_iso(),
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _store_bot_message(self, chat_jid: str, text: str) -> None:
        store_message(
            NewMessage(
                id=str(uuid.uuid4()),
                chat_jid=chat_jid,
                sender=self.config.assistant_name,
                sender_name=self.config.assistant_name,
                content=text,
                timestamp=_utc_now_iso(),
                is_from_me=True,
                is_bot_message=True,
            )
        )

    async def process_task(self, task: ScheduledTask) -> None:
        started = datetime.now(UTC)
        group = next(
            (g for g in self.state.registered_groups.values() if g.folder == task.group_folder),
            None,
        )
        if group is None:
            await self._record_task_error(task, started, "group not found")
            return

        ch = find_channel(self.channels, task.chat_jid)
        if not ch:
            await self._record_task_error(task, started, "channel not found")
            return

        user_prompt = task.prompt
        output = await self.runner.run(
            agent_input=AgentInput(
                prompt=user_prompt,
                group_folder=task.group_folder,
                chat_jid=task.chat_jid,
                is_main=bool(group.is_main),
                session_id=self.state.sessions.get(task.group_folder),
                is_scheduled_task=True,
                assistant_name=self.config.assistant_name,
            ),
            agent_config=group.agent_config or AgentConfig(),
            user_prompt=user_prompt,
        )
        finished = datetime.now(UTC)

        if output.status == "success" and output.text:
            await self.send_message(task.chat_jid, output.text)
            self._store_bot_message(task.chat_jid, output.text)

        await record_task_run(
            task,
            started_at=started,
            finished_at=finished,
            status="success" if output.status == "success" else "error",
            result=output.text if output.status == "success" else None,
            error=output.error if output.status != "success" else None,
            timezone_name=self.config.timezone,
        )
        write_tasks_snapshot(self.config, list_tasks())

    async def _record_task_error(self, task: ScheduledTask, started: datetime, error: str) -> None:
        finished = datetime.now(UTC)
        await record_task_run(
            task,
            started_at=started,
            finished_at=finished,
            status="error",
            result=None,
            error=error,
            timezone_name=self.config.timezone,
        )

    def recover_pending_messages(self) -> None:
        for chat_jid, group in self.state.registered_groups.items():
            since = self.state.last_agent_ts.get(chat_jid, "")
            pending = get_messages_since(chat_jid, since, self.config.assistant_name)
            if pending:
                logger.info("Recovery: %d unprocessed messages in %s", len(pending), group.name)
                asyncio.ensure_future(self.queue.enqueue_message_check(chat_jid))

    async def message_loop(self) -> None:
        while not self.stop_event.is_set():
            jids = list(self.state.registered_groups.keys())
            msgs = get_new_messages(
                self.state.last_ts,
                self.config.assistant_name,
                jids=jids if jids else None,
                limit=200,
            )
            if msgs:
                self.state.last_ts = msgs[-1].timestamp
                self.state.save()
                for m in msgs:
                    if m.chat_jid in self.state.registered_groups and not m.is_bot_message and not m.is_from_me:
                        formatted = format_messages([m], self.config.timezone)
                        if self.queue.send_message(m.chat_jid, formatted):
                            if not self.queue.is_container_active(m.chat_jid):
                                ch = find_channel(self.channels, m.chat_jid)
                                if ch:
                                    asyncio.ensure_future(ch.set_typing(m.chat_jid, True))
                        else:
                            await self.queue.enqueue_message_check(m.chat_jid)
            await asyncio.sleep(self.config.poll_interval_ms / 1000)

    async def run(self) -> None:
        await self.initialize()
        await self.connect_channels()

        self.queue.set_handlers(
            process_message_check=self.process_group_messages,
            process_task=self.process_task,
        )

        ipc_task = asyncio.create_task(
            start_ipc_watcher(
                self.config,
                send_message=self.send_message,
                registered_groups=lambda: self.state.registered_groups,
                stop_event=self.stop_event,
            )
        )
        sched_task = asyncio.create_task(
            start_scheduler_loop(
                timezone_name=self.config.timezone,
                poll_interval_ms=self.config.scheduler_poll_interval_ms,
                enqueue_task=self.queue.enqueue_task,
                stop_event=self.stop_event,
            )
        )
        msg_task = asyncio.create_task(self.message_loop())

        self.recover_pending_messages()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda s=sig: asyncio.ensure_future(self.shutdown(s)))
            except NotImplementedError:
                signal.signal(sig, lambda s, f: asyncio.ensure_future(self.shutdown(signal.Signals(s))))

        await asyncio.gather(ipc_task, sched_task, msg_task)

    async def shutdown(self, sig: signal.Signals) -> None:
        logger.info("Shutdown signal: %s", sig.name)
        self.stop_event.set()
        self.proxy_server.close()
        await self.queue.shutdown(timeout_s=10.0)
        for ch in self.channels:
            try:
                await ch.disconnect()
            except Exception:
                pass


async def run_service(config: AppConfig) -> None:
    manager = ServiceManager(config)
    await manager.run()


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
