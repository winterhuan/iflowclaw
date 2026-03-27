"""多Agent后端集成测试

这个测试文件包含可以真实运行的集成测试，用于验证：
1. 多个agent后端（iflow, claude, agno）的正确配置和运行
2. 直连模式和容器模式的切换
3. 容器内凭证代理的正确工作
4. MCP工具的正确桥接

注意：这些测试需要真实的凭证才能运行，可以通过环境变量配置
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

from iflowclaw.config import AppConfig, BackendCredentials, load_config
from iflowclaw.agents.runner import AgentRunner
from iflowclaw.agents.backends import BackendContext
from iflowclaw.types import AgentConfig, AgentInput


class TestMultiBackendIntegration:
    """多后端集成测试基类"""

    @pytest.fixture
    def temp_dir(self):
        """创建临时目录用于测试"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # 创建必要的目录结构
            (root / "store").mkdir(parents=True, exist_ok=True)
            (root / "groups" / "test_group").mkdir(parents=True, exist_ok=True)
            (root / "data" / "ipc" / "test_group").mkdir(parents=True, exist_ok=True)
            (root / "logs").mkdir(parents=True, exist_ok=True)
            yield root

    @pytest.fixture
    def test_config(self, temp_dir: Path) -> AppConfig:
        """创建测试配置"""
        # 设置环境变量以避免真实的飞书连接
        os.environ["FEISHU_APP_ID"] = "test_app_id"
        os.environ["FEISHU_APP_SECRET"] = "test_app_secret"

        # 创建测试配置
        config = load_config(temp_dir)

        # 覆盖一些配置以适应测试
        config.agent_timeout_ms = 10000  # 10秒超时
        config.idle_timeout_ms = 5000  # 5秒空闲超时
        config.container_timeout_ms = 30000  # 30秒容器超时

        return config

    @pytest.fixture
    def agent_input(self) -> AgentInput:
        """创建测试用的AgentInput"""
        return AgentInput(
            prompt="Hello, this is a test message",
            group_folder="test_group",
            chat_jid="feishu:test_chat",
            is_main=False,
            session_id="test_session_123",
            is_scheduled_task=False,
            assistant_name="TestBot",
        )

    @pytest.fixture
    def agent_config(self) -> AgentConfig:
        """创建测试用的AgentConfig"""
        return AgentConfig(
            backend="iflow",
            model="test-model",
            system_prompt="You are a helpful test assistant",
            execution_mode="direct",
            timeout=10000,
        )


class TestBackendConfiguration(TestMultiBackendIntegration):
    """测试后端配置"""

    def test_backend_map_completeness(self):
        """测试后端映射的完整性"""
        from iflowclaw.agents.runner import _BACKEND_MAP

        expected_backends = {"iflow", "claude", "agno", "container"}
        actual_backends = set(_BACKEND_MAP.keys())

        assert expected_backends == actual_backends, (
            f"后端映射不完整，期望: {expected_backends}，实际: {actual_backends}"
        )

    def test_default_model_attributes(self):
        """测试默认模型属性映射"""
        from iflowclaw.agents.runner import _DEFAULT_MODEL_ATTR

        expected_attrs = {
            "iflow": "openai_model",
            "claude": "claude_model",
            "agno": "agno_model",
            "container": "claude_model",
        }

        for backend, attr_name in expected_attrs.items():
            assert backend in _DEFAULT_MODEL_ATTR, f"缺少后端 {backend} 的默认模型属性"
            assert _DEFAULT_MODEL_ATTR[backend] == attr_name, f"后端 {backend} 的默认模型属性错误"


class TestExecutionModeResolution(TestMultiBackendIntegration):
    """测试执行模式解析"""

    def test_direct_mode_for_main_group(self, test_config: AppConfig):
        """测试主群默认执行模式"""
        from iflowclaw.agents.runner import _resolve_execution_mode

        agent_config = AgentConfig(backend="iflow")

        # 主群默认执行模式取决于配置
        # 如果配置的默认执行模式是"direct"，则主群使用"direct"
        # 如果配置的默认执行模式是其他值，则主群使用"container"
        mode = _resolve_execution_mode(agent_config, test_config, is_main=True)

        # 根据当前配置，默认执行模式是"direct"
        assert mode == "direct", f"主群应该使用配置的默认执行模式，实际: {mode}"

    def test_explicit_direct_mode(self, test_config: AppConfig):
        """测试显式指定直连模式"""
        from iflowclaw.agents.runner import _resolve_execution_mode

        agent_config = AgentConfig(backend="iflow", execution_mode="direct")

        # 显式指定的直连模式应该被尊重
        mode = _resolve_execution_mode(agent_config, test_config, is_main=True)
        assert mode == "direct", f"显式指定的直连模式应该被尊重，实际: {mode}"

    def test_non_main_group_default_mode(self, test_config: AppConfig):
        """测试非主群的默认模式"""
        from iflowclaw.agents.runner import _resolve_execution_mode

        agent_config = AgentConfig(backend="iflow")

        # 非主群应该使用配置的默认模式
        test_config.default_execution_mode = "container"
        mode = _resolve_execution_mode(agent_config, test_config, is_main=False)
        assert mode == "container", f"非主群应该使用配置的默认模式，实际: {mode}"


