"""Agent execution runner with multi-backend support.

This module provides the AgentRunner class that routes execution to
different backends (iFlow, Claude, Agno, Container) based on configuration.
"""

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

_BACKEND_MAP: dict[str, type] = {
    "iflow": IFlowBackend,
    "claude": ClaudeBackend,
    "agno": AgnoBackend,
    "container": ContainerBackend,
}

_DEFAULT_MODEL_ATTR: dict[str, str] = {
    "iflow": "openai_model",
    "claude": "claude_model",
    "agno": "agno_model",
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
        return "direct" if config.default_execution_mode == "direct" else "container"
    return "container" if config.default_execution_mode == "direct" else config.default_execution_mode


class AgentRunner:
    """Agent execution runner supporting multiple backends.

    Routes execution to iFlow, Claude, Agno, or Container backends
    based on group and agent configuration.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def _resolve_backend_name(self, agent_config: AgentConfig, is_main: bool) -> tuple[str, bool]:
        """Determine backend name and whether container execution is used."""
        use_container = _resolve_execution_mode(agent_config, self._config, is_main) == "container"
        if use_container:
            return "container", True
        return agent_config.backend or self._config.default_backend, False

    def _resolve_model(self, agent_config: AgentConfig, backend_name: str, use_container: bool) -> str | None:
        """Resolve the model name for the given backend."""
        if agent_config.model:
            return agent_config.model

        if use_container:
            container_backend = agent_config.backend or self._config.default_backend
            if container_backend == "container":
                container_backend = "claude"
            attr = _DEFAULT_MODEL_ATTR.get(container_backend, "claude_model")
        else:
            attr = _DEFAULT_MODEL_ATTR.get(backend_name, "openai_model")

        return getattr(self._config, attr, None) or getattr(self._config.credentials, attr, None)

    def _resolve_directories(self, group_folder: str) -> tuple[str, str]:
        """Resolve group and IPC directories, respecting container overrides."""
        container_group_dir = os.environ.get("IFLOWCLAW_GROUP_DIR")
        container_ipc_dir = os.environ.get("IFLOWCLAW_IPC_DIR")
        group_dir = container_group_dir or str(resolve_group_folder_path(self._config, group_folder))
        ipc_dir = container_ipc_dir or str(resolve_group_ipc_path(self._config, group_folder))
        return group_dir, ipc_dir

    def _build_context(
        self,
        agent_input: AgentInput,
        system_prompt: str,
        timeout_ms: int,
        group_dir: str,
        ipc_dir: str,
    ) -> BackendContext:
        return BackendContext(
            group_folder=agent_input.group_folder,
            chat_jid=agent_input.chat_jid,
            is_main=agent_input.is_main,
            session_id=agent_input.session_id,
            group_dir=group_dir,
            ipc_dir=ipc_dir,
            system_prompt=system_prompt,
            timeout_s=timeout_ms / 1000.0,
        )

    def _create_backend(
        self,
        backend_name: str,
        model: str | None,
        group_dir: str,
        ipc_dir: str,
        agent_config: AgentConfig,
        use_container: bool,
    ) -> object:
        backend_cls = _BACKEND_MAP.get(backend_name, IFlowBackend)

        if backend_name == "container":
            container_backend = agent_config.backend or self._config.default_backend
            if container_backend == "container":
                container_backend = "claude"
            return backend_cls(
                model=model,
                backend=container_backend,
                project_root=str(self._config.project_root),
                data_dir=str(self._config.data_dir),
                groups_dir=str(self._config.groups_dir),
                container_timeout_ms=agent_config.timeout or self._config.agent_timeout_ms,
                idle_timeout_ms=self._config.idle_timeout_ms,
                credential_proxy_port=self._config.credential_proxy_port,
                container_image=self._config.container_image,
                assistant_name=self._config.assistant_name,
                timezone=self._config.timezone,
                credentials=self._config.credentials,
            )

        if not os.environ.get("IFLOWCLAW_GROUP_DIR"):
            self._sync_skills(backend_name, group_dir, ipc_dir)

        if backend_name == "iflow":
            return backend_cls(
                model=model,
                api_key=self._config.credentials.openai_api_key,
                base_url=self._config.credentials.openai_base_url,
            )
        return backend_cls(model=model)

    def _sync_skills(self, backend_name: str, group_dir: str, ipc_dir: str) -> None:
        target_dir = Path(group_dir)
        global_dir = str((self._config.groups_dir / "global").resolve())
        project_dir = str(self._config.project_root.resolve())
        sync_skills_for_backend(
            backend_name,
            self._config.project_root,
            target_dir,
            group_dir=group_dir,
            global_dir=global_dir,
            ipc_dir=ipc_dir,
            project_dir=project_dir,
        )

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

        backend_name, use_container = self._resolve_backend_name(agent_config, agent_input.is_main)
        timeout_ms = agent_config.timeout or self._config.agent_timeout_ms
        group_dir, ipc_dir = self._resolve_directories(agent_input.group_folder)
        context = self._build_context(agent_input, system_prompt, timeout_ms, group_dir, ipc_dir)
        model = self._resolve_model(agent_config, backend_name, use_container)
        backend = self._create_backend(backend_name, model, group_dir, ipc_dir, agent_config, use_container)

        return await backend.run(user_prompt=user_prompt, context=context)
