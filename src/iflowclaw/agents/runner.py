from __future__ import annotations

import os
from pathlib import Path

from ..config import AppConfig
from ..group_folder import resolve_group_folder_path, resolve_group_ipc_path
from ..skills import sync_skills_for_backend
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
    "iflow": "openai_model",
    "claude": "claude_model",
    "agno": "openai_model",
    "container": "claude_model",
}


def _resolve_execution_mode(
    agent_config: AgentConfig,
    config: AppConfig,
    is_main: bool,
) -> str:
    if agent_config.execution_mode:
        return agent_config.execution_mode
    if is_main:
        if config.default_execution_mode == "direct":
            return "direct"
        return "container"
    if config.default_execution_mode == "direct":
        return "container"
    return config.default_execution_mode


def _uses_container_execution(
    agent_config: AgentConfig,
    config: AppConfig,
    is_main: bool,
) -> bool:
    return _resolve_execution_mode(agent_config, config, is_main) == "container"


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

        use_container = _uses_container_execution(agent_config, self._config, agent_input.is_main)
        backend_name = "container" if use_container else (agent_config.backend or self._config.default_backend)
        timeout_ms = agent_config.timeout or self._config.agent_timeout_ms

        container_group_dir = os.environ.get("IFLOWCLAW_GROUP_DIR")
        container_ipc_dir = os.environ.get("IFLOWCLAW_IPC_DIR")
        group_dir = container_group_dir or str(resolve_group_folder_path(self._config, agent_input.group_folder))
        ipc_dir = container_ipc_dir or str(resolve_group_ipc_path(self._config, agent_input.group_folder))

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
        container_backend = agent_config.backend or self._config.default_backend
        if container_backend == "container":
            container_backend = "claude"

        if use_container:
            default_model_attr = _DEFAULT_MODEL_ATTR.get(container_backend, "claude_model")
        else:
            default_model_attr = _DEFAULT_MODEL_ATTR.get(backend_name, "openai_model")
        model = agent_config.model or getattr(self._config, default_model_attr, None) or getattr(self._config.credentials, default_model_attr, None)

        if backend_name == "container":
            backend = backend_cls(
                model=model,
                backend=container_backend,
                project_root=str(self._config.project_root),
                data_dir=str(self._config.data_dir),
                groups_dir=str(self._config.groups_dir),
                container_timeout_ms=timeout_ms,
                idle_timeout_ms=self._config.idle_timeout_ms,
                credential_proxy_port=self._config.credential_proxy_port,
                container_image=self._config.container_image,
                assistant_name=self._config.assistant_name,
                timezone=self._config.timezone,
                credentials=self._config.credentials,
            )
        else:
            if not os.environ.get("IFLOWCLAW_GROUP_DIR"):
                target_dir = Path(group_dir)
                global_dir_path = str((self._config.groups_dir / "global").resolve())
                project_dir_path = str(self._config.project_root.resolve())
                sync_skills_for_backend(
                    backend_name,
                    self._config.project_root,
                    target_dir,
                    group_dir=group_dir,
                    global_dir=global_dir_path,
                    ipc_dir=ipc_dir,
                    project_dir=project_dir_path,
                )
            if backend_name == "iflow":
                backend = backend_cls(
                    model=model,
                    api_key=self._config.credentials.openai_api_key,
                    base_url=self._config.credentials.openai_base_url,
                )
            else:
                backend = backend_cls(model=model)

        return await backend.run(
            user_prompt=user_prompt,
            context=context,
        )
