"""端到端集成测试

测试完整的消息处理流程和任务调度流程。
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iflowclaw.config import load_config
from iflowclaw.db import (
    create_task,
    get_all_registered_groups,
    get_new_messages,
    get_router_state,
    init_database,
    list_tasks,
    set_registered_group,
    set_router_state,
    store_message,
)
from iflowclaw.group_queue import GroupQueue
from iflowclaw.router import format_messages, format_outbound
from iflowclaw.task_scheduler import compute_next_run, record_task_run
from iflowclaw.types import (
    AgentConfig,
    NewMessage,
    RegisteredGroup,
    ScheduledTask,
)


class TestMessageFlow(unittest.TestCase):
    """消息流程集成测试"""

    def setUp(self) -> None:
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        root = Path(self.temp_dir)
        (root / "store").mkdir(parents=True, exist_ok=True)
        (root / "groups" / "main").mkdir(parents=True, exist_ok=True)
        (root / "data" / "ipc" / "main").mkdir(parents=True, exist_ok=True)
        os.environ["FEISHU_APP_ID"] = "test_id"
        os.environ["FEISHU_APP_SECRET"] = "test_secret"
        self.config = load_config(root)
        init_database(self.config, in_memory=True)

        # 注册主群
        self.main_group = RegisteredGroup(
            name="main",
            folder="main",
            trigger="^@iFlow",
            added_at="2026-01-01T00:00:00Z",
            requires_trigger=False,
            is_main=True,
        )
        set_registered_group("feishu:main_chat", self.main_group)

    def tearDown(self) -> None:
        """清理测试环境"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_message_storage_and_retrieval(self) -> None:
        """测试消息存储和检索"""
        # 存储多条消息
        messages = [
            NewMessage(
                id=f"msg-{i}",
                chat_jid="feishu:main_chat",
                sender="user1",
                sender_name="User 1",
                content=f"Message {i}",
                timestamp=f"2026-01-01T0{i}:00:00Z",
                is_from_me=False,
                is_bot_message=False,
            )
            for i in range(3)
        ]

        for msg in messages:
            store_message(msg)

        # 检索消息
        retrieved = get_new_messages("", self.config.assistant_name)
        self.assertEqual(len(retrieved), 3)

        # 检索指定时间后的消息
        retrieved = get_new_messages("2026-01-01T01:00:00Z", self.config.assistant_name)
        self.assertEqual(len(retrieved), 1)
        self.assertEqual(retrieved[0].content, "Message 2")

    def test_message_formatting(self) -> None:
        """测试消息格式化"""
        messages = [
            NewMessage(
                id="msg-1",
                chat_jid="feishu:main_chat",
                sender="user1",
                sender_name="Alice",
                content="Hello <world>",
                timestamp="2026-01-01T00:00:00Z",
            ),
            NewMessage(
                id="msg-2",
                chat_jid="feishu:main_chat",
                sender="user2",
                sender_name="Bob",
                content='He said "hi"',
                timestamp="2026-01-01T00:01:00Z",
            ),
        ]

        formatted = format_messages(messages, "UTC")

        # 检查 XML 格式
        self.assertIn("<messages>", formatted)
        self.assertIn('sender="Alice"', formatted)
        self.assertIn('sender="Bob"', formatted)
        self.assertIn("&lt;world&gt;", formatted)
        self.assertIn("&quot;hi&quot;", formatted)

    def test_outbound_formatting(self) -> None:
        """测试出站消息格式化"""
        raw = "Hello\n<internal>secret</internal>\nWorld"
        formatted = format_outbound(raw)

        self.assertIn("Hello", formatted)
        self.assertIn("World", formatted)
        self.assertNotIn("secret", formatted)

    def test_router_state_persistence(self) -> None:
        """测试路由器状态持久化"""
        # 设置状态
        set_router_state("last_timestamp", "2026-01-01T00:00:00Z")
        set_router_state("last_agent_timestamp", '{"feishu:main_chat": "2026-01-01T00:00:00Z"}')

        # 验证状态
        last_ts = get_router_state("last_timestamp")
        self.assertEqual(last_ts, "2026-01-01T00:00:00Z")

        agent_ts = get_router_state("last_agent_timestamp")
        self.assertIsNotNone(agent_ts)
        parsed = json.loads(agent_ts)  # type: ignore[arg-type]
        self.assertEqual(parsed["feishu:main_chat"], "2026-01-01T00:00:00Z")


