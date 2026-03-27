from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from iflowclaw.config import load_config
from iflowclaw.db import create_task, get_all_sessions, init_database, list_tasks, store_message
from iflowclaw.sender_allowlist import ChatAllowlistEntry, SenderAllowlistConfig
from iflowclaw.types import NewMessage, RegisteredGroup


def _import_runtime_module(module_name: str):
    fake_croniter = types.ModuleType("croniter")

    class _FakeCroniter:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            return None

        def get_next(self, _cls):  # noqa: ANN001
            from datetime import UTC, datetime

            return datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

        @staticmethod
        def is_valid(_expr: str) -> bool:
            return True

    fake_croniter.croniter = _FakeCroniter

    sys.modules.pop(module_name, None)
    sys.modules.pop("iflowclaw.task_scheduler", None)
    with patch.dict(sys.modules, {"croniter": fake_croniter}):
        return importlib.import_module(module_name)


class _FakeChannel:
    name = "feishu"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def connect(self) -> None:
        return None

    async def send_message(self, jid: str, text: str) -> None:
        self.sent.append((jid, text))

    def is_connected(self) -> bool:
        return True

    def owns_jid(self, jid: str) -> bool:
        return jid.startswith("feishu:")

    async def disconnect(self) -> None:
        return None

    async def set_typing(self, jid: str, is_typing: bool) -> None:  # noqa: ARG002
        return None


class _FakeRunner:
    def __init__(self, result) -> None:  # noqa: ANN001
        self.result = result
        self.calls = []

    async def run(self, *, agent_input, agent_config, user_prompt):  # noqa: ANN001
        self.calls.append((agent_input, agent_config, user_prompt))
        return self.result


