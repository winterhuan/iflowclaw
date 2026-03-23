from __future__ import annotations

import logging
from typing import Any

from .base import BackendContext, BackendResult, StreamCallback

logger = logging.getLogger(__name__)

# MCP 工具列表
MCP_TOOLS = [
    "send_message",
    "schedule_task",
    "list_tasks",
    "pause_task",
    "resume_task",
    "cancel_task",
    "update_task",
    "register_group",
]


def _build_mcp_server_config(context: BackendContext) -> dict[str, Any]:
    """构建 stdio MCP 服务器配置"""
    return {
        "command": "python3",
        "args": ["-m", "iflowclaw.mcps.ipc_mcp_stdio"],
        "env": {
            "IFLOWCLAW_GROUP_FOLDER": context.group_folder,
            "IFLOWCLAW_CHAT_JID": context.chat_jid,
            "IFLOWCLAW_IS_MAIN": "1" if context.is_main else "0",
            "IFLOWCLAW_IPC_DIR": context.ipc_dir,
        },
    }


def _build_allowed_tools() -> list[str]:
    """构建允许的工具列表"""
    return [f"mcp__iflowclaw__{tool}" for tool in MCP_TOOLS]


class ClaudeBackend:
    name = "claude"

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
            from claude_agent_sdk import (
                AssistantMessage,
                ClaudeAgentOptions,
                PermissionResultAllow,
                PermissionResultDeny,
                ResultMessage,
                TextBlock,
                ToolPermissionContext,
                query,
            )
        except Exception as e:
            return BackendResult(status="error", text="", error=f"claude-agent-sdk not installed: {e}")

        mcp_server_config = _build_mcp_server_config(context)
        allowed = _build_allowed_tools()

        async def can_use_tool(tool_name: str, tool_input: dict[str, Any], ctx: ToolPermissionContext) -> Any:
            if tool_name in allowed:
                return PermissionResultAllow()
            return PermissionResultDeny(message=f"Tool not allowed: {tool_name}", interrupt=True)

        model = self._model or "sonnet"

        options = ClaudeAgentOptions(
            cwd=context.group_dir,
            system_prompt=context.system_prompt or "",
            model=model,
            mcp_servers={"iflowclaw": mcp_server_config},
            allowed_tools=allowed,
            can_use_tool=can_use_tool,
        )

        text_parts: list[str] = []
        try:
            async for message in query(prompt=user_prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in getattr(message, "content", []) or []:
                        if isinstance(block, TextBlock):
                            text_parts.append(block.text)
                            if on_stream:
                                await on_stream(block.text)
                if isinstance(message, ResultMessage):
                    break
        except Exception as e:
            logger.exception("claude agent sdk failed: %s", e)
            return BackendResult(status="error", text="".join(text_parts), error=str(e))

        return BackendResult(status="success", text="".join(text_parts).strip())
