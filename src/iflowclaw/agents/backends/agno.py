from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import (
    BackendConfigError,
    BackendContext,
    BackendError,
    BackendExecutionError,
    BackendNotInstalledError,
    BackendResult,
    StreamCallback,
)

logger = logging.getLogger(__name__)


def _resolve_model(model_string: str | None) -> Any:
    if not model_string:
        return None

    normalized_model = model_string.strip()
    if ":" in normalized_model:
        provider, model_id = normalized_model.split(":", 1)
        provider = provider.strip().lower()
        model_id = model_id.strip()
    else:
        provider, model_id = "openai", normalized_model

    if provider != "openai":
        raise BackendConfigError("Agno backend only supports OpenAI models. Use `gpt-4o` or `openai:gpt-4o`.")
    if not model_id:
        raise BackendConfigError("Agno backend model cannot be empty")

    try:
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=model_id)
    except BackendConfigError:
        raise
    except Exception as e:
        raise BackendConfigError(f"Failed to resolve model '{model_string}': {e}") from e


def _build_mcp_env(context: BackendContext) -> dict[str, str]:
    """构建 MCP 服务器环境变量"""
    return {
        "IFLOWCLAW_GROUP_FOLDER": context.group_folder,
        "IFLOWCLAW_CHAT_JID": context.chat_jid,
        "IFLOWCLAW_IS_MAIN": "1" if context.is_main else "0",
        "IFLOWCLAW_IPC_DIR": context.ipc_dir,
    }


class AgnoBackend:
    name = "agno"

    def __init__(self, *, model: str | None = None) -> None:
        self._model = model

    async def run(
        self,
        *,
        user_prompt: str,
        context: BackendContext,
        on_stream: StreamCallback | None = None,
    ) -> BackendResult:
        try:
            from agno.agent import Agent, RunOutput
            from agno.tools.mcp import MCPTools
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as e:
            raise BackendNotInstalledError("agno", "agno") from e

        model_obj = _resolve_model(self._model)
        if model_obj is None:
            raise BackendConfigError("No model configured for agno backend")

        mcp_env = _build_mcp_env(context)
        server_params = StdioServerParameters(
            command="python3",
            args=["-m", "iflowclaw.mcps.ipc_mcp_stdio"],
            env=mcp_env,
        )

        # 加载 skills
        skills_obj = None
        skills_dir = Path(context.group_dir) / "skills"
        if skills_dir.is_dir():
            try:
                from agno.skills import LocalSkills, Skills

                skills_obj = Skills(loaders=[LocalSkills(str(skills_dir))])
            except Exception as e:
                logger.debug("agno: failed to load skills: %s", e)

        text_parts: list[str] = []
        new_session_id: str | None = context.session_id

        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    mcp_tools = MCPTools(session=session)
                    await mcp_tools.initialize()

                    agent_kwargs: dict[str, Any] = dict(
                        model=model_obj,
                        system_message=context.system_prompt,
                        session_id=context.session_id,
                        tools=[mcp_tools],
                        markdown=True,
                    )
                    if skills_obj is not None:
                        agent_kwargs["skills"] = skills_obj

                    agent = Agent(**agent_kwargs)

                    if on_stream:
                        async for event in agent.arun(user_prompt, stream=True):
                            text_parts.append(event.content or "")
                            if event.content:
                                await on_stream(event.content)
                        text = "".join(text_parts)
                    else:
                        result: RunOutput = await agent.arun(user_prompt)
                        text = result.content or ""
                        text_parts.append(text)

                    try:
                        new_session_id = agent.session_id or context.session_id
                    except Exception:
                        pass
        except BackendError:
            raise
        except Exception as e:
            logger.exception("agno backend failed: %s", e)
            raise BackendExecutionError(str(e), partial_output="".join(text_parts)) from e

        return BackendResult(
            status="success",
            text=text,
            new_session_id=new_session_id,
        )
