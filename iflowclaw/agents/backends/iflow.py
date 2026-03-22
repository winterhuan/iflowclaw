from __future__ import annotations

from pathlib import Path
from typing import Any

from ...config import AppConfig
from ...group_folder import resolve_group_folder_path, resolve_group_ipc_path
from ...logging import get_logger
from ...types import AgentConfig, AgentInput, AgentOutput
from .base import ToolExecutor

logger = get_logger(__name__)


class IFlowBackend:
    name = "iflow"

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
            from iflow_sdk import IFlowClient, IFlowOptions
            from iflow_sdk.types import ApprovalMode, EnvVariable, McpServer
            from iflow_sdk import AssistantMessage, TaskFinishMessage
        except Exception as e:
            return AgentOutput(status="error", result=None, error=f"iflow-cli-sdk not installed: {e}")

        group_dir = resolve_group_folder_path(self._config, agent_input.group_folder)
        ipc_dir = resolve_group_ipc_path(self._config, agent_input.group_folder)

        mcp_server = McpServer(
            name="iflowclaw",
            command="python3",
            args=["-m", "iflowclaw.mcps.ipc_mcp_stdio"],
            env=[
                EnvVariable(name="IFLOWCLAW_GROUP_FOLDER", value=agent_input.group_folder),
                EnvVariable(name="IFLOWCLAW_CHAT_JID", value=agent_input.chat_jid),
                EnvVariable(name="IFLOWCLAW_IS_MAIN", value="1" if agent_input.is_main else "0"),
                EnvVariable(name="IFLOWCLAW_IPC_DIR", value=str(ipc_dir)),
            ],
        )

        options = IFlowOptions(
            auto_start_process=True,
            cwd=str(group_dir),
            timeout=float((agent_config.timeout or self._config.agent_timeout_ms) / 1000),
            approval_mode=ApprovalMode.YOLO,
            mcp_servers=[mcp_server],
            session_id=agent_input.session_id,
            metadata=agent_config.metadata or {},
            session_settings={
                "system_prompt": system_prompt or "",
            },
        )

        text_parts: list[str] = []
        new_session_id: str | None = None

        try:
            async with IFlowClient(options) as client:
                await client.send_message(user_prompt)
                async for msg in client.receive_messages():
                    if isinstance(msg, AssistantMessage):
                        chunk = getattr(getattr(msg, "chunk", None), "text", None)
                        if chunk:
                            text_parts.append(str(chunk))
                        agent_info = getattr(msg, "agent_info", None)
                        if agent_info is not None:
                            agent_id = getattr(agent_info, "agent_id", None)
                            if isinstance(agent_id, str):
                                new_session_id = new_session_id or options.session_id
                    elif isinstance(msg, TaskFinishMessage):
                        break
                sid = getattr(client, "session_id", None)
                if isinstance(sid, str) and sid:
                    new_session_id = sid
        except Exception as e:
            logger.exception("iflow backend failed: %s", e)
            return AgentOutput(status="error", result=None, error=str(e), new_session_id=new_session_id)

        return AgentOutput(status="success", result="".join(text_parts), new_session_id=new_session_id)
