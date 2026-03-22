from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iflowclaw.config import load_config
from iflowclaw.db import (
    get_all_registered_groups,
    get_messages_since,
    init_database,
    set_registered_group,
    store_message,
)
from iflowclaw.types import NewMessage, RegisteredGroup


class TestDb(unittest.TestCase):
    def test_store_and_query_messages(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            cfg = load_config(root)
            init_database(cfg, in_memory=True)

            msg = NewMessage(
                id="m1",
                chat_jid="feishu:chat1",
                sender="u1",
                sender_name="u1",
                content="hello",
                timestamp="2026-01-01T00:00:00Z",
                is_from_me=False,
                is_bot_message=False,
            )
            store_message(msg)
            got = get_messages_since("feishu:chat1", "", cfg.assistant_name)
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0].content, "hello")

    def test_registered_groups_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            cfg = load_config(root)
            init_database(cfg, in_memory=True)

            g = RegisteredGroup(
                name="main",
                folder="main",
                trigger="^@iFlow\\b",
                added_at="2026-01-01T00:00:00Z",
                requires_trigger=False,
                is_main=True,
            )
            set_registered_group("feishu:chat1", g)
            groups = get_all_registered_groups()
            self.assertIn("feishu:chat1", groups)
            self.assertEqual(groups["feishu:chat1"].folder, "main")


if __name__ == "__main__":
    unittest.main()

