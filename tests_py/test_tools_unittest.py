from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from iflowclaw.config import load_config
from iflowclaw.tools import IpcToolWriter


class TestTools(unittest.TestCase):
    def test_ipc_tool_writer_writes_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "data" / "ipc" / "main").mkdir(parents=True, exist_ok=True)
            cfg = load_config(root)

            w = IpcToolWriter(cfg, group_folder="main", chat_jid="feishu:chat1", is_main=True)
            w.write_message(text="hello")

            msg_dir = root / "data" / "ipc" / "main" / "messages"
            files = list(msg_dir.glob("*.json"))
            self.assertEqual(len(files), 1)
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["type"], "message")
            self.assertEqual(payload["text"], "hello")


if __name__ == "__main__":
    unittest.main()

