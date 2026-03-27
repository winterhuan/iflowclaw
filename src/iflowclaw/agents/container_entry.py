"""
iFlowClaw Container Runner
Runs inside a container, receives config via stdin, outputs result to stdout.

Supports multiple backends: claude, iflow, agno
Reuses AgentRunner for consistency with direct mode.

Input protocol:
  Stdin: ContainerInput JSON (read until EOF)
  IPC:   Follow-up messages in /workspace/ipc/input/
         Sentinel: /workspace/ipc/input/_close — signals session end

Stdout protocol:
  OUTPUT_START/END marker pairs.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

from iflowclaw.agents.runner import AgentRunner
from iflowclaw.config import AppConfig, BackendCredentials
from iflowclaw.types import AgentConfig, AgentInput

IPC_INPUT_DIR = Path("/workspace/ipc/input")
IPC_INPUT_CLOSE_SENTINEL = IPC_INPUT_DIR / "_close"
IPC_POLL_INTERVAL = 0.5

OUTPUT_START_MARKER = "---IFLOWCLAW_OUTPUT_START---"
OUTPUT_END_MARKER = "---IFLOWCLAW_OUTPUT_END---"


def log(msg: str) -> None:
    print(f"[container-runner] {msg}", file=sys.stderr, flush=True)


def write_output(
    *, status: str, result: str | None = None, new_session_id: str | None = None, error: str | None = None
) -> None:
    print(OUTPUT_START_MARKER, flush=True)
    data: dict[str, Any] = {"status": status}
    if result is not None:
        data["result"] = result
    if new_session_id is not None:
        data["newSessionId"] = new_session_id
    if error is not None:
        data["error"] = error
    print(json.dumps(data), flush=True)
    print(OUTPUT_END_MARKER, flush=True)


def should_close() -> bool:
    if IPC_INPUT_CLOSE_SENTINEL.exists():
        try:
            IPC_INPUT_CLOSE_SENTINEL.unlink()
        except OSError:
            pass
        return True
    return False


def drain_ipc_input() -> list[str]:
    IPC_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    messages: list[str] = []
    try:
        files = sorted(IPC_INPUT_DIR.glob("*.json"))
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                f.unlink()
                if data.get("type") == "message" and data.get("text"):
                    messages.append(data["text"])
            except Exception as e:
                log(f"Failed to process input file {f.name}: {e}")
                try:
                    f.unlink()
                except OSError:
                    pass
    except Exception as e:
        log(f"IPC drain error: {e}")
    return messages


async def wait_for_ipc_message() -> str | None:
    while True:
        if should_close():
            return None
        messages = drain_ipc_input()
        if messages:
            return "\n".join(messages)
        await asyncio.sleep(IPC_POLL_INTERVAL)


def build_config(backend: str, model: str | None) -> AppConfig:
    """构建容器内的简化配置

    容器内路径：
    - /workspace/group - 群组目录（从宿主机挂载）
    - /workspace/global - 全局目录（只读挂载）
    - /workspace/ipc - IPC 目录
    """
    assistant_name = os.environ.get("ASSISTANT_NAME", "iFlow")
    escaped_name = re.escape(assistant_name)

    # 从环境变量读取凭证
    credentials = BackendCredentials(
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        anthropic_base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
        openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com"),
        openai_model=model if backend == "iflow" else None,
    )

    # 注意：容器内只有一个群组目录，被挂载到 /workspace/group
    # groups_dir 设为 /workspace，这样 resolve_group_folder_path("x") 返回 /workspace/x
    # 但实际我们只需要 /workspace/group
    return AppConfig(
        project_root=Path("/workspace/group"),
        store_dir=Path("/workspace/store"),
        groups_dir=Path("/workspace"),  # 挂载点的父目录
        data_dir=Path("/workspace"),
        logs_dir=Path("/workspace/logs"),
        sender_allowlist_path=Path("/workspace/config/sender-allowlist.json"),
        mount_allowlist_path=Path("/workspace/config/mount-allowlist.json"),
        assistant_name=assistant_name,
        feishu_app_id="",
        feishu_app_secret="",
        poll_interval_ms=2000,
        scheduler_poll_interval_ms=60000,
        ipc_poll_interval_ms=1000,
        agent_timeout_ms=300000,
        idle_timeout_ms=180000,
        max_concurrent_agents=1,
        container_timeout_ms=1800000,
        container_image="",
        credential_proxy_port=3001,
        timezone=os.environ.get("TZ", "Asia/Shanghai"),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        default_backend=backend,
        default_execution_mode="direct",
        claude_model=model if backend == "claude" else None,
        agno_model=model if backend == "agno" else None,
        trigger_pattern=re.compile(rf"^@{escaped_name}\b", re.IGNORECASE),
        credentials=credentials,
    )


async def main() -> None:
    try:
        stdin_data = sys.stdin.read()
        data = json.loads(stdin_data)

        group_folder = data["groupFolder"]
        chat_jid = data["chatJid"]
        is_main = data["isMain"]
        session_id = data.get("sessionId")
        is_scheduled_task = data.get("isScheduledTask", False)
        assistant_name = data.get("assistantName")
        backend = data.get("backend", "claude")
        model = data.get("model")
        system_prompt = data.get("systemPrompt")

        log(f"Received input for group: {group_folder}, backend: {backend}")
    except Exception as e:
        write_output(status="error", error=f"Failed to parse input: {e}")
        sys.exit(1)

    # 设置容器内 MCP 环境变量
    os.environ["IFLOWCLAW_GROUP_FOLDER"] = group_folder
    os.environ["IFLOWCLAW_CHAT_JID"] = chat_jid
    os.environ["IFLOWCLAW_IS_MAIN"] = "1" if is_main else "0"
    os.environ["IFLOWCLAW_IPC_DIR"] = "/workspace/ipc"
    os.environ["IFLOWCLAW_GROUP_DIR"] = "/workspace/group"  # 容器内群组目录

    IPC_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        IPC_INPUT_CLOSE_SENTINEL.unlink()
    except OSError:
        pass

    # 构建系统提示（添加 global AGENTS.md）
    if not is_main:
        global_md = Path("/workspace/global/AGENTS.md")
        if global_md.exists():
            extra = global_md.read_text(encoding="utf-8")
            system_prompt = (system_prompt + "\n" if system_prompt else "") + extra

    prompt = data["prompt"]
    if is_scheduled_task:
        prompt = f"[SCHEDULED TASK]\n\n{prompt}"

    pending = drain_ipc_input()
    if pending:
        log(f"Draining {len(pending)} pending IPC messages")
        prompt += "\n" + "\n".join(pending)

    config = build_config(backend, model)
    runner = AgentRunner(config)

    try:
        while True:
            log(f"Starting query (backend: {backend}, session: {session_id or 'new'})...")

            agent_input = AgentInput(
                prompt=prompt,
                group_folder=group_folder,
                chat_jid=chat_jid,
                is_main=is_main,
                session_id=session_id,
                is_scheduled_task=is_scheduled_task,
                assistant_name=assistant_name,
            )

            agent_config = AgentConfig(
                backend=backend,
                model=model,
                system_prompt=system_prompt,
                execution_mode="direct",  # 容器内使用直连模式
            )

            result = await runner.run(
                agent_input=agent_input,
                agent_config=agent_config,
                user_prompt=prompt,
            )

            if result.new_session_id:
                session_id = result.new_session_id

            if result.status == "error":
                write_output(status="error", result=None, new_session_id=session_id, error=result.error)
                sys.exit(1)

            if result.text:
                write_output(status="success", result=result.text, new_session_id=session_id)

            if should_close():
                log("Close sentinel consumed during query, exiting")
                break

            write_output(status="success", result=None, new_session_id=session_id)

            log("Query ended, waiting for next IPC message...")
            next_message = await wait_for_ipc_message()
            if next_message is None:
                log("Close sentinel received, exiting")
                break

            log(f"Got new message ({len(next_message)} chars)")
            prompt = next_message

    except Exception as e:
        log(f"Agent error: {e}\n{traceback.format_exc()}")
        write_output(status="error", error=str(e), new_session_id=session_id)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
