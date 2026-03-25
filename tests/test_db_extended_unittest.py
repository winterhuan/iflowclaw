"""db 模块扩展单元测试"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from iflowclaw.config import load_config
from iflowclaw.db import (
    create_task,
    delete_task,
    get_all_chats,
    get_all_registered_groups,
    get_all_sessions,
    get_available_groups,
    get_due_tasks,
    get_new_messages,
    get_registered_group,
    get_router_state,
    init_database,
    list_tasks,
    log_task_run,
    set_registered_group,
    set_router_state,
    set_session,
    set_task_status,
    store_chat_metadata,
    store_message,
    update_task,
    update_task_after_run,
)
from iflowclaw.types import (
    AgentConfig,
    NewMessage,
    RegisteredGroup,
    TaskRunLog,
)


class TestChatOperations(unittest.TestCase):
    """聊天操作测试"""

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

    def test_store_chat_metadata(self) -> None:
        """测试存储聊天元数据"""
        store_chat_metadata(
            "feishu:chat1",
            "2026-01-01T00:00:00Z",
            name="Test Chat",
            channel="feishu",
            is_group=True,
        )

        chats = get_all_chats()
        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0].jid, "feishu:chat1")
        self.assertEqual(chats[0].name, "Test Chat")
        self.assertEqual(chats[0].channel, "feishu")
        self.assertEqual(chats[0].is_group, 1)

    def test_store_chat_metadata_update(self) -> None:
        """测试更新聊天元数据"""
        store_chat_metadata(
            "feishu:chat1",
            "2026-01-01T00:00:00Z",
            name="Old Name",
            channel="feishu",
            is_group=True,
        )

        store_chat_metadata(
            "feishu:chat1",
            "2026-01-02T00:00:00Z",
            name="New Name",
            channel="feishu",
            is_group=True,
        )

        chats = get_all_chats()
        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0].name, "New Name")
        self.assertEqual(chats[0].last_message_time, "2026-01-02T00:00:00Z")

    def test_get_all_chats_order(self) -> None:
        """测试聊天列表排序"""
        store_chat_metadata("feishu:chat1", "2026-01-01T00:00:00Z", name="Chat 1")
        store_chat_metadata("feishu:chat2", "2026-01-03T00:00:00Z", name="Chat 2")
        store_chat_metadata("feishu:chat3", "2026-01-02T00:00:00Z", name="Chat 3")

        chats = get_all_chats()

        # 应该按时间降序排列
        self.assertEqual(chats[0].name, "Chat 2")
        self.assertEqual(chats[1].name, "Chat 3")
        self.assertEqual(chats[2].name, "Chat 1")


class TestMessageOperations(unittest.TestCase):
    """消息操作测试"""

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

    def test_store_message(self) -> None:
        """测试存储消息"""
        msg = NewMessage(
            id="msg1",
            chat_jid="feishu:chat1",
            sender="user1",
            sender_name="User 1",
            content="Hello",
            timestamp="2026-01-01T00:00:00Z",
            is_from_me=False,
            is_bot_message=False,
        )

        store_message(msg)

        messages = get_new_messages("", self.config.assistant_name)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "Hello")

    def test_get_messages_since(self) -> None:
        """测试获取指定时间后的消息"""
        store_message(
            NewMessage(
                id="msg1",
                chat_jid="feishu:chat1",
                sender="user1",
                sender_name="User 1",
                content="Message 1",
                timestamp="2026-01-01T00:00:00Z",
            )
        )

        store_message(
            NewMessage(
                id="msg2",
                chat_jid="feishu:chat1",
                sender="user1",
                sender_name="User 1",
                content="Message 2",
                timestamp="2026-01-01T01:00:00Z",
            )
        )

        # 获取 00:30 之后的消息
        messages = get_new_messages("2026-01-01T00:30:00Z", self.config.assistant_name)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "Message 2")

    def test_get_new_messages_with_jids(self) -> None:
        """测试按 JID 过滤消息"""
        store_message(
            NewMessage(
                id="msg1",
                chat_jid="feishu:chat1",
                sender="user1",
                sender_name="User 1",
                content="Message 1",
                timestamp="2026-01-01T00:00:00Z",
            )
        )

        store_message(
            NewMessage(
                id="msg2",
                chat_jid="feishu:chat2",
                sender="user1",
                sender_name="User 1",
                content="Message 2",
                timestamp="2026-01-01T00:00:00Z",
            )
        )

        # 只获取 chat1 的消息
        messages = get_new_messages(
            "",
            self.config.assistant_name,
            jids=["feishu:chat1"],
        )
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].chat_jid, "feishu:chat1")

    def test_store_message_with_bot_prefix(self) -> None:
        """测试带机器人前缀的消息"""
        store_message(
            NewMessage(
                id="msg1",
                chat_jid="feishu:chat1",
                sender="bot",
                sender_name="Bot",
                content="iFlow: Hello",
                timestamp="2026-01-01T00:00:00Z",
                is_from_me=True,
                is_bot_message=True,
            )
        )

        messages = get_new_messages("", self.config.assistant_name)
        self.assertEqual(len(messages), 1)
        # 前缀应该被剥离
        self.assertEqual(messages[0].content, "Hello")


class TestSessionOperations(unittest.TestCase):
    """会话操作测试"""

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

    def test_set_and_get_session(self) -> None:
        """测试设置和获取会话"""
        set_session("test_group", "session-123")

        sessions = get_all_sessions()
        self.assertEqual(sessions["test_group"], "session-123")

    def test_update_session(self) -> None:
        """测试更新会话"""
        set_session("test_group", "session-123")
        set_session("test_group", "session-456")

        sessions = get_all_sessions()
        self.assertEqual(sessions["test_group"], "session-456")

    def test_multiple_sessions(self) -> None:
        """测试多个会话"""
        set_session("group1", "session-1")
        set_session("group2", "session-2")

        sessions = get_all_sessions()
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions["group1"], "session-1")
        self.assertEqual(sessions["group2"], "session-2")


class TestRouterStateOperations(unittest.TestCase):
    """路由器状态操作测试"""

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

    def test_set_and_get_router_state(self) -> None:
        """测试设置和获取路由器状态"""
        set_router_state("last_timestamp", "2026-01-01T00:00:00Z")

        value = get_router_state("last_timestamp")
        self.assertEqual(value, "2026-01-01T00:00:00Z")

    def test_get_nonexistent_state(self) -> None:
        """测试获取不存在的状态"""
        value = get_router_state("nonexistent")
        self.assertIsNone(value)

    def test_update_router_state(self) -> None:
        """测试更新路由器状态"""
        set_router_state("key", "value1")
        set_router_state("key", "value2")

        value = get_router_state("key")
        self.assertEqual(value, "value2")


class TestTaskOperations(unittest.TestCase):
    """任务操作测试"""

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

    def test_create_task(self) -> None:
        """测试创建任务"""
        task = create_task(
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="Hello",
            schedule_type="cron",
            schedule_value="0 * * * *",
            context_mode="group",
            next_run="2026-01-01T01:00:00Z",
        )

        self.assertIsNotNone(task.id)
        self.assertEqual(task.group_folder, "main")
        self.assertEqual(task.prompt, "Hello")
        self.assertEqual(task.schedule_type, "cron")
        self.assertEqual(task.status, "active")

    def test_list_tasks(self) -> None:
        """测试列出任务"""
        create_task(
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="Task 1",
            schedule_type="cron",
            schedule_value="0 * * * *",
            context_mode="group",
            next_run="2026-01-01T01:00:00Z",
        )

        create_task(
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="Task 2",
            schedule_type="interval",
            schedule_value="60000",
            context_mode="isolated",
            next_run=None,
        )

        tasks = list_tasks()
        self.assertEqual(len(tasks), 2)

    def test_list_tasks_by_group(self) -> None:
        """测试按组列出任务"""
        create_task(
            group_folder="group1",
            chat_jid="feishu:chat1",
            prompt="Task 1",
            schedule_type="cron",
            schedule_value="0 * * * *",
            context_mode="group",
            next_run="2026-01-01T01:00:00Z",
        )

        create_task(
            group_folder="group2",
            chat_jid="feishu:chat2",
            prompt="Task 2",
            schedule_type="interval",
            schedule_value="60000",
            context_mode="isolated",
            next_run=None,
        )

        tasks = list_tasks(group_folder="group1")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].group_folder, "group1")

    def test_get_due_tasks(self) -> None:
        """测试获取到期任务"""
        create_task(
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="Task 1",
            schedule_type="cron",
            schedule_value="0 * * * *",
            context_mode="group",
            next_run="2026-01-01T01:00:00Z",
        )

        # 查询 01:30 之前的任务
        due = get_due_tasks("2026-01-01T01:30:00Z")
        self.assertEqual(len(due), 1)

        # 查询 00:30 之前的任务
        due = get_due_tasks("2026-01-01T00:30:00Z")
        self.assertEqual(len(due), 0)

    def test_set_task_status(self) -> None:
        """测试设置任务状态"""
        task = create_task(
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="Task",
            schedule_type="cron",
            schedule_value="0 * * * *",
            context_mode="group",
            next_run="2026-01-01T01:00:00Z",
        )

        set_task_status(task.id, "paused")

        tasks = list_tasks()
        self.assertEqual(tasks[0].status, "paused")

    def test_delete_task(self) -> None:
        """测试删除任务"""
        task = create_task(
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="Task",
            schedule_type="cron",
            schedule_value="0 * * * *",
            context_mode="group",
            next_run="2026-01-01T01:00:00Z",
        )

        delete_task(task.id)

        tasks = list_tasks()
        self.assertEqual(len(tasks), 0)

    def test_update_task(self) -> None:
        """测试更新任务"""
        task = create_task(
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="Old prompt",
            schedule_type="cron",
            schedule_value="0 * * * *",
            context_mode="group",
            next_run="2026-01-01T01:00:00Z",
        )

        update_task(
            task.id,
            prompt="New prompt",
            schedule_type="interval",
            schedule_value="60000",
        )

        tasks = list_tasks()
        self.assertEqual(tasks[0].prompt, "New prompt")
        self.assertEqual(tasks[0].schedule_type, "interval")
        self.assertEqual(tasks[0].schedule_value, "60000")

    def test_update_task_after_run(self) -> None:
        """测试任务运行后更新"""
        task = create_task(
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="Task",
            schedule_type="cron",
            schedule_value="0 * * * *",
            context_mode="group",
            next_run="2026-01-01T01:00:00Z",
        )

        update_task_after_run(
            task.id,
            last_run="2026-01-01T01:00:00Z",
            last_result="success",
            next_run="2026-01-01T02:00:00Z",
        )

        tasks = list_tasks()
        self.assertEqual(tasks[0].last_run, "2026-01-01T01:00:00Z")
        self.assertEqual(tasks[0].last_result, "success")
        self.assertEqual(tasks[0].next_run, "2026-01-01T02:00:00Z")

    def test_log_task_run(self) -> None:
        """测试记录任务运行"""
        task = create_task(
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="Task",
            schedule_type="cron",
            schedule_value="0 * * * *",
            context_mode="group",
            next_run="2026-01-01T01:00:00Z",
        )

        log_entry = TaskRunLog(
            task_id=task.id,
            run_at="2026-01-01T01:00:00Z",
            duration_ms=1000,
            status="success",
            result="OK",
            error=None,
        )

        # 不应该抛出异常
        log_task_run(log_entry)


class TestRegisteredGroupOperations(unittest.TestCase):
    """注册组操作测试"""

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

    def test_set_and_get_registered_group(self) -> None:
        """测试设置和获取注册组"""
        group = RegisteredGroup(
            name="Test Group",
            folder="test-group",
            trigger="^@Bot",
            added_at="2026-01-01T00:00:00Z",
            requires_trigger=True,
            is_main=False,
        )

        set_registered_group("feishu:chat1", group)

        retrieved = get_registered_group("feishu:chat1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "Test Group")  # type: ignore[union-attr]
        self.assertEqual(retrieved.folder, "test-group")  # type: ignore[union-attr]

    def test_get_nonexistent_group(self) -> None:
        """测试获取不存在的组"""
        retrieved = get_registered_group("feishu:nonexistent")
        self.assertIsNone(retrieved)

    def test_get_all_registered_groups(self) -> None:
        """测试获取所有注册组"""
        group1 = RegisteredGroup(
            name="Group 1",
            folder="group1",
            trigger="^@Bot",
            added_at="2026-01-01T00:00:00Z",
        )

        group2 = RegisteredGroup(
            name="Group 2",
            folder="group2",
            trigger="^@Bot",
            added_at="2026-01-01T00:00:00Z",
        )

        set_registered_group("feishu:chat1", group1)
        set_registered_group("feishu:chat2", group2)

        groups = get_all_registered_groups()
        self.assertEqual(len(groups), 2)
        self.assertIn("feishu:chat1", groups)
        self.assertIn("feishu:chat2", groups)

    def test_update_registered_group(self) -> None:
        """测试更新注册组"""
        group = RegisteredGroup(
            name="Old Name",
            folder="test-group",
            trigger="^@Bot",
            added_at="2026-01-01T00:00:00Z",
        )

        set_registered_group("feishu:chat1", group)

        updated_group = RegisteredGroup(
            name="New Name",
            folder="test-group",
            trigger="^@Bot",
            added_at="2026-01-01T00:00:00Z",
        )

        set_registered_group("feishu:chat1", updated_group)

        groups = get_all_registered_groups()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups["feishu:chat1"].name, "New Name")

    def test_group_with_agent_config(self) -> None:
        """测试带 Agent 配置的组"""
        agent_config = AgentConfig(
            backend="claude",
            model="sonnet",
            timeout=60000,
        )

        group = RegisteredGroup(
            name="Test Group",
            folder="test-group",
            trigger="^@Bot",
            added_at="2026-01-01T00:00:00Z",
            agent_config=agent_config,
        )

        set_registered_group("feishu:chat1", group)

        retrieved = get_registered_group("feishu:chat1")
        self.assertIsNotNone(retrieved)
        self.assertIsNotNone(retrieved.agent_config)  # type: ignore[union-attr]
        self.assertEqual(retrieved.agent_config.backend, "claude")  # type: ignore[union-attr]

    def test_invalid_group_folder(self) -> None:
        """测试无效的组文件夹"""
        group = RegisteredGroup(
            name="Test Group",
            folder="global",  # 保留名称
            trigger="^@Bot",
            added_at="2026-01-01T00:00:00Z",
        )

        with self.assertRaises(ValueError):
            set_registered_group("feishu:chat1", group)


class TestAvailableGroups(unittest.TestCase):
    """可用组测试"""

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

    def test_get_available_groups(self) -> None:
        """测试获取可用组"""
        # 添加一些聊天
        store_chat_metadata("feishu:chat1", "2026-01-01T00:00:00Z", name="Group 1", is_group=True)
        store_chat_metadata("feishu:chat2", "2026-01-01T00:00:00Z", name="Group 2", is_group=True)
        store_chat_metadata("feishu:user1", "2026-01-01T00:00:00Z", name="User 1", is_group=False)

        # 注册一个组
        group = RegisteredGroup(
            name="Group 1",
            folder="group1",
            trigger="^@Bot",
            added_at="2026-01-01T00:00:00Z",
        )
        set_registered_group("feishu:chat1", group)

        registered_groups = {"feishu:chat1": group}
        available = get_available_groups(registered_groups)

        # 应该只返回群组，不包含用户
        group_jids = [g.jid for g in available]
        self.assertIn("feishu:chat1", group_jids)
        self.assertIn("feishu:chat2", group_jids)
        self.assertNotIn("feishu:user1", group_jids)

        # 检查注册状态
        for g in available:
            if g.jid == "feishu:chat1":
                self.assertTrue(g.is_registered)
            elif g.jid == "feishu:chat2":
                self.assertFalse(g.is_registered)


if __name__ == "__main__":
    import os

    unittest.main()
