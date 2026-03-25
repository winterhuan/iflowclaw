"""sender_allowlist 模块单元测试"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from iflowclaw.sender_allowlist import (
    ChatAllowlistEntry,
    SenderAllowlistConfig,
    is_sender_allowed,
    is_trigger_allowed,
    load_sender_allowlist,
    should_drop_message,
)


class TestSenderAllowlist(unittest.TestCase):
    """发送者白名单测试"""

    def test_default_config(self) -> None:
        """测试默认配置"""
        config = SenderAllowlistConfig()

        self.assertEqual(config.default.allow, "*")
        self.assertEqual(config.default.mode, "trigger")
        self.assertEqual(config.chats, {})
        self.assertTrue(config.log_denied)

    def test_is_sender_allowed_wildcard(self) -> None:
        """测试通配符允许"""
        config = SenderAllowlistConfig()

        # 默认通配符应该允许所有人
        self.assertTrue(is_sender_allowed("feishu:chat1", "user1", config))
        self.assertTrue(is_sender_allowed("feishu:chat1", "user2", config))

    def test_is_sender_allowed_specific(self) -> None:
        """测试特定用户允许"""
        config = SenderAllowlistConfig(
            default=ChatAllowlistEntry(allow=["user1", "user2"], mode="trigger")
        )

        self.assertTrue(is_sender_allowed("feishu:chat1", "user1", config))
        self.assertTrue(is_sender_allowed("feishu:chat1", "user2", config))
        self.assertFalse(is_sender_allowed("feishu:chat1", "user3", config))

    def test_is_sender_allowed_per_chat(self) -> None:
        """测试按聊天配置"""
        config = SenderAllowlistConfig(
            default=ChatAllowlistEntry(allow="*", mode="trigger"),
            chats={
                "feishu:chat1": ChatAllowlistEntry(allow=["user1"], mode="trigger"),
            },
        )

        # chat1 使用特定配置
        self.assertTrue(is_sender_allowed("feishu:chat1", "user1", config))
        self.assertFalse(is_sender_allowed("feishu:chat1", "user2", config))

        # chat2 使用默认配置
        self.assertTrue(is_sender_allowed("feishu:chat2", "user1", config))
        self.assertTrue(is_sender_allowed("feishu:chat2", "user2", config))

    def test_should_drop_message(self) -> None:
        """测试消息丢弃"""
        config = SenderAllowlistConfig(
            default=ChatAllowlistEntry(allow="*", mode="trigger"),
            chats={
                "feishu:chat1": ChatAllowlistEntry(allow="*", mode="drop"),
            },
        )

        # chat1 设置为 drop 模式
        self.assertTrue(should_drop_message("feishu:chat1", config))

        # chat2 使用默认 trigger 模式
        self.assertFalse(should_drop_message("feishu:chat2", config))

    def test_is_trigger_allowed(self) -> None:
        """测试触发词允许"""
        config = SenderAllowlistConfig(
            default=ChatAllowlistEntry(allow=["user1"], mode="trigger")
        )

        # 允许的用户
        self.assertTrue(is_trigger_allowed("feishu:chat1", "user1", config))

        # 不允许的用户（会记录日志但返回 False）
        self.assertFalse(is_trigger_allowed("feishu:chat1", "user2", config))


class TestLoadSenderAllowlist(unittest.TestCase):
    """加载发送者白名单测试"""

    def test_load_from_file(self) -> None:
        """测试从文件加载"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "allowlist.json"
            data = {
                "default": {"allow": "*", "mode": "trigger"},
                "chats": {
                    "feishu:chat1": {"allow": ["user1", "user2"], "mode": "trigger"},
                    "feishu:chat2": {"allow": "*", "mode": "drop"},
                },
                "logDenied": False,
            }
            path.write_text(json.dumps(data), encoding="utf-8")

            config = load_sender_allowlist(path)

            self.assertEqual(config.default.allow, "*")
            self.assertEqual(config.default.mode, "trigger")
            self.assertIn("feishu:chat1", config.chats)
            self.assertEqual(config.chats["feishu:chat1"].allow, ["user1", "user2"])
            self.assertEqual(config.chats["feishu:chat2"].mode, "drop")
            self.assertFalse(config.log_denied)

    def test_load_nonexistent_file(self) -> None:
        """测试加载不存在的文件"""
        path = Path("/nonexistent/path/allowlist.json")
        config = load_sender_allowlist(path)

        # 应该返回默认配置
        self.assertEqual(config.default.allow, "*")
        self.assertEqual(config.default.mode, "trigger")

    def test_load_invalid_json(self) -> None:
        """测试加载无效 JSON"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "allowlist.json"
            path.write_text("invalid json", encoding="utf-8")

            config = load_sender_allowlist(path)

            # 应该返回默认配置
            self.assertEqual(config.default.allow, "*")

    def test_load_partial_config(self) -> None:
        """测试加载部分配置"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "allowlist.json"
            data = {
                "default": {"allow": ["user1"]},
                # 缺少 chats 和 logDenied
            }
            path.write_text(json.dumps(data), encoding="utf-8")

            config = load_sender_allowlist(path)

            self.assertEqual(config.default.allow, ["user1"])
            self.assertEqual(config.default.mode, "trigger")  # 默认值
            self.assertTrue(config.log_denied)  # 默认值


class TestChatAllowlistEntry(unittest.TestCase):
    """ChatAllowlistEntry 数据类测试"""

    def test_default_entry(self) -> None:
        """测试默认条目"""
        entry = ChatAllowlistEntry()
        self.assertEqual(entry.allow, "*")
        self.assertEqual(entry.mode, "trigger")

    def test_custom_entry(self) -> None:
        """测试自定义条目"""
        entry = ChatAllowlistEntry(allow=["user1", "user2"], mode="drop")
        self.assertEqual(entry.allow, ["user1", "user2"])
        self.assertEqual(entry.mode, "drop")


if __name__ == "__main__":
    unittest.main()