class TestTaskSchedulingFlow(unittest.TestCase):
    """任务调度流程集成测试"""

    def setUp(self) -> None:
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        root = Path(self.temp_dir)
        (root / "store").mkdir(parents=True, exist_ok=True)
        (root / "groups" / "main").mkdir(parents=True, exist_ok=True)
        (root / "data" / "ipc" / "main").mkdir(parents=True, exist_ok=True)
        os.environ["FEISHU_APP_ID"] = "test_id"
        os.environ["FEISHU_APP_SECRET"] = "test_secret"
        self.config = load_config(root)
        init_database(self.config, in_memory=True)

        # 注册主群
        self.main_group = RegisteredGroup(
            name="main",
            folder="main",
            trigger="^@iFlow",
            added_at="2026-01-01T00:00:00Z",
            requires_trigger=False,
            is_main=True,
        )
        set_registered_group("feishu:main_chat", self.main_group)

    def tearDown(self) -> None:
        """清理测试环境"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_task_lifecycle(self) -> None:
        """测试任务生命周期"""
        # 创建任务
        task = create_task(
            group_folder="main",
            chat_jid="feishu:main_chat",
            prompt="Test task",
            schedule_type="cron",
            schedule_value="0 * * * *",
            context_mode="group",
            next_run="2026-01-01T01:00:00Z",
        )

        self.assertIsNotNone(task.id)
        self.assertEqual(task.status, "active")

        # 验证任务存在
        tasks = list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].id, task.id)

    def test_cron_task_next_run(self) -> None:
        """测试 cron 任务下次运行时间"""
        task = ScheduledTask(
            id="test",
            group_folder="main",
            chat_jid="feishu:main_chat",
            prompt="Test",
            schedule_type="cron",
            schedule_value="0 9 * * *",  # 每天 9 点
            context_mode="group",
            next_run=None,
            last_run=None,
            last_result=None,
            status="active",
            created_at="2026-01-01T00:00:00Z",
        )

        now = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
        next_run = compute_next_run(task, now_utc=now, timezone_name="UTC")

        self.assertIsNotNone(next_run)
        # 下次运行应该是明天 9 点
        next_dt = datetime.fromisoformat(next_run.replace("Z", "+00:00"))  # type: ignore[union-attr]
        self.assertEqual(next_dt.hour, 9)
        self.assertEqual(next_dt.day, 2)

    def test_interval_task_next_run(self) -> None:
        """测试间隔任务下次运行时间"""
        task = ScheduledTask(
            id="test",
            group_folder="main",
            chat_jid="feishu:main_chat",
            prompt="Test",
            schedule_type="interval",
            schedule_value="300000",  # 5 分钟
            context_mode="group",
            next_run=None,
            last_run="2026-01-01T00:00:00Z",
            last_result=None,
            status="active",
            created_at="2026-01-01T00:00:00Z",
        )

        now = datetime(2026, 1, 1, 0, 10, 0, tzinfo=UTC)
        next_run = compute_next_run(task, now_utc=now, timezone_name="UTC")

        self.assertIsNotNone(next_run)
        # 下次运行应该在 00:15
        next_dt = datetime.fromisoformat(next_run.replace("Z", "+00:00"))  # type: ignore[union-attr]
        self.assertEqual(next_dt.minute, 15)

    def test_once_task_no_next_run(self) -> None:
        """测试一次性任务没有下次运行"""
        task = ScheduledTask(
            id="test",
            group_folder="main",
            chat_jid="feishu:main_chat",
            prompt="Test",
            schedule_type="once",
            schedule_value="2026-01-01T10:00:00",
            context_mode="group",
            next_run="2026-01-01T10:00:00Z",
            last_run=None,
            last_result=None,
            status="active",
            created_at="2026-01-01T00:00:00Z",
        )

        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        next_run = compute_next_run(task, now_utc=now, timezone_name="UTC")

        self.assertIsNone(next_run)

    def test_task_run_recording(self) -> None:
        """测试任务运行记录"""
        task = create_task(
            group_folder="main",
            chat_jid="feishu:main_chat",
            prompt="Test task",
            schedule_type="cron",
            schedule_value="0 * * * *",
            context_mode="group",
            next_run="2026-01-01T01:00:00Z",
        )

        started = datetime(2026, 1, 1, 1, 0, 0, tzinfo=UTC)
        finished = datetime(2026, 1, 1, 1, 0, 5, tzinfo=UTC)

        # 记录任务运行
        asyncio.run(
            record_task_run(
                task,
                started_at=started,
                finished_at=finished,
                status="success",
                result="Task completed",
                error=None,
                timezone_name="UTC",
            )
        )

        # 验证任务状态已更新
        tasks = list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertIsNotNone(tasks[0].last_run)


class TestGroupQueueFlow(unittest.TestCase):
    """组队列流程集成测试"""

    def setUp(self) -> None:
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        root = Path(self.temp_dir)
        (root / "store").mkdir(parents=True, exist_ok=True)
        os.environ["FEISHU_APP_ID"] = "test_id"
        os.environ["FEISHU_APP_SECRET"] = "test_secret"
        self.config = load_config(root)
        init_database(self.config, in_memory=True)

    def tearDown(self) -> None:
        """清理测试环境"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_group_queue_creation(self) -> None:
        """测试组队列创建"""
        queue = GroupQueue(
            max_concurrent=5,
            idle_timeout_ms=60000,
            config=self.config,
        )

        self.assertIsNotNone(queue)
        self.assertEqual(queue._sem._value, 5)

    @pytest.mark.asyncio
    async def test_group_queue_handlers(self) -> None:
        """测试组队列处理器"""
        queue = GroupQueue(
            max_concurrent=2,
            idle_timeout_ms=1000,
            config=self.config,
        )

        processed_messages = []
        processed_tasks = []

        async def process_message(chat_jid: str) -> None:
            processed_messages.append(chat_jid)

        async def process_task(task: ScheduledTask) -> None:
            processed_tasks.append(task.id)

        queue.set_handlers(
            process_message_check=process_message,
            process_task=process_task,
        )

        self.assertIsNotNone(queue._process_message_check)
        self.assertIsNotNone(queue._process_task)


