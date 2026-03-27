"""agents 模块单元测试"""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from iflowclaw.agents.backends.agno import _resolve_model as resolve_agno_model
from iflowclaw.agents.backends.base import BackendConfigError, BackendContext, BackendResult
from iflowclaw.agents.prompting import _process_agents_markdown, build_system_prompt
from iflowclaw.agents.runner import AgentRunner, _resolve_execution_mode
from iflowclaw.config import load_config
from iflowclaw.types import AgentConfig, AgentInput


class TestBackendContext(unittest.TestCase):
    """BackendContext 数据类测试"""

    def test_context_creation(self) -> None:
        """测试上下文创建"""
        context = BackendContext(
            group_folder="test_group",
            chat_jid="feishu:test_chat",
            is_main=False,
            session_id="test_session",
            group_dir="/test/group",
            ipc_dir="/test/ipc",
            system_prompt="Test prompt",
            timeout_s=60.0,
        )

        self.assertEqual(context.group_folder, "test_group")
        self.assertEqual(context.chat_jid, "feishu:test_chat")
        self.assertFalse(context.is_main)
        self.assertEqual(context.session_id, "test_session")
        self.assertEqual(context.group_dir, "/test/group")
        self.assertEqual(context.ipc_dir, "/test/ipc")
        self.assertEqual(context.system_prompt, "Test prompt")
        self.assertEqual(context.timeout_s, 60.0)

    def test_context_optional_fields(self) -> None:
        """测试可选字段"""
        context = BackendContext(
            group_folder="test_group",
            chat_jid="feishu:test_chat",
            is_main=True,
            session_id=None,
            group_dir="/test/group",
            ipc_dir="/test/ipc",
            system_prompt=None,
            timeout_s=30.0,
        )

        self.assertIsNone(context.session_id)
        self.assertIsNone(context.system_prompt)


class TestBackendResult(unittest.TestCase):
    """BackendResult 数据类测试"""

    def test_success_result(self) -> None:
        """测试成功结果"""
        result = BackendResult(
            status="success",
            text="Hello, world!",
            new_session_id="session-123",
            error=None,
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.text, "Hello, world!")
        self.assertEqual(result.new_session_id, "session-123")
        self.assertIsNone(result.error)

    def test_error_result(self) -> None:
        """测试错误结果"""
        result = BackendResult(
            status="error",
            text="",
            new_session_id=None,
            error="Something went wrong",
        )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.text, "")
        self.assertIsNone(result.new_session_id)
        self.assertEqual(result.error, "Something went wrong")


class TestAgentInput(unittest.TestCase):
    """AgentInput 数据类测试"""

    def test_input_creation(self) -> None:
        """测试输入创建"""
        agent_input = AgentInput(
            prompt="Hello",
            group_folder="test_group",
            chat_jid="feishu:test_chat",
            is_main=False,
            session_id="session-123",
            is_scheduled_task=False,
            assistant_name="TestBot",
        )

        self.assertEqual(agent_input.prompt, "Hello")
        self.assertEqual(agent_input.group_folder, "test_group")
        self.assertEqual(agent_input.chat_jid, "feishu:test_chat")
        self.assertFalse(agent_input.is_main)
        self.assertEqual(agent_input.session_id, "session-123")
        self.assertFalse(agent_input.is_scheduled_task)
        self.assertEqual(agent_input.assistant_name, "TestBot")

    def test_input_defaults(self) -> None:
        """测试默认值"""
        agent_input = AgentInput(
            prompt="Hello",
            group_folder="test_group",
            chat_jid="feishu:test_chat",
            is_main=False,
        )

        self.assertIsNone(agent_input.session_id)
        self.assertFalse(agent_input.is_scheduled_task)
        self.assertIsNone(agent_input.assistant_name)
        self.assertEqual(agent_input.extension_input, {})


