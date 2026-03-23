from __future__ import annotations

import logging
from typing import Any

from .base import BackendContext, BackendResult, StreamCallback

logger = logging.getLogger(__name__)


class IFlowBackend:
    name = "iflow"

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
            from iflow_sdk import AssistantMessage, IFlowClient, IFlowOptions, TaskFinishMessage
            from iflow_sdk.types import ApprovalMode, EnvVariable, McpServer
        except Exception as e:
            return BackendResult(status="error", text="", error=f"iflow-cli-sdk not installed: {e}")

        mcp_server = McpServer(
            name="iflowclaw",
            command="python3",
            args=["-m", "iflowclaw.mcps.ipc_mcp_stdio"],
            env=[
                EnvVariable(name="IFLOWCLAW_GROUP_FOLDER", value=context.group_folder),
                EnvVariable(name="IFLOWCLAW_CHAT_JID", value=context.chat_jid),
                EnvVariable(name="IFLOWCLAW_IS_MAIN", value="1" if context.is_main else "0"),
                EnvVariable(name="IFLOWCLAW_IPC_DIR", value=context.ipc_dir),
            ],
        )

        session_settings: dict[str, Any] = {}
        if context.system_prompt:
            session_settings["system_prompt"] = context.system_prompt

        options = IFlowOptions(
            auto_start_process=True,
            cwd=context.group_dir,
            timeout=context.timeout_s,
            approval_mode=ApprovalMode.YOLO,
            mcp_servers=[mcp_server],
            session_id=context.session_id,
            session_settings=session_settings,
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
                            if on_stream:
                                await on_stream(str(chunk))
                        agent_info = getattr(msg, "agent_info", None)
                        if agent_info is not None:
                            agent_id = getattr(agent_info, "agent_id", None)
                            if isinstance(agent_id, str):
                                new_session_id = new_session_id or context.session_id
                    elif isinstance(msg, TaskFinishMessage):
                        break
                sid = getattr(client, "session_id", None)
                if isinstance(sid, str) and sid:
                    new_session_id = sid
        except Exception as e:
            logger.exception("iflow backend failed: %s", e)
            return BackendResult(
                status="error",
                text="".join(text_parts),
                error=str(e),
                new_session_id=new_session_id,
            )

        return BackendResult(
            status="success",
            text="".join(text_parts),
            new_session_id=new_session_id,
        )