class TestMultiGroupScenario(unittest.TestCase):
    """多组场景集成测试"""

    def setUp(self) -> None:
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        root = Path(self.temp_dir)
        (root / "store").mkdir(parents=True, exist_ok=True)
        (root / "groups" / "main").mkdir(parents=True, exist_ok=True)
        (root / "groups" / "group1").mkdir(parents=True, exist_ok=True)
        (root / "groups" / "group2").mkdir(parents=True, exist_ok=True)
        (root / "data" / "ipc" / "main").mkdir(parents=True, exist_ok=True)
        (root / "data" / "ipc" / "group1").mkdir(parents=True, exist_ok=True)
        (root / "data" / "ipc" / "group2").mkdir(parents=True, exist_ok=True)
        os.environ["FEISHU_APP_ID"] = "test_id"
        os.environ["FEISHU_APP_SECRET"] = "test_secret"
        self.config = load_config(root)
        init_database(self.config, in_memory=True)

    def tearDown(self) -> None:
        """清理测试环境"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_multiple_groups_registration(self) -> None:
        """测试多组注册"""
        # 注册主群
        main_group = RegisteredGroup(
            name="main",
            folder="main",
            trigger="^@iFlow",
            added_at="2026-01-01T00:00:00Z",
            requires_trigger=False,
            is_main=True,
        )
        set_registered_group("feishu:main_chat", main_group)

        # 注册普通群
        group1 = RegisteredGroup(
            name="Group 1",
            folder="group1",
            trigger="^@iFlow",
            added_at="2026-01-01T00:00:00Z",
            requires_trigger=True,
            is_main=False,
        )
        set_registered_group("feishu:chat1", group1)

        group2 = RegisteredGroup(
            name="Group 2",
            folder="group2",
            trigger="^@Bot",
            added_at="2026-01-01T00:00:00Z",
            requires_trigger=True,
            is_main=False,
        )
        set_registered_group("feishu:chat2", group2)

        # 验证所有组都已注册
        groups = get_all_registered_groups()
        self.assertEqual(len(groups), 3)
        self.assertIn("feishu:main_chat", groups)
        self.assertIn("feishu:chat1", groups)
        self.assertIn("feishu:chat2", groups)

    def test_group_isolation(self) -> None:
        """测试组隔离"""
        # 注册两个组
        group1 = RegisteredGroup(
            name="Group 1",
            folder="group1",
            trigger="^@iFlow",
            added_at="2026-01-01T00:00:00Z",
        )
        set_registered_group("feishu:chat1", group1)

        group2 = RegisteredGroup(
            name="Group 2",
            folder="group2",
            trigger="^@iFlow",
            added_at="2026-01-01T00:00:00Z",
        )
        set_registered_group("feishu:chat2", group2)

        # 在组 1 中存储消息
        store_message(
            NewMessage(
                id="msg1",
                chat_jid="feishu:chat1",
                sender="user1",
                sender_name="User 1",
                content="Message in group 1",
                timestamp="2026-01-01T00:00:00Z",
            )
        )

        # 在组 2 中存储消息
        store_message(
            NewMessage(
                id="msg2",
                chat_jid="feishu:chat2",
                sender="user2",
                sender_name="User 2",
                content="Message in group 2",
                timestamp="2026-01-01T00:00:00Z",
            )
        )

        # 验证消息隔离
        group1_messages = get_new_messages(
            "", self.config.assistant_name, jids=["feishu:chat1"]
        )
        group2_messages = get_new_messages(
            "", self.config.assistant_name, jids=["feishu:chat2"]
        )

        self.assertEqual(len(group1_messages), 1)
        self.assertEqual(len(group2_messages), 1)
        self.assertEqual(group1_messages[0].content, "Message in group 1")
        self.assertEqual(group2_messages[0].content, "Message in group 2")

    def test_tasks_per_group(self) -> None:
        """测试每组任务"""
        # 注册组
        group1 = RegisteredGroup(
            name="Group 1",
            folder="group1",
            trigger="^@iFlow",
            added_at="2026-01-01T00:00:00Z",
        )
        set_registered_group("feishu:chat1", group1)

        group2 = RegisteredGroup(
            name="Group 2",
            folder="group2",
            trigger="^@iFlow",
            added_at="2026-01-01T00:00:00Z",
        )
        set_registered_group("feishu:chat2", group2)

        # 在组 1 创建任务
        create_task(
            group_folder="group1",
            chat_jid="feishu:chat1",
            prompt="Task in group 1",
            schedule_type="cron",
            schedule_value="0 * * * *",
            context_mode="group",
            next_run="2026-01-01T01:00:00Z",
        )

        # 在组 2 创建任务
        create_task(
            group_folder="group2",
            chat_jid="feishu:chat2",
            prompt="Task in group 2",
            schedule_type="interval",
            schedule_value="60000",
            context_mode="group",
            next_run=None,
        )

        # 验证任务隔离
        group1_tasks = list_tasks(group_folder="group1")
        group2_tasks = list_tasks(group_folder="group2")

        self.assertEqual(len(group1_tasks), 1)
        self.assertEqual(len(group2_tasks), 1)
        self.assertEqual(group1_tasks[0].prompt, "Task in group 1")
        self.assertEqual(group2_tasks[0].prompt, "Task in group 2")


if __name__ == "__main__":
    unittest.main()
