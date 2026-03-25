"""snapshots 模块单元测试"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from iflowclaw.config import load_config
from iflowclaw.snapshots import write_tasks_snapshot
from iflowclaw.types import ScheduledTask


class TestWriteTasksSnapshot(unittest.TestCase):
    """任务快照写入测试"""

    def test_write_empty_tasks(self) -> None:
        """测试写入空任务列表"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            (root / "data").mkdir(parents=True, exist_ok=True)

            config = load_config(root)
            write_tasks_snapshot(config, [])

            snapshot_path = root / "data" / "ipc" / "current_tasks.json"
            self.assertTrue(snapshot_path.exists())

            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(data, [])

    def test_write_single_task(self) -> None:
        """测试写入单个任务"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            (root / "data").mkdir(parents=True, exist_ok=True)

            config = load_config(root)

            task = ScheduledTask(
                id="test-id",
                group_folder="main",
                chat_jid="feishu:chat1",
                prompt="Hello, world!",
                schedule_type="cron",
                schedule_value="0 * * * *",
                context_mode="group",
                next_run="2026-01-01T01:00:00Z",
                last_run=None,
                last_result=None,
                status="active",
                created_at="2026-01-01T00:00:00Z",
            )

            write_tasks_snapshot(config, [task])

            snapshot_path = root / "data" / "ipc" / "current_tasks.json"
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))

            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["id"], "test-id")
            self.assertEqual(data[0]["groupFolder"], "main")
            self.assertEqual(data[0]["prompt"], "Hello, world!")
            self.assertEqual(data[0]["schedule_type"], "cron")

    def test_write_multiple_tasks(self) -> None:
        """测试写入多个任务"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            (root / "data").mkdir(parents=True, exist_ok=True)

            config = load_config(root)

            tasks = [
                ScheduledTask(
                    id=f"task-{i}",
                    group_folder="main",
                    chat_jid="feishu:chat1",
                    prompt=f"Task {i}",
                    schedule_type="interval",
                    schedule_value="60000",
                    context_mode="isolated",
                    next_run=None,
                    last_run=None,
                    last_result=None,
                    status="active",
                    created_at="2026-01-01T00:00:00Z",
                )
                for i in range(3)
            ]

            write_tasks_snapshot(config, tasks)

            snapshot_path = root / "data" / "ipc" / "current_tasks.json"
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))

            self.assertEqual(len(data), 3)
            self.assertEqual(data[0]["id"], "task-0")
            self.assertEqual(data[1]["id"], "task-1")
            self.assertEqual(data[2]["id"], "task-2")

    def test_atomic_write(self) -> None:
        """测试原子写入"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            (root / "data").mkdir(parents=True, exist_ok=True)

            config = load_config(root)

            # 第一次写入
            task1 = ScheduledTask(
                id="task-1",
                group_folder="main",
                chat_jid="feishu:chat1",
                prompt="Task 1",
                schedule_type="cron",
                schedule_value="0 * * * *",
                context_mode="group",
                next_run="2026-01-01T01:00:00Z",
                last_run=None,
                last_result=None,
                status="active",
                created_at="2026-01-01T00:00:00Z",
            )
            write_tasks_snapshot(config, [task1])

            # 第二次写入应该覆盖
            task2 = ScheduledTask(
                id="task-2",
                group_folder="main",
                chat_jid="feishu:chat1",
                prompt="Task 2",
                schedule_type="interval",
                schedule_value="60000",
                context_mode="isolated",
                next_run=None,
                last_run=None,
                last_result=None,
                status="active",
                created_at="2026-01-01T00:00:00Z",
            )
            write_tasks_snapshot(config, [task2])

            snapshot_path = root / "data" / "ipc" / "current_tasks.json"
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))

            # 应该只有第二次写入的任务
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["id"], "task-2")

            # 临时文件不应该存在
            tmp_path = snapshot_path.with_suffix(".json.tmp")
            self.assertFalse(tmp_path.exists())


if __name__ == "__main__":
    unittest.main()