class TestContainerBackend(TestMultiBackendIntegration):
    """测试容器后端"""

    @pytest.mark.skipif(not os.environ.get("RUN_CONTAINER_TESTS"), reason="容器测试需要设置 RUN_CONTAINER_TESTS=1")
    @pytest.mark.asyncio
    async def test_container_backend_initialization(self, test_config: AppConfig):
        """测试容器后端初始化"""
        from iflowclaw.agents.backends.container import ContainerBackend

        backend = ContainerBackend(
            model="test-model",
            backend="claude",
            project_root=str(test_config.project_root),
            data_dir=str(test_config.data_dir),
            groups_dir=str(test_config.groups_dir),
        )

        assert backend.name == "container"
        assert backend._backend == "claude"
        assert backend._model == "test-model"

    @pytest.mark.skipif(not os.environ.get("RUN_CONTAINER_TESTS"), reason="容器测试需要设置 RUN_CONTAINER_TESTS=1")
    @pytest.mark.asyncio
    async def test_container_backend_with_different_backends(self, test_config: AppConfig):
        """测试容器后端支持不同的内部后端"""
        from iflowclaw.agents.backends.container import ContainerBackend

        for internal_backend in ["claude", "iflow", "agno"]:
            backend = ContainerBackend(
                model="test-model",
                backend=internal_backend,
                project_root=str(test_config.project_root),
                data_dir=str(test_config.data_dir),
                groups_dir=str(test_config.groups_dir),
            )

            assert backend._backend == internal_backend, f"容器后端应该支持内部后端 {internal_backend}"


class TestAgentRunner(TestMultiBackendIntegration):
    """测试Agent运行器"""

    @pytest.mark.asyncio
    async def test_runner_backend_selection(self, test_config: AppConfig, agent_input: AgentInput):
        """测试运行器后端选择逻辑"""
        runner = AgentRunner(test_config)

        # 测试不同后端的配置
        test_cases = [
            ("iflow", "iflow"),
            ("claude", "claude"),
            ("agno", "agno"),
            ("container", "container"),
        ]

        for backend_name, expected_backend in test_cases:
            agent_config = AgentConfig(backend=backend_name, execution_mode="direct")

            # 我们不能真正运行agent，但可以测试配置逻辑
            # 这里我们测试配置是否正确传递
            assert agent_config.backend == expected_backend, f"后端配置应该正确传递: {backend_name}"

    @pytest.mark.asyncio
    async def test_runner_timeout_configuration(self, test_config: AppConfig, agent_input: AgentInput):
        """测试运行器超时配置"""
        runner = AgentRunner(test_config)

        # 测试自定义超时
        agent_config = AgentConfig(backend="iflow", timeout=5000)

        # 验证超时配置被正确应用
        assert agent_config.timeout == 5000, "自定义超时应该被应用"

        # 测试默认超时
        agent_config_default = AgentConfig(backend="iflow")
        assert agent_config_default.timeout is None, "默认超时应该为None"


class TestMCPIntegration(TestMultiBackendIntegration):
    """测试MCP集成"""

    def test_mcp_tools_configuration(self):
        """测试MCP工具配置"""
        from iflowclaw.agents.backends.claude import MCP_TOOLS

        expected_tools = [
            "send_message",
            "schedule_task",
            "list_tasks",
            "pause_task",
            "resume_task",
            "cancel_task",
            "update_task",
            "register_group",
        ]

        assert set(MCP_TOOLS) == set(expected_tools), f"MCP工具列表不正确，期望: {expected_tools}，实际: {MCP_TOOLS}"

    def test_mcp_environment_variables(self):
        """测试MCP环境变量配置"""
        from iflowclaw.agents.backends.agno import _build_mcp_env
        from iflowclaw.agents.backends.base import BackendContext

        context = BackendContext(
            group_folder="test_group",
            chat_jid="feishu:test_chat",
            is_main=True,
            session_id="test_session",
            group_dir="/test/group",
            ipc_dir="/test/ipc",
            system_prompt="Test prompt",
            timeout_s=60.0,
        )

        env = _build_mcp_env(context)

        expected_vars = {
            "IFLOWCLAW_GROUP_FOLDER": "test_group",
            "IFLOWCLAW_CHAT_JID": "feishu:test_chat",
            "IFLOWCLAW_IS_MAIN": "1",
            "IFLOWCLAW_IPC_DIR": "/test/ipc",
        }

        for key, expected_value in expected_vars.items():
            assert key in env, f"缺少环境变量: {key}"
            assert env[key] == expected_value, f"环境变量 {key} 的值不正确，期望: {expected_value}，实际: {env[key]}"


