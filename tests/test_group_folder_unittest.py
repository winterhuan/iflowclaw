"""group_folder 模块单元测试"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from iflowclaw.config import load_config
from iflowclaw.group_folder import (
    RESERVED_FOLDERS,
    assert_valid_group_folder,
    is_valid_group_folder,
    resolve_group_folder_path,
    resolve_group_ipc_path,
)


class TestGroupFolderValidation(unittest.TestCase):
    """组文件夹名称验证测试"""

    def test_valid_folder_names(self) -> None:
        """测试有效的文件夹名称"""
        valid_names = [
            "main",
            "test-group",
            "test_group",
            "group123",
            "a",
            "A123",
            "my-group_2024",
            "123",  # 纯数字也有效
        ]
        for name in valid_names:
            with self.subTest(name=name):
                self.assertTrue(is_valid_group_folder(name), f"'{name}' should be valid")

    def test_invalid_folder_names(self) -> None:
        """测试无效的文件夹名称"""
        invalid_names = [
            "",  # 空字符串
            "global",  # 保留名称
            "GLOBAL",  # 保留名称（大小写不敏感）
            "with/slash",  # 包含斜杠
            "with\\backslash",  # 包含反斜杠
            "with..dot",  # 包含 ..
            "-startdash",  # 以破折号开头
            "_startunderscore",  # 以下划线开头
            "a" * 65,  # 超过64字符
            "has space",  # 包含空格
            "has\ttab",  # 包含制表符
        ]
        for name in invalid_names:
            with self.subTest(name=name):
                self.assertFalse(is_valid_group_folder(name), f"'{name}' should be invalid")

    def test_reserved_folders(self) -> None:
        """测试保留文件夹名称"""
        for reserved in RESERVED_FOLDERS:
            with self.subTest(reserved=reserved):
                self.assertFalse(is_valid_group_folder(reserved))

    def test_assert_valid_group_folder(self) -> None:
        """测试断言有效文件夹"""
        # 有效的不应该抛出异常
        assert_valid_group_folder("main")
        assert_valid_group_folder("test-group")

        # 无效的应该抛出异常
        with self.assertRaises(ValueError):
            assert_valid_group_folder("")
        with self.assertRaises(ValueError):
            assert_valid_group_folder("global")
        with self.assertRaises(ValueError):
            assert_valid_group_folder("with/slash")


class TestGroupFolderPath(unittest.TestCase):
    """组文件夹路径解析测试"""

    def test_resolve_group_folder_path(self) -> None:
        """测试解析组文件夹路径"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "groups").mkdir(parents=True, exist_ok=True)
            os.environ["FEISHU_APP_ID"] = "test_id"
            os.environ["FEISHU_APP_SECRET"] = "test_secret"

            config = load_config(root)
            path = resolve_group_folder_path(config, "test-group")

            self.assertEqual(path, (root / "groups" / "test-group").resolve())

    def test_resolve_group_folder_path_invalid(self) -> None:
        """测试无效的组文件夹路径"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "groups").mkdir(parents=True, exist_ok=True)
            os.environ["FEISHU_APP_ID"] = "test_id"
            os.environ["FEISHU_APP_SECRET"] = "test_secret"

            config = load_config(root)

            with self.assertRaises(ValueError):
                resolve_group_folder_path(config, "global")

            with self.assertRaises(ValueError):
                resolve_group_folder_path(config, "with/slash")

    def test_resolve_group_ipc_path(self) -> None:
        """测试解析组 IPC 路径"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "data" / "ipc").mkdir(parents=True, exist_ok=True)
            os.environ["FEISHU_APP_ID"] = "test_id"
            os.environ["FEISHU_APP_SECRET"] = "test_secret"

            config = load_config(root)
            path = resolve_group_ipc_path(config, "test-group")

            self.assertEqual(path, (root / "data" / "ipc" / "test-group").resolve())

    def test_resolve_group_ipc_path_invalid(self) -> None:
        """测试无效的组 IPC 路径"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "data" / "ipc").mkdir(parents=True, exist_ok=True)
            os.environ["FEISHU_APP_ID"] = "test_id"
            os.environ["FEISHU_APP_SECRET"] = "test_secret"

            config = load_config(root)

            with self.assertRaises(ValueError):
                resolve_group_ipc_path(config, "global")


if __name__ == "__main__":
    import os

    unittest.main()
