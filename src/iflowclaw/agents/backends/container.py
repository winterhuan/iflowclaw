"""Container Backend - 在 Docker 容器中运行 Agent

支持多后端（claude/iflow/agno），根据不同后端注入不同的凭证：
- claude: 通过 credential proxy 注入 Anthropic 凭证
- iflow: 挂载 ~/.iflow/settings.json
- agno: 注入 OPENAI_API_KEY 环境变量
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

from .base import BackendContext, BackendResult, StreamCallback

logger = logging.getLogger(__name__)

CONTAINER_HOST_GATEWAY = "host.docker.internal"
OUTPUT_START_MARKER = "---IFLOWCLAW_OUTPUT_START---"
OUTPUT_END_MARKER = "---IFLOWCLAW_OUTPUT_END---"

_detected_runtime: str | None = None


def _get_runtime() -> str:
    global _detected_runtime
    if _detected_runtime is None:
        for bin_name in ("docker", "podman"):
            try:
                result = subprocess.run(
                    [bin_name, "info", "--format", "{{.ServerVersion}}"],
                    capture_output=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    _detected_runtime = bin_name
                    break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        if _detected_runtime is None:
            raise RuntimeError("No container runtime (docker/podman) found")
    return _detected_runtime


def _host_gateway_args() -> list[str]:
    if platform.system() == "Linux":
        return [f"--add-host={CONTAINER_HOST_GATEWAY}:host-gateway"]
    return []


def _stop_container_cmd(name: str) -> list[str]:
    return [_get_runtime(), "stop", "-t", "1", name]


def _cleanup_orphans() -> None:
    try:
        result = subprocess.run(
            [_get_runtime(), "ps", "--filter", "name=iflowclaw-", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return
        orphans = [n.strip() for n in result.stdout.strip().splitlines() if n.strip()]
        for name in orphans:
            try:
                subprocess.run(_stop_container_cmd(name), capture_output=True, timeout=15)
            except Exception:
                pass
        if orphans:
            logger.info("Stopped %d orphaned containers: %s", len(orphans), orphans)
    except Exception as e:
        logger.warning("Failed to clean up orphaned containers: %s", e)


def _build_mounts(
    group_folder: str,
    is_main: bool,
    project_root: Path,
    data_dir: Path,
    groups_dir: Path,
    backend: str,
) -> list[tuple[str, str, bool]]:
    """构建容器挂载点"""
    mounts: list[tuple[str, str, bool]] = []
    group_dir = groups_dir / group_folder

    # 主群挂载项目目录
    if is_main:
        mounts.append((str(project_root), "/workspace/project", True))
        env_file = project_root / ".env"
        if env_file.exists():
            mounts.append(("/dev/null", "/workspace/project/.env", True))
        mounts.append((str(group_dir), "/workspace/group", False))
    else:
        mounts.append((str(group_dir), "/workspace/group", False))
        global_dir = groups_dir / "global"
        if global_dir.is_dir():
            mounts.append((str(global_dir), "/workspace/global", True))

    # Claude 会话目录
    sessions_dir = data_dir / "sessions" / group_folder / ".claude"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    settings_file = sessions_dir / "settings.json"
    if not settings_file.exists():
        settings_file.write_text(
            json.dumps(
                {
                    "env": {
                        "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
                        "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD": "1",
                        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0",
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    mounts.append((str(sessions_dir), "/home/node/.claude", False))

    # IPC 目录
    ipc_dir = data_dir / "ipc" / group_folder
    for sub in ("messages", "tasks", "input"):
        (ipc_dir / sub).mkdir(parents=True, exist_ok=True)
    mounts.append((str(ipc_dir), "/workspace/ipc", False))

    return mounts


def _build_env_vars(
    backend: str,
    credential_proxy_port: int,
    model: str | None = None,
) -> list[str]:
    """构建容器环境变量"""
    args = []

    tz = os.environ.get("TZ", "Asia/Shanghai")
    args.extend(["-e", f"TZ={tz}"])

    if backend == "claude":
        # Claude 后端通过 credential proxy 注入凭证
        args.extend(["-e", f"ANTHROPIC_BASE_URL=http://{CONTAINER_HOST_GATEWAY}:{credential_proxy_port}"])
        args.extend(["-e", "ANTHROPIC_API_KEY=placeholder"])
        if model:
            args.extend(["-e", f"CLAUDE_MODEL={model}"])
    elif backend in ("iflow", "agno"):
        # iFlow 和 Agno 后端使用 OpenAI 兼容 API
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            args.extend(["-e", f"OPENAI_API_KEY={openai_key}"])
        openai_url = os.environ.get("OPENAI_BASE_URL", "")
        if openai_url:
            args.extend(["-e", f"OPENAI_BASE_URL={openai_url}"])
        if model:
            args.extend(["-e", f"IFLOW_MODEL={model}" if backend == "iflow" else f"AGNO_MODEL={model}"])

    return args


def _build_args(
    runtime: str,
    container_name: str,
    mounts: list[tuple[str, str, bool]],
    env_vars: list[str],
    container_image: str = "iflowclaw-agent:latest",
) -> list[str]:
    """构建 docker run 参数"""
    args = [runtime, "run", "-i", "--rm", "--name", container_name]

    args.extend(env_vars)
    args.extend(_host_gateway_args())

    host_uid = os.getuid()
    host_gid = os.getgid()
    if host_uid is not None and host_uid != 0 and host_uid != 1000:
        args.extend(["--user", f"{host_uid}:{host_gid}"])
        args.extend(["-e", "HOME=/home/node"])

    for host_path, container_path, readonly in mounts:
        mode = "ro" if readonly else "rw"
        args.extend(["-v", f"{host_path}:{container_path}:{mode}"])

    args.append(container_image)
    return args


class ContainerBackend:
    name = "container"

    def __init__(
        self,
        *,
        model: str | None = None,
        backend: str = "claude",
        project_root: str | None = None,
        data_dir: str | None = None,
        groups_dir: str | None = None,
        container_timeout_ms: int = 1_800_000,
        idle_timeout_ms: int = 180_000,
        credential_proxy_port: int = 3001,
        container_image: str = "iflowclaw-agent:latest",
    ) -> None:
        self._model = model
        self._backend = backend
        self._project_root = Path(project_root) if project_root else Path.cwd()
        self._data_dir = Path(data_dir) if data_dir else self._project_root / "data"
        self._groups_dir = Path(groups_dir) if groups_dir else self._project_root / "groups"
        self._container_timeout_ms = container_timeout_ms
        self._idle_timeout_ms = idle_timeout_ms
        self._credential_proxy_port = credential_proxy_port
        self._container_image = container_image

    async def run(
        self,
        *,
        user_prompt: str,
        context: BackendContext,
        on_stream: StreamCallback | None = None,
    ) -> BackendResult:
        try:
            runtime = _get_runtime()
        except Exception as e:
            return BackendResult(status="error", text="", error=str(e))

        # 如果是Claude后端，启动凭证代理
        proxy_server = None
        if self._backend == "claude":
            try:
                from ..config import AppConfig
                from ..credential_proxy import start_credential_proxy

                # 创建一个临时配置对象用于凭证代理
                # 注意：这里需要从环境变量或配置中获取凭证信息
                config = AppConfig(
                    project_root=self._project_root,
                    data_dir=self._data_dir,
                    groups_dir=self._groups_dir,
                    credential_proxy_port=self._credential_proxy_port,
                )
                proxy_server = await start_credential_proxy(config, port=self._credential_proxy_port)
            except Exception as e:
                logger.warning("Failed to start credential proxy: %s", e)

        _cleanup_orphans()

        # 主运行逻辑，使用try/finally确保清理
        return await self._run_with_cleanup(
            runtime=runtime,
            user_prompt=user_prompt,
            context=context,
            on_stream=on_stream,
            proxy_server=proxy_server,
        )

    async def _run_with_cleanup(
        self,
        *,
        runtime: str,
        user_prompt: str,
        context: BackendContext,
        on_stream: StreamCallback | None,
        proxy_server: asyncio.AbstractServer | None,
    ) -> BackendResult:
        """实际运行容器，并在结束后清理凭证代理"""
        try:
            return await self._run_container(
                runtime=runtime,
                user_prompt=user_prompt,
                context=context,
                on_stream=on_stream,
            )
        finally:
            if proxy_server:
                try:
                    proxy_server.close()
                    await proxy_server.wait_closed()
                except Exception as e:
                    logger.warning("Failed to close credential proxy: %s", e)

    async def _run_container(
        self,
        *,
        runtime: str,
        user_prompt: str,
        context: BackendContext,
        on_stream: StreamCallback | None,
    ) -> BackendResult:
        """容器运行的主逻辑"""

        mounts = _build_mounts(
            context.group_folder,
            context.is_main,
            self._project_root,
            self._data_dir,
            self._groups_dir,
            self._backend,
        )

        env_vars = _build_env_vars(
            self._backend,
            self._credential_proxy_port,
            self._model,
        )

        safe_name = context.group_folder.replace("/", "-").replace("\\", "-")[:50]
        container_name = f"iflowclaw-{safe_name}-{int(time.time() * 1000) % 100000}"

        container_args = _build_args(
            runtime,
            container_name,
            mounts,
            env_vars,
            self._container_image,
        )

        input_data: dict[str, Any] = {
            "prompt": user_prompt,
            "sessionId": context.session_id,
            "groupFolder": context.group_folder,
            "chatJid": context.chat_jid,
            "isMain": context.is_main,
            "assistantName": os.environ.get("ASSISTANT_NAME", "iFlow"),
            "backend": self._backend,
        }
        if self._model:
            input_data["model"] = self._model
        if context.system_prompt:
            input_data["systemPrompt"] = context.system_prompt

        logger.info("Spawning container: %s (backend: %s)", container_name, self._backend)

        group_dir = self._groups_dir / context.group_folder
        group_dir.mkdir(parents=True, exist_ok=True)

        timeout_ms = max(self._container_timeout_ms, self._idle_timeout_ms + 30_000)

        proc = await asyncio.create_subprocess_exec(
            *container_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        proc.stdin.write(json.dumps(input_data).encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        await proc.stdin.wait_closed()

        stdout_buf: list[str] = []
        new_session_id: str | None = None
        had_streaming_output = False
        timed_out = False
        result_futures: list[asyncio.Task[None]] = []
        parse_buffer = ""

        timeout_task: asyncio.TimerHandle | None = None
        loop = asyncio.get_running_loop()

        def _kill_on_timeout() -> None:
            nonlocal timed_out
            timed_out = True
            logger.error("Container %s timed out", container_name)
            try:
                subprocess.run(_stop_container_cmd(container_name), capture_output=True, timeout=15)
            except Exception:
                if proc.returncode is None:
                    proc.kill()

        def _reset_timeout() -> None:
            nonlocal timeout_task
            if timeout_task:
                timeout_task.cancel()
            timeout_task = loop.call_later(timeout_ms / 1000, _kill_on_timeout)

        _reset_timeout()

        async def _read_stream(stream: asyncio.StreamReader, is_stdout: bool) -> None:
            nonlocal parse_buffer, new_session_id, had_streaming_output
            while True:
                try:
                    chunk = await asyncio.wait_for(stream.read(65536), timeout=timeout_ms / 1000 + 60)
                except TimeoutError:
                    break
                if not chunk:
                    break

                text = chunk.decode("utf-8", errors="replace")

                if is_stdout:
                    stdout_buf.append(text)
                    if on_stream:
                        parse_buffer += text
                        while True:
                            start_idx = parse_buffer.find(OUTPUT_START_MARKER)
                            if start_idx == -1:
                                break
                            end_idx = parse_buffer.find(OUTPUT_END_MARKER, start_idx)
                            if end_idx == -1:
                                break
                            json_str = parse_buffer[start_idx + len(OUTPUT_START_MARKER) : end_idx].strip()
                            parse_buffer = parse_buffer[end_idx + len(OUTPUT_END_MARKER) :]
                            try:
                                data = json.loads(json_str)
                                sid = data.get("newSessionId")
                                if sid:
                                    new_session_id = sid
                                had_streaming_output = True
                                _reset_timeout()
                                result_text = data.get("result")
                                if result_text:
                                    t = asyncio.create_task(on_stream(str(result_text)))
                                    result_futures.append(t)
                            except Exception:
                                pass
                else:
                    for line in text.strip().splitlines():
                        if line:
                            logger.debug("[container:%s] %s", context.group_folder, line)

        stdout_task = asyncio.create_task(_read_stream(proc.stdout, True))
        stderr_task = asyncio.create_task(_read_stream(proc.stderr, False))

        try:
            await asyncio.wait_for(proc.wait(), timeout=(timeout_ms / 1000) + 60)
        except TimeoutError:
            timed_out = True
            try:
                subprocess.run(_stop_container_cmd(container_name), capture_output=True, timeout=15)
            except Exception:
                if proc.returncode is None:
                    proc.kill()

        if timeout_task:
            timeout_task.cancel()

        await asyncio.sleep(0.1)
        for t in (stdout_task, stderr_task):
            if not t.done():
                t.cancel()

        if result_futures:
            await asyncio.gather(*result_futures, return_exceptions=True)

        stdout_text = "".join(stdout_buf)

        if timed_out:
            if had_streaming_output:
                return BackendResult(status="success", text="", new_session_id=new_session_id)
            return BackendResult(status="error", text="", error=f"Container timed out after {timeout_ms}ms")

        if proc.returncode != 0:
            return BackendResult(
                status="error",
                text="",
                error=f"Container exited with code {proc.returncode}",
                new_session_id=new_session_id,
            )

        if on_stream:
            return BackendResult(status="success", text="", new_session_id=new_session_id)

        try:
            start_idx = stdout_text.find(OUTPUT_START_MARKER)
            end_idx = stdout_text.find(OUTPUT_END_MARKER)
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = stdout_text[start_idx + len(OUTPUT_START_MARKER) : end_idx].strip()
            else:
                lines = stdout_text.strip().splitlines()
                json_str = lines[-1] if lines else "{}"
            data = json.loads(json_str)
            return BackendResult(
                status=data.get("status", "success"),
                text=str(data.get("result", "")),
                new_session_id=data.get("newSessionId"),
                error=data.get("error"),
            )
        except Exception as e:
            return BackendResult(status="error", text="", error=f"Failed to parse output: {e}")
