"""router 模块扩展单元测试"""

from __future__ import annotations

import unittest

from iflowclaw.router import (
    escape_xml,
    find_channel,
    format_local_time,
    format_messages,
    format_outbound,
    strip_internal_tags,
)
from iflowclaw.types import Channel, NewMessage


class MockChannel:
    """模拟 Channel 实现"""

    def __init__(self, name: str, owned_jids: set[str]) -> None:
        self.name = name
        self._owned_jids = owned_jids
        self._connected = True

    async def connect(self) -> None:
        self._connected = True

    async def send_message(self, jid: str, text: str) -> None:
        pass

    def is_connected(self) -> bool:
        return self._connected

    def owns_jid(self, jid: str) -> bool:
        return jid in self._owned_jids

    async def disconnect(self) -> None:
        self._connected = False

    async def set_typing(self, jid: str, is_typing: bool) -> None:
        pass


class TestEscapeXml(unittest.TestCase):
    """XML 转义测试"""

    def test_escape_special_chars(self) -> None:
        """测试特殊字符转义"""
        self.assertEqual(escape_xml("<script>alert('xss')</script>"), "&lt;script&gt;alert('xss')&lt;/script&gt;")
        self.assertEqual(escape_xml('He said "hello"'), "He said &quot;hello&quot;")
        self.assertEqual(escape_xml("A & B"), "A &amp; B")

    def test_escape_empty_string(self) -> None:
        """测试空字符串"""
        self.assertEqual(escape_xml(""), "")

    def test_escape_none(self) -> None:
        """测试 None（应该返回空字符串）"""
        # 函数签名是 str，但实际可能传入 None
        self.assertEqual(escape_xml(None), "")  # type: ignore[arg-type]

    def test_escape_normal_string(self) -> None:
        """测试普通字符串"""
        self.assertEqual(escape_xml("hello world"), "hello world")


class TestFormatLocalTime(unittest.TestCase):
    """本地时间格式化测试"""

    def test_format_utc_time(self) -> None:
        """测试 UTC 时间格式化"""
        result = format_local_time("2026-01-01T00:00:00Z", "UTC")
        self.assertEqual(result, "2026-01-01 00:00:00")

    def test_format_shanghai_time(self) -> None:
        """测试上海时间格式化"""
        result = format_local_time("2026-01-01T00:00:00Z", "Asia/Shanghai")
        self.assertEqual(result, "2026-01-01 08:00:00")

    def test_format_with_offset(self) -> None:
        """测试带时区偏移的时间"""
        result = format_local_time("2026-01-01T08:00:00+08:00", "Asia/Shanghai")
        self.assertEqual(result, "2026-01-01 08:00:00")


class TestFormatMessages(unittest.TestCase):
    """消息格式化测试"""

    def test_format_single_message(self) -> None:
        """测试单条消息格式化"""
        messages = [
            NewMessage(
                id="1",
                chat_jid="feishu:chat1",
                sender="user1",
                sender_name="Alice",
                content="Hello, world!",
                timestamp="2026-01-01T00:00:00Z",
            )
        ]

        result = format_messages(messages, "UTC")

        self.assertIn("<messages>", result)
        self.assertIn("</messages>", result)
        self.assertIn('sender="Alice"', result)
        self.assertIn("Hello, world!", result)

    def test_format_multiple_messages(self) -> None:
        """测试多条消息格式化"""
        messages = [
            NewMessage(
                id="1",
                chat_jid="feishu:chat1",
                sender="user1",
                sender_name="Alice",
                content="Hello",
                timestamp="2026-01-01T00:00:00Z",
            ),
            NewMessage(
                id="2",
                chat_jid="feishu:chat1",
                sender="user2",
                sender_name="Bob",
                content="Hi there",
                timestamp="2026-01-01T00:01:00Z",
            ),
        ]

        result = format_messages(messages, "UTC")

        self.assertIn("Alice", result)
        self.assertIn("Bob", result)
        self.assertIn("Hello", result)
        self.assertIn("Hi there", result)

    def test_format_empty_messages(self) -> None:
        """测试空消息列表"""
        result = format_messages([], "UTC")
        self.assertIn("<messages>", result)
        self.assertIn("</messages>", result)

    def test_format_message_with_special_chars(self) -> None:
        """测试包含特殊字符的消息"""
        messages = [
            NewMessage(
                id="1",
                chat_jid="feishu:chat1",
                sender="user1",
                sender_name="Alice",
                content="<script>alert('xss')</script>",
                timestamp="2026-01-01T00:00:00Z",
            )
        ]

        result = format_messages(messages, "UTC")

        self.assertIn("&lt;script&gt;", result)
        self.assertNotIn("<script>", result)


class TestStripInternalTags(unittest.TestCase):
    """内部标签剥离测试"""

    def test_strip_single_tag(self) -> None:
        """测试剥离单个标签"""
        raw = "Hello\n<internal>secret info</internal>\nWorld"
        result = strip_internal_tags(raw)
        self.assertEqual(result, "Hello\n\nWorld")

    def test_strip_multiple_tags(self) -> None:
        """测试剥离多个标签"""
        raw = "Start\n<internal>secret1</internal>\nMiddle\n<internal>secret2</internal>\nEnd"
        result = strip_internal_tags(raw)
        self.assertIn("Start", result)
        self.assertIn("Middle", result)
        self.assertIn("End", result)
        self.assertNotIn("secret1", result)
        self.assertNotIn("secret2", result)

    def test_strip_no_tags(self) -> None:
        """测试没有标签的情况"""
        raw = "Hello World"
        result = strip_internal_tags(raw)
        self.assertEqual(result, "Hello World")

    def test_strip_multiline_internal(self) -> None:
        """测试多行内部标签"""
        raw = "Hello\n<internal>\nline1\nline2\n</internal>\nWorld"
        result = strip_internal_tags(raw)
        self.assertIn("Hello", result)
        self.assertIn("World", result)
        self.assertNotIn("line1", result)


class TestFormatOutbound(unittest.TestCase):
    """出站消息格式化测试"""

    def test_format_outbound_normal(self) -> None:
        """测试正常出站消息"""
        result = format_outbound("Hello World")
        self.assertEqual(result, "Hello World")

    def test_format_outbound_with_internal(self) -> None:
        """测试包含内部标签的出站消息"""
        result = format_outbound("Hello\n<internal>secret</internal>\nWorld")
        self.assertIn("Hello", result)
        self.assertIn("World", result)
        self.assertNotIn("secret", result)


class TestFindChannel(unittest.TestCase):
    """查找频道测试"""

    def test_find_existing_channel(self) -> None:
        """测试查找存在的频道"""
        channels: list[Channel] = [
            MockChannel("feishu", {"feishu:chat1", "feishu:chat2"}),  # type: ignore[list-item]
            MockChannel("telegram", {"tg:chat3"}),  # type: ignore[list-item]
        ]

        result = find_channel(channels, "feishu:chat1")
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "feishu")  # type: ignore[union-attr]

    def test_find_nonexistent_channel(self) -> None:
        """测试查找不存在的频道"""
        channels: list[Channel] = [
            MockChannel("feishu", {"feishu:chat1"}),  # type: ignore[list-item]
        ]

        result = find_channel(channels, "tg:chat1")
        self.assertIsNone(result)

    def test_find_channel_empty_list(self) -> None:
        """测试空频道列表"""
        result = find_channel([], "feishu:chat1")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
