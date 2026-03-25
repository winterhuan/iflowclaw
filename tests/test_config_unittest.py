"""配置模块单元测试"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from iflowclaw.config import BackendCredentials, load_config


class TestEnvFile(unittest.TestCase):
    """环境变量文件解析测试"""

    def test_load_config_with_env_file(self) -> None:
        """测试从 .env 文件加载配置"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            env_file = root / ".env"
            env_file.write_text(
                "FEISHU_APP_ID=test_id\n"
                "FEISHU_APP_SECRET=test_secret\n"
                "ASSISTANT_NAME=TestBot\n"
                "AGENT_BACKEND=claude\n"
                "AGENT_TIMEOUT=60000\n",
                encoding="utf-8",
            )

            config = load_config(root)

            self.assertEqual(config.feishu_app_id, "test_id")
            self.assertEqual(config.feishu_app_secret, "test_secret")
            self.assertEqual(config.assistant_name, "TestBot")
            self.assertEqual(config.default_backend, "claude")
            self.assertEqual(config.agent_timeout_ms, 60000)

    def test_load_config_without_env_file(self) -> None:
        """测试没有 .env 文件时使用默认值"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)

            # 清除环境变量
            old_app_id = os.environ.get("FEISHU_APP_ID")
            old_app_secret = os.environ.get("FEISHU_APP_SECRET")
            if "FEISHU_APP_ID" in os.environ:
                del os.environ["FEISHU_APP_ID"]
            if "FEISHU_APP_SECRET" in os.environ:
                del os.environ["FEISHU_APP_SECRET"]

            try:
                config = load_config(root)
                self.assertEqual(config.assistant_name, "iFlow")  # 默认值
                self.assertEqual(config.agent_timeout_ms, 300000)  # 默认值
            finally:
                if old_app_id:
                    os.environ["FEISHU_APP_ID"] = old_app_id
                if old_app_secret:
                    os.environ["FEISHU_APP_SECRET"] = old_app_secret

    def test_env_file_with_comments_and_empty_lines(self) -> None:
        """测试 .env 文件中的注释和空行"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            env_file = root / ".env"
            env_file.write_text(
                "# This is a comment\n"
                "\n"
                "FEISHU_APP_ID=test_id\n"
                "  \n"
                "# Another comment\n"
                "FEISHU_APP_SECRET=test_secret\n",
                encoding="utf-8",
            )

            config = load_config(root)
            self.assertEqual(config.feishu_app_id, "test_id")
            self.assertEqual(config.feishu_app_secret, "test_secret")

    def test_env_file_with_quoted_values(self) -> None:
        """测试 .env 文件中带引号的值"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            env_file = root / ".env"
            env_file.write_text(
                'FEISHU_APP_ID="quoted_id"\n'
                "FEISHU_APP_SECRET='single_quoted'\n",
                encoding="utf-8",
            )

            # 清除环境变量以确保 .env 文件的值生效
            old_app_id = os.environ.get("FEISHU_APP_ID")
            old_app_secret = os.environ.get("FEISHU_APP_SECRET")
            if "FEISHU_APP_ID" in os.environ:
                del os.environ["FEISHU_APP_ID"]
            if "FEISHU_APP_SECRET" in os.environ:
                del os.environ["FEISHU_APP_SECRET"]

            try:
                config = load_config(root)
                self.assertEqual(config.feishu_app_id, "quoted_id")
                self.assertEqual(config.feishu_app_secret, "single_quoted")
            finally:
                if old_app_id:
                    os.environ["FEISHU_APP_ID"] = old_app_id
                if old_app_secret:
                    os.environ["FEISHU_APP_SECRET"] = old_app_secret


class TestAppConfig(unittest.TestCase):
    """AppConfig 数据类测试"""

    def test_config_default_values(self) -> None:
        """测试配置默认值"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            os.environ["FEISHU_APP_ID"] = "test_id"
            os.environ["FEISHU_APP_SECRET"] = "test_secret"

            config = load_config(root)

            self.assertEqual(config.poll_interval_ms, 2000)
            self.assertEqual(config.scheduler_poll_interval_ms, 60000)
            self.assertEqual(config.ipc_poll_interval_ms, 1000)
            self.assertEqual(config.max_concurrent_agents, 5)
            self.assertEqual(config.default_backend, "iflow")
            self.assertEqual(config.default_execution_mode, "direct")

    def test_config_trigger_pattern(self) -> None:
        """测试触发词正则表达式"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            os.environ["FEISHU_APP_ID"] = "test_id"
            os.environ["FEISHU_APP_SECRET"] = "test_secret"

            # 保存并设置 ASSISTANT_NAME
            old_assistant_name = os.environ.get("ASSISTANT_NAME")
            os.environ["ASSISTANT_NAME"] = "TestBot"

            try:
                config = load_config(root)

                self.assertTrue(config.trigger_pattern.search("@TestBot hello"))
                self.assertTrue(config.trigger_pattern.search("@testbot hello"))
                self.assertFalse(config.trigger_pattern.search("@Other hello"))
                self.assertFalse(config.trigger_pattern.search("TestBot hello"))
            finally:
                # 恢复原来的值
                if old_assistant_name is not None:
                    os.environ["ASSISTANT_NAME"] = old_assistant_name
                elif "ASSISTANT_NAME" in os.environ:
                    del os.environ["ASSISTANT_NAME"]

    def test_config_backend_credential(self) -> None:
        """测试后端凭证配置"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            os.environ["FEISHU_APP_ID"] = "test_id"
            os.environ["FEISHU_APP_SECRET"] = "test_secret"
            os.environ["ANTHROPIC_API_KEY"] = "sk-test-123"
            os.environ["OPENAI_API_KEY"] = "sk-openai-456"

            config = load_config(root)

            self.assertEqual(config.credentials.anthropic_api_key, "sk-test-123")
            self.assertEqual(config.credentials.openai_api_key, "sk-openai-456")

    def test_config_directory_paths(self) -> None:
        """测试目录路径配置"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            os.environ["FEISHU_APP_ID"] = "test_id"
            os.environ["FEISHU_APP_SECRET"] = "test_secret"

            config = load_config(root)

            self.assertEqual(config.project_root, root)
            self.assertEqual(config.store_dir, root / "store")
            self.assertEqual(config.groups_dir, root / "groups")
            self.assertEqual(config.data_dir, root / "data")
            self.assertEqual(config.logs_dir, root / "logs")


class TestBackendCredentials(unittest.TestCase):
    """BackendCredentials 数据类测试"""

    def test_default_credentials(self) -> None:
        """测试默认凭证"""
        creds = BackendCredentials()
        self.assertIsNone(creds.anthropic_api_key)
        self.assertEqual(creds.anthropic_base_url, "https://api.anthropic.com")
        self.assertIsNone(creds.claude_oauth_token)
        self.assertIsNone(creds.openai_api_key)
        self.assertEqual(creds.openai_base_url, "https://api.openai.com")

    def test_custom_credentials(self) -> None:
        """测试自定义凭证"""
        creds = BackendCredentials(
            anthropic_api_key="sk-test",
            anthropic_base_url="https://custom.api.com",
            claude_oauth_token="oauth-token",
            openai_api_key="sk-openai",
            openai_base_url="https://custom.openai.com",
        )
        self.assertEqual(creds.anthropic_api_key, "sk-test")
        self.assertEqual(creds.anthropic_base_url, "https://custom.api.com")
        self.assertEqual(creds.claude_oauth_token, "oauth-token")
        self.assertEqual(creds.openai_api_key, "sk-openai")
        self.assertEqual(creds.openai_base_url, "https://custom.openai.com")


if __name__ == "__main__":
    unittest.main()