class TestServiceRuntimeFixes(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "store").mkdir(parents=True, exist_ok=True)
        with patch.dict(
            os.environ,
            {"FEISHU_APP_ID": "test_id", "FEISHU_APP_SECRET": "test_secret"},
            clear=False,
        ):
            self.config = load_config(self.root)
        init_database(self.config, in_memory=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_process_task_respects_isolated_context(self) -> None:
        cli_mod = _import_runtime_module("iflowclaw.cli")
        from iflowclaw.agents.backends.base import BackendResult

        manager = cli_mod.ServiceManager(self.config)
        manager.channels = [_FakeChannel()]
        manager.runner = _FakeRunner(
            BackendResult(status="success", text="isolated reply", new_session_id="isolated-session")
        )
        manager.state = cli_mod.ServiceState(
            sessions={"main": "group-session"},
            registered_groups={
                "feishu:test": RegisteredGroup(
                    name="main",
                    folder="main",
                    trigger="@iFlow",
                    added_at="2026-01-01T00:00:00Z",
                    requires_trigger=False,
                    is_main=True,
                )
            },
        )

        task = create_task(
            group_folder="main",
            chat_jid="feishu:test",
            prompt="run isolated",
            schedule_type="once",
            schedule_value="2026-01-01T00:00:00",
            context_mode="isolated",
            next_run="2026-01-01T00:00:00Z",
        )

        await manager.process_task(task)

        self.assertEqual(len(manager.runner.calls), 1)
        self.assertIsNone(manager.runner.calls[0][0].session_id)
        self.assertEqual(manager.state.sessions["main"], "group-session")
        self.assertEqual(get_all_sessions(), {})

    async def test_process_task_persists_group_session_updates(self) -> None:
        cli_mod = _import_runtime_module("iflowclaw.cli")
        from iflowclaw.agents.backends.base import BackendResult

        manager = cli_mod.ServiceManager(self.config)
        manager.channels = [_FakeChannel()]
        manager.runner = _FakeRunner(
            BackendResult(status="success", text="group reply", new_session_id="new-group-session")
        )
        manager.state = cli_mod.ServiceState(
            sessions={"main": "group-session"},
            registered_groups={
                "feishu:test": RegisteredGroup(
                    name="main",
                    folder="main",
                    trigger="@iFlow",
                    added_at="2026-01-01T00:00:00Z",
                    requires_trigger=False,
                    is_main=True,
                )
            },
        )

        task = create_task(
            group_folder="main",
            chat_jid="feishu:test",
            prompt="run group",
            schedule_type="once",
            schedule_value="2026-01-01T00:00:00",
            context_mode="group",
            next_run="2026-01-01T00:00:00Z",
        )

        await manager.process_task(task)

        self.assertEqual(len(manager.runner.calls), 1)
        self.assertEqual(manager.runner.calls[0][0].session_id, "group-session")
        self.assertEqual(manager.state.sessions["main"], "new-group-session")
        self.assertEqual(get_all_sessions()["main"], "new-group-session")

    async def test_ipc_update_task_recomputes_next_run_for_partial_schedule_change(self) -> None:
        ipc_mod = _import_runtime_module("iflowclaw.ipc")

        task = create_task(
            group_folder="main",
            chat_jid="feishu:test",
            prompt="interval task",
            schedule_type="interval",
            schedule_value="60000",
            context_mode="group",
            next_run="2026-01-01T00:01:00Z",
        )

        await ipc_mod._handle_ipc_file(
            self.config,
            source_folder="main",
            payload={
                "type": "update_task",
                "taskId": task.id,
                "schedule_value": "120000",
            },
            send_message=_noop_send_message,
            registered_groups_by_jid={
                "feishu:test": RegisteredGroup(
                    name="main",
                    folder="main",
                    trigger="@iFlow",
                    added_at="2026-01-01T00:00:00Z",
                    requires_trigger=False,
                    is_main=True,
                )
            },
        )

        updated = list_tasks()[0]
        self.assertEqual(updated.schedule_value, "120000")
        self.assertIsNotNone(updated.next_run)
        self.assertNotEqual(updated.next_run, "2026-01-01T00:01:00Z")

    async def test_process_group_messages_keeps_cursor_on_empty_success(self) -> None:
        cli_mod = _import_runtime_module("iflowclaw.cli")
        from iflowclaw.agents.backends.base import BackendResult

        manager = cli_mod.ServiceManager(self.config)
        manager.channels = [_FakeChannel()]
        manager.runner = _FakeRunner(BackendResult(status="success", text="", new_session_id="new-session"))
        manager.state = cli_mod.ServiceState(
            sessions={},
            registered_groups={
                "feishu:test": RegisteredGroup(
                    name="main",
                    folder="main",
                    trigger="@iFlow",
                    added_at="2026-01-01T00:00:00Z",
                    requires_trigger=False,
                    is_main=True,
                )
            },
        )
        store_message(
            NewMessage(
                id="msg-1",
                chat_jid="feishu:test",
                sender="user-1",
                sender_name="User One",
                content="hello",
                timestamp="2026-01-01T00:00:01Z",
            )
        )

        await manager.process_group_messages("feishu:test")

        self.assertEqual(manager.state.last_agent_ts["feishu:test"], "2026-01-01T00:00:01Z")
        self.assertEqual(manager.state.sessions["main"], "new-session")
        self.assertEqual(get_all_sessions()["main"], "new-session")
        self.assertEqual(manager.channels[0].sent, [])

    async def test_register_group_updates_live_registry(self) -> None:
        ipc_mod = _import_runtime_module("iflowclaw.ipc")

        registered_groups = {
            "feishu:main": RegisteredGroup(
                name="main",
                folder="main",
                trigger="@iFlow",
                added_at="2026-01-01T00:00:00Z",
                requires_trigger=False,
                is_main=True,
            )
        }

        await ipc_mod._handle_ipc_file(
            self.config,
            source_folder="main",
            payload={
                "type": "register_group",
                "jid": "feishu:new-group",
                "name": "New Group",
                "folder": "new-group",
                "trigger": "@iFlow",
            },
            send_message=_noop_send_message,
            registered_groups_by_jid=registered_groups,
        )

        self.assertIn("feishu:new-group", registered_groups)
        self.assertEqual(registered_groups["feishu:new-group"].folder, "new-group")

    async def test_initialize_does_not_start_global_proxy(self) -> None:
        cli_mod = _import_runtime_module("iflowclaw.cli")

        manager = cli_mod.ServiceManager(self.config)
        with (
            patch.object(manager, "_check_container_runtime"),
            patch.object(manager, "_register_channels"),
        ):
            await manager.initialize()

        self.assertIsNone(manager.proxy_server)

    async def test_trigger_check_uses_chat_jid_not_group_folder(self) -> None:
        cli_mod = _import_runtime_module("iflowclaw.cli")

        manager = cli_mod.ServiceManager(self.config)
        missed = [
            NewMessage(
                id="msg-2",
                chat_jid="feishu:test",
                sender="allowed-user",
                sender_name="Allowed User",
                content="@iFlow hello",
                timestamp="2026-01-01T00:00:02Z",
            )
        ]
        group = RegisteredGroup(
            name="test",
            folder="folder-name",
            trigger="@iFlow",
            added_at="2026-01-01T00:00:00Z",
            requires_trigger=True,
            is_main=False,
        )
        allow_cfg = SenderAllowlistConfig(
            default=ChatAllowlistEntry(allow=[], mode="trigger"),
            chats={"feishu:test": ChatAllowlistEntry(allow=["allowed-user"], mode="trigger")},
        )

        with patch("iflowclaw.cli.load_sender_allowlist", return_value=allow_cfg):
            needs_trigger = manager._needs_trigger_check(group, False, missed)

        self.assertFalse(needs_trigger)


async def _noop_send_message(_jid: str, _text: str) -> None:
    return None
