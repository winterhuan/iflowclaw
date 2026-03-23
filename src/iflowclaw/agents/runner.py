from __future__ import annotations

import os

from ..config import AppConfig
from ..group_folder import resolve_group_folder_path, resolve_group_ipc_path
from ..types import AgentConfig, AgentInput
from .backends import (
    AgnoBackend,
    BackendContext,
    BackendResult,
    ClaudeBackend,
    ContainerBackend,
    IFlowBackend,
)
from .prompting import build_system_prompt

_BACKEND_MAP = {
    "iflow": IFlowBackend,
    "claude": ClaudeBackend,
    "agno": AgnoBackend,
    "container": ContainerBackend,
}

_DEFAULT_MODEL_ATTR = {
    "iflow": "iflow_model",
    "claude": "claude_model",
    "agno": "agno_model",
    "container": "claude_model",
}


def _resolve_execution_mode(
    agent_config: AgentConfig,
    config: AppConfig,
    is_main: bool,
) -> str:
    """解析执行模式

    优先级：
    1. agent_config.execution_mode - 显式配置
    2. is_main=True: 默认使用容器模式（除非明确指定direct）
    3. is_main=False: 使用配置的default_execution_mode

    注意：容器模式要求 Docker/Podman 可用，否则会回退到直连模式
    """
    if agent_config.execution_mode:
        return agent_config.execution_mode

    # 主群默认使用容器模式（除非明确配置为direct）
    if is_main:
        # 如果默认执行模式是direct，则使用direct，否则使用container
        if config.default_execution_mode == "direct":
            return "direct"
        return "container"

    # 非主群使用配置的模式，但如果配置为direct则使用container
    if config.default_execution_mode == "direct":
        return "container"
    return config.default_execution_mode


class AgentRunner:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    async def run(
        self,
        *,
        agent_input: AgentInput,
        agent_config: AgentConfig,
        user_prompt: str,
    ) -> BackendResult:
        system_prompt = build_system_prompt(
            self._config,
            group_folder=agent_input.group_folder,
            is_main=agent_input.is_main,
        )
        if agent_config.system_prompt:
            system_prompt = (system_prompt + "\n" if system_prompt else "") + agent_config.system_prompt

        execution_mode = _resolve_execution_mode(agent_config, self._config, agent_input.is_main)

        # 决定后端名称
        if execution_mode == "container":
            backend_name = "container"
        else:
            backend_name = agent_config.backend or self._config.default_backend

        timeout_ms = agent_config.timeout or self._config.agent_timeout_ms

        # 容器内直接使用环境变量指定的路径
        container_group_dir = os.environ.get("IFLOWCLAW_GROUP_DIR")
        container_ipc_dir = os.environ.get("IFLOWCLAW_IPC_DIR")

        if container_group_dir:
            group_dir = container_group_dir
        else:
            group_dir = str(resolve_group_folder_path(self._config, agent_input.group_folder))

        if container_ipc_dir:
            ipc_dir = container_ipc_dir
        else:
            ipc_dir = str(resolve_group_ipc_path(self._config, agent_input.group_folder))

        context = BackendContext(
            group_folder=agent_input.group_folder,
            chat_jid=agent_input.chat_jid,
            is_main=agent_input.is_main,
            session_id=agent_input.session_id,
            group_dir=group_dir,
            ipc_dir=ipc_dir,
            system_prompt=system_prompt,
            timeout_s=timeout_ms / 1000.0,
        )

        backend_cls = _BACKEND_MAP.get(backend_name, IFlowBackend)
        default_model_attr = _DEFAULT_MODEL_ATTR.get(backend_name, "iflow_model")
        model = agent_config.model or getattr(self._config, default_model_attr)

        if backend_name == "container":
            # 容器内使用的后端（可以是claude, iflow, agno）
            container_backend = agent_config.backend or self._config.default_backend
            if container_backend == "container":
                # 如果默认后端也是container，回退到claude
                container_backend = "claude"

            backend = backend_cls(
                model=model,
                backend=container_backend,
                project_root=str(self._config.project_root),
                data_dir=str(self._config.data_dir),
                groups_dir=str(self._config.groups_dir),
                container_timeout_ms=timeout_ms,
                idle_timeout_ms=self._config.idle_timeout_ms,
                credential_proxy_port=self._config.credential_proxy_port,
            )
        else:
            backend = backend_cls(model=model)

        return await backend.run(
            user_prompt=user_prompt,
            context=context,
        )
