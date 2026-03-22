from __future__ import annotations

from typing import Any

from ...config import AppConfig
from ...group_folder import resolve_group_folder_path
from ...logging import get_logger
from ...types import AgentConfig, AgentInput, AgentOutput
from .base import ToolExecutor

logger = get_logger(__name__)


class ClaudeBackend:
    name = "claude"

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    async def run(
        self,
        *,
        agent_input: AgentInput,
        agent_config: AgentConfig,
        system_prompt: str | None,
        user_prompt: str,
        tool_executor: ToolExecutor,
    ) -> AgentOutput:
        try:
            from claude_agent_sdk import (
                AssistantMessage,
                ClaudeAgentOptions,
                PermissionResultAllow,
                PermissionResultDeny,
                ResultMessage,
                TextBlock,
                ToolPermissionContext,
                create_sdk_mcp_server,
                query,
                tool,
            )
        except Exception as e:
            return AgentOutput(status="error", result=None, error=f"claude-agent-sdk not installed: {e}")

        group_dir = resolve_group_folder_path(self._config, agent_input.group_folder)

        async def _call_tool(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
            result_text = await tool_executor(tool_name, args)
            return {"content": [{"type": "text", "text": result_text}]}

        @tool(
            "send_message",
            "Send a message to the user or group immediately while you're still running.",
            {"text": str, "sender": str | None},
        )
        async def send_message_tool(args: dict[str, Any]) -> dict[str, Any]:
            return await _call_tool("send_message", args)

        @tool(
            "schedule_task",
            "Schedule a recurring or one-time task.",
            {
                "prompt": str,
                "schedule_type": str,
                "schedule_value": str,
                "context_mode": str | None,
                "target_group_jid": str | None,
            },
        )
        async def schedule_task_tool(args: dict[str, Any]) -> dict[str, Any]:
            return await _call_tool("schedule_task", args)

        @tool(
            "list_tasks",
            "List scheduled tasks.",
            {},
        )
        async def list_tasks_tool(args: dict[str, Any]) -> dict[str, Any]:
            _ = args
            return await _call_tool("list_tasks", {})

        @tool("pause_task", "Pause a scheduled task.", {"task_id": str})
        async def pause_task_tool(args: dict[str, Any]) -> dict[str, Any]:
            return await _call_tool("pause_task", args)

        @tool("resume_task", "Resume a paused task.", {"task_id": str})
        async def resume_task_tool(args: dict[str, Any]) -> dict[str, Any]:
            return await _call_tool("resume_task", args)

        @tool("cancel_task", "Cancel a scheduled task.", {"task_id": str})
        async def cancel_task_tool(args: dict[str, Any]) -> dict[str, Any]:
            return await _call_tool("cancel_task", args)

        @tool(
            "update_task",
            "Update an existing scheduled task.",
            {"task_id": str, "prompt": str | None, "schedule_type": str | None, "schedule_value": str | None},
        )
        async def update_task_tool(args: dict[str, Any]) -> dict[str, Any]:
            return await _call_tool("update_task", args)

        @tool(
            "register_group",
            "Register a new chat/group (main group only).",
            {"jid": str, "name": str, "folder": str, "trigger": str},
        )
        async def register_group_tool(args: dict[str, Any]) -> dict[str, Any]:
            return await _call_tool("register_group", args)

        server = create_sdk_mcp_server(
            name="iflowclaw",
            version="1.0.0",
            tools=[
                send_message_tool,
                schedule_task_tool,
                list_tasks_tool,
                pause_task_tool,
                resume_task_tool,
                cancel_task_tool,
                update_task_tool,
                register_group_tool,
            ],
        )

        allowed = [
            "mcp__iflowclaw__send_message",
            "mcp__iflowclaw__schedule_task",
            "mcp__iflowclaw__list_tasks",
            "mcp__iflowclaw__pause_task",
            "mcp__iflowclaw__resume_task",
            "mcp__iflowclaw__cancel_task",
            "mcp__iflowclaw__update_task",
            "mcp__iflowclaw__register_group",
        ]

        async def can_use_tool(tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext) -> Any:
            _ = tool_input
            _ = context
            if tool_name in allowed:
                return PermissionResultAllow()
            return PermissionResultDeny(message=f"Tool not allowed: {tool_name}", interrupt=True)

        model = agent_config.model or self._config.claude_model or "sonnet"

        options = ClaudeAgentOptions(
            cwd=str(group_dir),
            system_prompt=system_prompt or "",
            model=model,
            mcp_servers={"iflowclaw": server},
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
                if isinstance(message, ResultMessage):
                    break
        except Exception as e:
            logger.exception("claude agent sdk failed: %s", e)
            return AgentOutput(status="error", result=None, error=str(e))

        return AgentOutput(status="success", result="".join(text_parts).strip())
