from __future__ import annotations

import unittest

from iflowclaw.router import format_messages, strip_internal_tags
from iflowclaw.types import NewMessage


class TestRouter(unittest.TestCase):
    def test_format_messages_contains_xml(self) -> None:
        msgs = [
            NewMessage(
                id="1",
                chat_jid="feishu:chat1",
                sender="u1",
                sender_name="Alice",
                content="Hello <world>",
                timestamp="2026-01-01T00:00:00Z",
            )
        ]
        xml = format_messages(msgs, "Asia/Shanghai")
        self.assertIn("<messages>", xml)
        self.assertIn("&lt;world&gt;", xml)

    def test_strip_internal(self) -> None:
        raw = "hi\n<internal>secret</internal>\nthere"
        self.assertEqual(strip_internal_tags(raw), "hi\n\nthere".strip())


if __name__ == "__main__":
    unittest.main()