class TestAgentConfig(unittest.TestCase):
    """AgentConfig 数据类测试"""

    def test_config_defaults(self) -> None:
        """测试默认配置"""
        config = AgentConfig()

        self.assertIsNone(config.backend)
        self.assertIsNone(config.model)
        self.assertIsNone(config.system_prompt)
        self.assertIsNone(config.execution_mode)
        self.assertIsNone(config.timeout)
        self.assertEqual(config.metadata, {})

    def test_config_custom(self) -> None:
        """测试自定义配置"""
        config = AgentConfig(
            backend="claude",
            model="sonnet",
            system_prompt="You are helpful",
            execution_mode="container",
            timeout=60000,
            metadata={"key": "value"},
        )

        self.assertEqual(config.backend, "claude")
        self.assertEqual(config.model, "sonnet")
        self.assertEqual(config.system_prompt, "You are helpful")
        self.assertEqual(config.execution_mode, "container")
        self.assertEqual(config.timeout, 60000)
        self.assertEqual(config.metadata, {"key": "value"})


class TestResolveExecutionMode(unittest.TestCase):
    """执行模式解析测试"""

    def setUp(self) -> None:
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        root = Path(self.temp_dir)
        (root / "store").mkdir(parents=True, exist_ok=True)
        os.environ["FEISHU_APP_ID"] = "test_id"
        os.environ["FEISHU_APP_SECRET"] = "test_secret"
        self.config = load_config(root)

    def tearDown(self) -> None:
        """清理测试环境"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_explicit_execution_mode(self) -> None:
        """测试显式指定的执行模式"""
        agent_config = AgentConfig(execution_mode="container")

        mode = _resolve_execution_mode(agent_config, self.config, is_main=False)
        self.assertEqual(mode, "container")

        mode = _resolve_execution_mode(agent_config, self.config, is_main=True)
        self.assertEqual(mode, "container")

    def test_main_group_default_direct(self) -> None:
        """测试主群默认执行模式（direct）"""
        self.config.default_execution_mode = "direct"
        agent_config = AgentConfig()

        mode = _resolve_execution_mode(agent_config, self.config, is_main=True)
        self.assertEqual(mode, "direct")

    def test_main_group_default_container(self) -> None:
        """测试主群默认执行模式（container）"""
        self.config.default_execution_mode = "container"
        agent_config = AgentConfig()

        mode = _resolve_execution_mode(agent_config, self.config, is_main=True)
        self.assertEqual(mode, "container")

    def test_non_main_group_default_direct(self) -> None:
        """测试非主群默认执行模式（direct -> container）"""
        self.config.default_execution_mode = "direct"
        agent_config = AgentConfig()

        mode = _resolve_execution_mode(agent_config, self.config, is_main=False)
        self.assertEqual(mode, "container")

    def test_non_main_group_default_container(self) -> None:
        """测试非主群默认执行模式（container）"""
        self.config.default_execution_mode = "container"
        agent_config = AgentConfig()

        mode = _resolve_execution_mode(agent_config, self.config, is_main=False)
        self.assertEqual(mode, "container")


class TestAgnoBackendConfig(unittest.TestCase):
    def test_agno_rejects_non_openai_provider(self) -> None:
        with self.assertRaises(BackendConfigError):
            resolve_agno_model("anthropic:claude-sonnet")

    def test_agno_accepts_plain_openai_model_name(self) -> None:
        fake_agno = types.ModuleType("agno")
        fake_agno_models = types.ModuleType("agno.models")
        fake_module = types.ModuleType("agno.models.openai")

        class _FakeOpenAIChat:
            def __init__(self, *, id: str) -> None:
                self.id = id

        fake_module.OpenAIChat = _FakeOpenAIChat

        with patch.dict(
            sys.modules,
            {
                "agno": fake_agno,
                "agno.models": fake_agno_models,
                "agno.models.openai": fake_module,
            },
        ):
            model = resolve_agno_model("gpt-4o")

        self.assertEqual(model.id, "gpt-4o")


class TestProcessAgentsMarkdown(unittest.TestCase):
    """AGENTS.md 模板处理测试"""

    def test_template_replacement(self) -> None:
        """测试模板变量替换"""
        content = "Group: {{GROUP_DIR}}\nGlobal: {{GLOBAL_DIR}}\nIPC: {{IPC_DIR}}"
        result = _process_agents_markdown(
            content,
            group_dir=Path("/test/group"),
            global_dir=Path("/test/global"),
            ipc_dir=Path("/test/ipc"),
        )

        # 使用 os.sep 适配 Windows 路径分隔符
        self.assertIn(str(Path("/test/group")), result)
        self.assertIn(str(Path("/test/global")), result)
        self.assertIn(str(Path("/test/ipc")), result)
        self.assertNotIn("{{GROUP_DIR}}", result)

    def test_no_templates(self) -> None:
        """测试没有模板变量"""
        content = "Hello World"
        result = _process_agents_markdown(
            content,
            group_dir=Path("/test/group"),
            global_dir=Path("/test/global"),
            ipc_dir=Path("/test/ipc"),
        )

        self.assertEqual(result, "Hello World")


class TestBuildSystemPrompt(unittest.TestCase):
    """系统提示词构建测试"""

    def setUp(self) -> None:
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        root = Path(self.temp_dir)
        (root / "store").mkdir(parents=True, exist_ok=True)
        (root / "groups" / "test_group").mkdir(parents=True, exist_ok=True)
        (root / "groups" / "global").mkdir(parents=True, exist_ok=True)
        os.environ["FEISHU_APP_ID"] = "test_id"
        os.environ["FEISHU_APP_SECRET"] = "test_secret"
        self.config = load_config(root)

    def tearDown(self) -> None:
        """清理测试环境"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_build_with_group_agents(self) -> None:
        """测试包含组 AGENTS.md"""
        agents_file = self.config.groups_dir / "test_group" / "AGENTS.md"
        agents_file.write_text("Group instructions", encoding="utf-8")

        prompt = build_system_prompt(self.config, group_folder="test_group", is_main=True)

        self.assertIsNotNone(prompt)
        self.assertIn("Group instructions", prompt)  # type: ignore[union-attr]

    def test_build_with_global_agents(self) -> None:
        """测试包含全局 AGENTS.md"""
        global_agents = self.config.groups_dir / "global" / "AGENTS.md"
        global_agents.write_text("Global instructions", encoding="utf-8")

        prompt = build_system_prompt(self.config, group_folder="test_group", is_main=False)

        self.assertIsNotNone(prompt)
        self.assertIn("Global instructions", prompt)  # type: ignore[union-attr]

    def test_build_with_both(self) -> None:
        """测试同时包含组和全局 AGENTS.md"""
        group_agents = self.config.groups_dir / "test_group" / "AGENTS.md"
        group_agents.write_text("Group instructions", encoding="utf-8")

        global_agents = self.config.groups_dir / "global" / "AGENTS.md"
        global_agents.write_text("Global instructions", encoding="utf-8")

        prompt = build_system_prompt(self.config, group_folder="test_group", is_main=False)

        self.assertIsNotNone(prompt)
        self.assertIn("Group instructions", prompt)  # type: ignore[union-attr]
        self.assertIn("Global instructions", prompt)  # type: ignore[union-attr]

    def test_build_without_agents(self) -> None:
        """测试没有 AGENTS.md"""
        prompt = build_system_prompt(self.config, group_folder="test_group", is_main=True)
        self.assertIsNone(prompt)


class TestAgentRunner(unittest.TestCase):
    """AgentRunner 测试"""

    def setUp(self) -> None:
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        root = Path(self.temp_dir)
        (root / "store").mkdir(parents=True, exist_ok=True)
        (root / "groups" / "test_group").mkdir(parents=True, exist_ok=True)
        (root / "data" / "ipc" / "test_group").mkdir(parents=True, exist_ok=True)
        os.environ["FEISHU_APP_ID"] = "test_id"
        os.environ["FEISHU_APP_SECRET"] = "test_secret"
        self.config = load_config(root)

    def tearDown(self) -> None:
        """清理测试环境"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_runner_creation(self) -> None:
        """测试运行器创建"""
        runner = AgentRunner(self.config)
        self.assertIsNotNone(runner)
        self.assertEqual(runner._config, self.config)


if __name__ == "__main__":
    unittest.main()
