from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from iflowclaw.mcps.ipc_mcp_stdio import write_ipc_file


class TestIpcMcp(unittest.TestCase):
    def test_write_ipc_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            msg_dir = Path(td) / "messages"
            data = {
                "type": "message",
                "chatJid": "feishu:chat1",
                "text": "hello",
                "groupFolder": "main",
            }
            write_ipc_file(msg_dir, data)

            files = list(msg_dir.glob("*.json"))
            self.assertEqual(len(files), 1)
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["type"], "message")
            self.assertEqual(payload["text"], "hello")


if __name__ == "__main__":
    unittest.main()
