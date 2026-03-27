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
from .db import (
    get_all_registered_groups,
    get_all_sessions,
    get_available_groups,
    get_messages_since,
    get_new_messages,
    get_router_state,
    init_database,
    list_tasks,
    reset_running_tasks,
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
    MAIN_GROUP_FOLDER,
    MAIN_GROUP_NAME,
    NewMessage,
    RegisteredGroup,
    ScheduledTask,
    STATUS_ERROR,
    STATUS_SUCCESS,
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
        self._shutting_down = False
        self._tasks: list[asyncio.Task] = []

    async def initialize(self) -> None:
        """Initialize database, load state, and set up components."""
        init_database(self.config)
        reset_running_tasks()
        self.state = ServiceState.load()
        write_tasks_snapshot(self.config, list_tasks())
        self._check_container_runtime()
        self._register_channels()
        self.queue = GroupQueue(
            max_concurrent=self.config.max_concurrent_agents,
            idle_timeout_ms=self.config.idle_timeout_ms,
            config=self.config,
        )
        self.runner = AgentRunner(self.config)

    def _uses_container_runtime(self, agent_config: AgentConfig, is_main: bool) -> bool:
        return _resolve_execution_mode(agent_config, self.config, is_main) == "container" or (
            (agent_config.backend or self.config.default_backend) == "container"
        )

    def _check_container_runtime(self) -> None:
        if self._uses_container_runtime(AgentConfig(), True) or any(
            self._uses_container_runtime(g.agent_config or AgentConfig(), bool(g.is_main))
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
            name=MAIN_GROUP_NAME,
            folder=MAIN_GROUP_FOLDER,
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

        if output.status != STATUS_SUCCESS:
            self.state.last_agent_ts[chat_jid] = previous_cursor
            self.state.save()
            return

        if output.new_session_id:
            self.state.sessions[group.folder] = output.new_session_id
            set_session(group.folder, output.new_session_id)

        if output.text:
            await self.send_message(chat_jid, output.text)
            self._store_bot_message(chat_jid, output.text)

    def _needs_trigger_check(self, group: RegisteredGroup, is_main: bool, missed: list[NewMessage]) -> bool:
        if is_main or group.requires_trigger is False:
            return False
        allow_cfg = load_sender_allowlist(self.config.sender_allowlist_path)
        return not any(
            self.config.trigger_pattern.search(m.content.strip())
            and (m.is_from_me or is_trigger_allowed(m.chat_jid, m.sender, allow_cfg))
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
        session_id = self.state.sessions.get(task.group_folder) if task.context_mode == "group" else None
        output = await self.runner.run(
            agent_input=AgentInput(
                prompt=user_prompt,
                group_folder=task.group_folder,
                chat_jid=task.chat_jid,
                is_main=bool(group.is_main),
                session_id=session_id,
                is_scheduled_task=True,
                assistant_name=self.config.assistant_name,
            ),
            agent_config=group.agent_config or AgentConfig(),
            user_prompt=user_prompt,
        )
        finished = datetime.now(UTC)

        if task.context_mode == "group" and output.status == STATUS_SUCCESS and output.new_session_id:
            self.state.sessions[task.group_folder] = output.new_session_id
            set_session(task.group_folder, output.new_session_id)

        if output.status == STATUS_SUCCESS and output.text:
            await self.send_message(task.chat_jid, output.text)
            self._store_bot_message(task.chat_jid, output.text)

        await record_task_run(
            task,
            started_at=started,
            finished_at=finished,
            status=STATUS_SUCCESS if output.status == STATUS_SUCCESS else STATUS_ERROR,
            result=output.text if output.status == STATUS_SUCCESS else None,
            error=output.error if output.status != STATUS_SUCCESS else None,
            timezone_name=self.config.timezone,
        )
        write_tasks_snapshot(self.config, list_tasks())

    async def _record_task_error(self, task: ScheduledTask, started: datetime, error: str) -> None:
        finished = datetime.now(UTC)
        await record_task_run(
            task,
            started_at=started,
            finished_at=finished,
            status=STATUS_ERROR,
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

        self._tasks = [ipc_task, sched_task, msg_task]

        self.recover_pending_messages()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda s=sig: asyncio.ensure_future(self.shutdown(s)))
            except NotImplementedError:
                signal.signal(sig, lambda s, f: asyncio.ensure_future(self.shutdown(signal.Signals(s))))

        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def shutdown(self, sig: signal.Signals) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        logger.info("Shutdown signal: %s", sig.name)
        self.stop_event.set()

        # Cancel all running tasks
        for task in self._tasks:
            task.cancel()

        if self.proxy_server is not None:
            self.proxy_server.close()
        if self.queue:
            await self.queue.shutdown(timeout_s=10.0)
        for ch in self.channels:
            try:
                await ch.disconnect()
            except Exception:
                pass


async def run_service(config: AppConfig) -> None:
    manager = ServiceManager(config)
    await manager.run()


def cmd_init(config: AppConfig) -> int:
    """Initialize configuration interactively."""
    import os

    env_path = config.project_root / ".env"

    print("=" * 50)
    print("iFlowClaw 配置初始化")
    print("=" * 50)
    print()

    # 检查现有配置
    existing = {}
    if env_path.exists():
        print(f"发现已有配置文件: {env_path}")
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    existing[key.strip()] = value.strip()
        print("将保留已有配置，按 Enter 跳过\n")

    # 收集配置
    new_config = {}

    # 必需配置
    print("【必需配置】")
    feishu_app_id = existing.get("FEISHU_APP_ID", "")
    if feishu_app_id:
        print(f"  FEISHU_APP_ID: {feishu_app_id[:8]}*** (已配置)")
    else:
        feishu_app_id = input("  飞书应用 ID (FEISHU_APP_ID): ").strip()
    if feishu_app_id:
        new_config["FEISHU_APP_ID"] = feishu_app_id

    feishu_app_secret = existing.get("FEISHU_APP_SECRET", "")
    if feishu_app_secret:
        print(f"  FEISHU_APP_SECRET: {'*' * 16} (已配置)")
    else:
        import getpass

        feishu_app_secret = getpass.getpass("  飞书应用密钥 (FEISHU_APP_SECRET): ").strip()
    if feishu_app_secret:
        new_config["FEISHU_APP_SECRET"] = feishu_app_secret

    # 可选配置
    print("\n【可选配置】(按 Enter 使用默认值)")
    assistant_name = input(f"  助手名称 [{existing.get('ASSISTANT_NAME', 'iFlow')}]: ").strip()
    if assistant_name:
        new_config["ASSISTANT_NAME"] = assistant_name
    elif "ASSISTANT_NAME" in existing:
        new_config["ASSISTANT_NAME"] = existing["ASSISTANT_NAME"]

    agent_backend = input(f"  默认后端 (iflow/claude/agno) [{existing.get('AGENT_BACKEND', 'iflow')}]: ").strip()
    if agent_backend:
        new_config["AGENT_BACKEND"] = agent_backend
    elif "AGENT_BACKEND" in existing:
        new_config["AGENT_BACKEND"] = existing["AGENT_BACKEND"]

    log_level = input(f"  日志级别 (debug/info/warning/error) [{existing.get('LOG_LEVEL', 'info')}]: ").strip()
    if log_level:
        new_config["LOG_LEVEL"] = log_level
    elif "LOG_LEVEL" in existing:
        new_config["LOG_LEVEL"] = existing["LOG_LEVEL"]

    timezone = input(f"  时区 [{existing.get('TZ', 'Asia/Shanghai')}]: ").strip()
    if timezone:
        new_config["TZ"] = timezone
    elif "TZ" in existing:
        new_config["TZ"] = existing["TZ"]

    # 合并配置
    final_config = {**existing, **new_config}

    # 写入文件
    with open(env_path, "w") as f:
        f.write("# iFlowClaw 配置文件\n")
        f.write("# 由 'iflowclaw init' 生成\n\n")
        for key in sorted(final_config.keys()):
            f.write(f"{key}={final_config[key]}\n")

    print(f"\n配置已保存到: {env_path}")
    print("\n下一步:")
    print("  • 运行服务: iflowclaw run")
    print("  • 安装为系统服务: iflowclaw install")
    return 0


def cmd_install(config: AppConfig) -> int:
    """Install as user systemd service."""
    import os
    import subprocess

    service_name = "iflowclaw"
    project_root = str(config.project_root)
    python_bin = os.environ.get("PYTHON_BIN", "python3")
    path_env = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")

    # 创建日志目录
    config.logs_dir.mkdir(parents=True, exist_ok=True)

    # 检查 .env
    env_path = config.project_root / ".env"
    if not env_path.exists():
        print("错误: 请先运行 'iflowclaw init' 创建配置")
        return 1

    # 生成服务文件内容
    service_content = f"""[Unit]
Description=iFlowClaw - Lightweight Personal AI Assistant
After=network.target

[Service]
Type=simple
WorkingDirectory={project_root}
ExecStart={python_bin} -m iflowclaw run
Restart=always
RestartSec=10
StandardOutput=append:{project_root}/logs/iflowclaw.log
StandardError=append:{project_root}/logs/iflowclaw.log
Environment=PYTHONPATH={project_root}
Environment=PATH={path_env}

[Install]
WantedBy=default.target"""

    # 用户级服务
    service_dir = Path.home() / ".config" / "systemd" / "user"
    service_dir.mkdir(parents=True, exist_ok=True)
    service_file = service_dir / f"{service_name}.service"
    service_file.write_text(service_content)
    print(f"服务文件已创建: {service_file}")

    # 重载并启用
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", f"{service_name}.service"], check=True)
    print("服务已启用（登录后自启）")

    # 询问是否启动
    answer = input("是否立即启动服务？[Y/n] ").strip().lower()
    if answer != "n":
        subprocess.run(["systemctl", "--user", "start", f"{service_name}.service"])
        subprocess.run(["systemctl", "--user", "status", f"{service_name}.service", "--no-pager"])

    print("\n服务管理:")
    print(f"  iflowclaw start    # 启动服务")
    print(f"  iflowclaw stop     # 停止服务")
    print(f"  iflowclaw restart  # 重启服务")
    print(f"  iflowclaw status   # 查看状态")
    print(f"  iflowclaw logs     # 查看日志")

    return 0


def cmd_service(action: str, follow: bool = False) -> int:
    """Manage systemd user service."""
    import subprocess

    service_name = "iflowclaw"

    if action == "logs":
        args = ["journalctl", "--user", "-u", f"{service_name}.service"]
        if follow:
            args.append("-f")
        subprocess.run(args)
    else:
        subprocess.run(["systemctl", "--user", action, f"{service_name}.service"])
        if action in ("start", "restart"):
            subprocess.run(["systemctl", "--user", "status", f"{service_name}.service", "--no-pager"])

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="iflowclaw",
        description="iFlowClaw - 轻量级个人 AI 助手",
    )
    sub = parser.add_subparsers(dest="cmd", help="可用命令")

    # run 命令
    sub.add_parser("run", help="前台运行服务")

    # init 命令
    sub.add_parser("init", help="初始化配置")

    # install 命令
    sub.add_parser("install", help="安装为用户服务")

    # 服务管理命令
    sub.add_parser("start", help="启动服务")
    sub.add_parser("stop", help="停止服务")
    sub.add_parser("restart", help="重启服务")
    sub.add_parser("status", help="查看服务状态")

    logs_parser = sub.add_parser("logs", help="查看服务日志")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="实时跟踪日志")

    args = parser.parse_args(argv)
    cmd = args.cmd or "run"

    # 服务管理命令不需要加载配置
    if cmd in ("start", "stop", "restart", "status"):
        return cmd_service(cmd)
    if cmd == "logs":
        return cmd_service("logs", follow=getattr(args, "follow", False))

    # 加载配置
    try:
        config = load_config()
    except Exception as e:
        print(f"配置加载失败: {e}")
        print("请先运行: iflowclaw init")
        return 1

    configure_logging(config.logs_dir, level=config.log_level)

    if cmd == "init":
        return cmd_init(config)
    elif cmd == "install":
        return cmd_install(config)
    elif cmd == "run":
        # 检查必需配置
        env_path = config.project_root / ".env"
        if not env_path.exists():
            print("未找到配置文件，请先运行: iflowclaw init")
            return 1
        asyncio.run(run_service(config))
        return 0
    else:
        parser.print_help()
        return 2
