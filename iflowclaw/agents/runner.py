from __future__ import annotations

from dataclasses import replace

from ..config import AppConfig
from ..tools import execute_local_tool
from ..types import AgentConfig, AgentInput, AgentOutput
from .backends import ClaudeBackend, IFlowBackend
from .prompting import build_system_prompt


class AgentRunner:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._iflow = IFlowBackend(config)
        self._claude = ClaudeBackend(config)

    async def run(
        self,
        *,
        agent_input: AgentInput,
        agent_config: AgentConfig,
        user_prompt: str,
    ) -> AgentOutput:
        system_prompt = build_system_prompt(self._config, group_folder=agent_input.group_folder, is_main=agent_input.is_main)
        if agent_config.system_prompt:
            system_prompt = (system_prompt + "\n" if system_prompt else "") + agent_config.system_prompt

        backend_name = agent_config.backend or self._config.default_backend

        if backend_name == "claude":
            model = agent_config.model or self._config.claude_model
            agent_config = replace(agent_config, model=model)
            backend = self._claude
        else:
            model = agent_config.model or self._config.iflow_model
            agent_config = replace(agent_config, model=model)
            backend = self._iflow

        async def tool_executor(name: str, args: dict) -> str:
            return execute_local_tool(
                config=self._config,
                group_folder=agent_input.group_folder,
                chat_jid=agent_input.chat_jid,
                is_main=agent_input.is_main,
                tool_name=name,
                tool_input=args,
            )

        return await backend.run(
            agent_input=agent_input,
            agent_config=agent_config,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tool_executor=tool_executor,
        )