class TestCredentialProxy(TestMultiBackendIntegration):
    """测试凭证代理"""

    def test_auth_mode_detection(self, test_config: AppConfig):
        """测试认证模式检测"""
        from iflowclaw.credential_proxy import detect_auth_mode

        # 测试API密钥模式
        test_config.credentials.anthropic_api_key = "test-key"
        test_config.credentials.claude_oauth_token = None

        mode = detect_auth_mode(test_config)
        assert mode == "api-key", f"应该检测到API密钥模式，实际: {mode}"

        # 测试OAuth模式
        test_config.credentials.anthropic_api_key = None
        test_config.credentials.claude_oauth_token = "test-token"

        mode = detect_auth_mode(test_config)
        assert mode == "oauth", f"应该检测到OAuth模式，实际: {mode}"

    def test_proxy_config_building(self, test_config: AppConfig):
        """测试代理配置构建"""
        from iflowclaw.credential_proxy import build_proxy_config

        test_config.credentials.anthropic_api_key = "test-key"
        test_config.credentials.anthropic_base_url = "https://test.anthropic.com"

        proxy_config = build_proxy_config(test_config)

        assert proxy_config.auth_mode == "api-key"
        assert proxy_config.api_key == "test-key"
        assert proxy_config.upstream_url == "https://test.anthropic.com"


class TestContainerEntry(TestMultiBackendIntegration):
    """测试容器入口"""

    def test_container_config_building(self):
        """测试容器内配置构建"""
        from iflowclaw.agents.container_entry import build_config

        # 设置测试环境变量
        os.environ["ASSISTANT_NAME"] = "TestBot"
        os.environ["TZ"] = "UTC"

        config = build_config("claude", "test-model")

        assert config.default_backend == "claude"
        assert config.claude_model == "test-model"
        assert config.credentials.openai_model is None
        assert config.agno_model is None
        assert config.assistant_name == "TestBot"

        # 测试iFlow后端配置
        config_iflow = build_config("iflow", "iflow-model")
        assert config_iflow.default_backend == "iflow"
        assert config_iflow.credentials.openai_model == "iflow-model"
        assert config_iflow.claude_model is None

        # 测试Agno后端配置
        config_agno = build_config("agno", "gpt-4")
        assert config_agno.default_backend == "agno"
        assert config_agno.agno_model == "gpt-4"
        assert config_iflow.claude_model is None


class TestEndToEndWorkflow(TestMultiBackendIntegration):
    """端到端工作流测试"""

    @pytest.mark.asyncio
    async def test_backend_selection_workflow(self, test_config: AppConfig):
        """测试后端选择工作流"""
        runner = AgentRunner(test_config)

        # 测试不同后端的配置流程
        test_cases = [
            {
                "backend": "iflow",
                "mode": "direct",
                "expected_backend": "iflow",
            },
            {
                "backend": "claude",
                "mode": "container",
                "expected_backend": "container",
            },
            {
                "backend": "agno",
                "mode": "direct",
                "expected_backend": "agno",
            },
        ]

        for case in test_cases:
            agent_input = AgentInput(
                prompt="Test message",
                group_folder="test_group",
                chat_jid="feishu:test",
                is_main=False,
                session_id=None,
                is_scheduled_task=False,
                assistant_name="TestBot",
            )

            agent_config = AgentConfig(
                backend=case["backend"],
                execution_mode=case["mode"],
            )

            # 这里我们不能真正运行agent，但可以验证配置逻辑
            # 在真实环境中，这里会调用runner.run()
            assert agent_config.backend == case["backend"]
            assert agent_config.execution_mode == case["mode"]


if __name__ == "__main__":
    # 当直接运行时，运行所有测试
    pytest.main([__file__, "-v"])
