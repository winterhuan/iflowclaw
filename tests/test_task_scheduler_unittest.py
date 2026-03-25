"""task_scheduler 模块单元测试"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from iflowclaw.task_scheduler import _parse_iso, _to_utc_iso, compute_next_run
from iflowclaw.types import ScheduledTask


class TestTimeUtils(unittest.TestCase):
    """时间工具函数测试"""

    def test_parse_iso(self) -> None:
        """测试 ISO 时间解析"""
        # 带 Z 后缀
        dt = _parse_iso("2026-01-01T00:00:00Z")
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 1)
        self.assertEqual(dt.day, 1)

        # 带时区偏移
        dt = _parse_iso("2026-01-01T08:00:00+08:00")
        self.assertEqual(dt.hour, 0)  # 转换为 UTC

    def test_to_utc_iso(self) -> None:
        """测试转换为 UTC ISO 格式"""
        dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        iso = _to_utc_iso(dt)
        self.assertEqual(iso, "2026-01-01T00:00:00Z")

        # 带时区的时间
        from zoneinfo import ZoneInfo

        dt_shanghai = datetime(2026, 1, 1, 8, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        iso = _to_utc_iso(dt_shanghai)
        self.assertEqual(iso, "2026-01-01T00:00:00Z")


class TestComputeNextRun(unittest.TestCase):
    """计算下次运行时间测试"""

    def test_once_schedule(self) -> None:
        """测试一次性任务"""
        task = ScheduledTask(
            id="test-1",
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="test",
            schedule_type="once",
            schedule_value="2026-01-01T10:00:00",
            context_mode="isolated",
            next_run="2026-01-01T10:00:00Z",
            last_run=None,
            last_result=None,
            status="active",
            created_at="2026-01-01T00:00:00Z",
        )

        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = compute_next_run(task, now_utc=now, timezone_name="Asia/Shanghai")

        # 一次性任务没有下次运行
        self.assertIsNone(result)

    def test_interval_schedule(self) -> None:
        """测试间隔任务"""
        task = ScheduledTask(
            id="test-2",
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="test",
            schedule_type="interval",
            schedule_value="60000",  # 60秒
            context_mode="isolated",
            next_run=None,
            last_run=None,
            last_result=None,
            status="active",
            created_at="2026-01-01T00:00:00Z",
        )

        now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        result = compute_next_run(task, now_utc=now, timezone_name="Asia/Shanghai")

        self.assertIsNotNone(result)
        # 下次运行应该是 60 秒后
        next_run = _parse_iso(result)  # type: ignore[arg-type]
        expected = now + timedelta(seconds=60)
        self.assertAlmostEqual(next_run.timestamp(), expected.timestamp(), delta=1)

    def test_interval_schedule_with_last_run(self) -> None:
        """测试有上次运行时间的间隔任务"""
        task = ScheduledTask(
            id="test-3",
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="test",
            schedule_type="interval",
            schedule_value="300000",  # 5分钟
            context_mode="isolated",
            next_run=None,
            last_run="2026-01-01T00:00:00Z",
            last_result=None,
            status="active",
            created_at="2026-01-01T00:00:00Z",
        )

        now = datetime(2026, 1, 1, 0, 10, 0, tzinfo=UTC)  # 10分钟后
        result = compute_next_run(task, now_utc=now, timezone_name="Asia/Shanghai")

        self.assertIsNotNone(result)
        # 下次运行应该基于 last_run 计算
        next_run = _parse_iso(result)  # type: ignore[arg-type]
        self.assertGreater(next_run, now)

    def test_interval_schedule_invalid(self) -> None:
        """测试无效的间隔值"""
        task = ScheduledTask(
            id="test-4",
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="test",
            schedule_type="interval",
            schedule_value="0",  # 无效的间隔
            context_mode="isolated",
            next_run=None,
            last_run=None,
            last_result=None,
            status="active",
            created_at="2026-01-01T00:00:00Z",
        )

        now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        result = compute_next_run(task, now_utc=now, timezone_name="Asia/Shanghai")

        # 应该回退到 60 秒
        self.assertIsNotNone(result)
        next_run = _parse_iso(result)  # type: ignore[arg-type]
        expected = now + timedelta(seconds=60)
        self.assertAlmostEqual(next_run.timestamp(), expected.timestamp(), delta=1)

    def test_cron_schedule(self) -> None:
        """测试 cron 调度"""
        task = ScheduledTask(
            id="test-5",
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="test",
            schedule_type="cron",
            schedule_value="0 * * * *",  # 每小时
            context_mode="isolated",
            next_run=None,
            last_run=None,
            last_result=None,
            status="active",
            created_at="2026-01-01T00:00:00Z",
        )

        now = datetime(2026, 1, 1, 0, 30, 0, tzinfo=UTC)  # 00:30
        result = compute_next_run(task, now_utc=now, timezone_name="UTC")

        self.assertIsNotNone(result)
        # 下次运行应该是 01:00
        next_run = _parse_iso(result)  # type: ignore[arg-type]
        self.assertEqual(next_run.hour, 1)
        self.assertEqual(next_run.minute, 0)

    def test_cron_schedule_daily(self) -> None:
        """测试每日 cron 调度"""
        task = ScheduledTask(
            id="test-6",
            group_folder="main",
            chat_jid="feishu:chat1",
            prompt="test",
            schedule_type="cron",
            schedule_value="0 9 * * *",  # 每天 9 点
            context_mode="isolated",
            next_run=None,
            last_run=None,
            last_result=None,
            status="active",
            created_at="2026-01-01T00:00:00Z",
        )

        now = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)  # 10:00
        result = compute_next_run(task, now_utc=now, timezone_name="Asia/Shanghai")

        self.assertIsNotNone(result)
        # 下次运行应该是明天 9 点（上海时间）
        next_run = _parse_iso(result)  # type: ignore[arg-type]
        # 上海时间 9 点 = UTC 1 点
        self.assertEqual(next_run.hour, 1)


class TestScheduledTask(unittest.TestCase):
    """ScheduledTask 数据类测试"""

    def test_task_creation(self) -> None:
        """测试任务创建"""
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

        self.assertEqual(task.id, "test-id")
        self.assertEqual(task.group_folder, "main")
        self.assertEqual(task.chat_jid, "feishu:chat1")
        self.assertEqual(task.prompt, "Hello, world!")
        self.assertEqual(task.schedule_type, "cron")
        self.assertEqual(task.schedule_value, "0 * * * *")
        self.assertEqual(task.context_mode, "group")
        self.assertEqual(task.status, "active")


if __name__ == "__main__":
    unittest.main()
