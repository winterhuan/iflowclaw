from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol

from ...types import AgentConfig, AgentInput, AgentOutput

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[str]]


class AgentBackend(Protocol):
    name: str

    async def run(
        self,
        *,
        agent_input: AgentInput,
        agent_config: AgentConfig,
        system_prompt: str | None,
        user_prompt: str,
        tool_executor: ToolExecutor,
    ) -> AgentOutput: ...
