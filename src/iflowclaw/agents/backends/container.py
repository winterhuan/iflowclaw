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

from ...config import BackendCredentials
from ...credential_proxy import build_proxy_config_for_provider, start_credential_proxy_with_proxy_config
from .base import (
    BackendConfigError,
    BackendContext,
    BackendError,
    BackendExecutionError,
    BackendNotInstalledError,
    BackendResult,
    BackendTimeoutError,
    StreamCallback,
)

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
            raise BackendNotInstalledError("container", "docker or podman")
    return _detected_runtime


def _host_gateway_args() -> list[str]:
    if platform.system() == "Linux":
        return [f"--add-host={CONTAINER_HOST_GATEWAY}:host-gateway"]
    return []


def _stop_container_cmd(name: str) -> list[str]:
    return [_get_runtime(), "stop", "-t", "1", name]


def _stop_container_with_retry(name: str, max_retries: int = 3, retry_delay: float = 1.0) -> bool:
    """Stop a container with retry logic.

    Args:
        name: Container name to stop
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries in seconds

    Returns:
        True if container was stopped successfully, False otherwise
    """
    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                _stop_container_cmd(name),
                capture_output=True,
                timeout=15,
            )
            if result.returncode == 0:
                return True
            logger.debug(
                "Container stop attempt %d/%d failed for %s: returncode=%d",
                attempt + 1,
                max_retries,
                name,
                result.returncode,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "Container stop attempt %d/%d timed out for %s",
                attempt + 1,
                max_retries,
                name,
            )
        except Exception as e:
            logger.warning(
                "Container stop attempt %d/%d failed for %s: %s",
                attempt + 1,
                max_retries,
                name,
                e,
            )

        if attempt < max_retries - 1:
            time.sleep(retry_delay * (attempt + 1))  # Exponential backoff

    logger.error("Failed to stop container %s after %d attempts", name, max_retries)
    return False


def _cleanup_orphans() -> None:
    """Clean up orphaned containers with retry logic."""
    try:
        result = subprocess.run(
            [_get_runtime(), "ps", "--filter", "name=iflowclaw-", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning("Failed to list containers: returncode=%d", result.returncode)
            return

        orphans = [name.strip() for name in result.stdout.strip().splitlines() if name.strip()]
        if not orphans:
            return

        stopped = []
        failed = []
        for name in orphans:
            if _stop_container_with_retry(name):
                stopped.append(name)
            else:
                failed.append(name)

        if stopped:
            logger.info("Stopped %d orphaned containers: %s", len(stopped), stopped)
        if failed:
            logger.warning("Failed to stop %d orphaned containers: %s", len(failed), failed)

    except subprocess.TimeoutExpired:
        logger.warning("Timeout while listing containers for cleanup")
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
    mounts: list[tuple[str, str, bool]] = []
    group_dir = groups_dir / group_folder

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

    _sync_skills_for_container(project_root, sessions_dir, group_dir, backend)
    mounts.append((str(sessions_dir), "/home/node/.claude", False))

    ipc_dir = data_dir / "ipc" / group_folder
    for sub in ("messages", "tasks", "input"):
        (ipc_dir / sub).mkdir(parents=True, exist_ok=True)
    mounts.append((str(ipc_dir), "/workspace/ipc", False))

    return mounts


def _sync_skills_for_container(
    project_root: Path,
    sessions_dir: Path,
    group_dir: Path,
    backend: str,
) -> None:
    from ...skills import sync_skills_for_backend

    kwargs = dict(
        group_dir="/workspace/group",
        global_dir="/workspace/global",
        ipc_dir="/workspace/ipc",
        project_dir="/workspace/project",
    )

    if backend == "claude":
        sync_skills_for_backend("claude", project_root, sessions_dir.parent, **kwargs)
    elif backend == "iflow":
        sync_skills_for_backend("iflow", project_root, group_dir, **kwargs)
    elif backend == "agno":
        sync_skills_for_backend("agno", project_root, group_dir, **kwargs)


def _build_env_vars(
    backend: str,
    credential_proxy_port: int,
    timezone: str,
    model: str | None = None,
    proxy_provider: str | None = None,
) -> list[str]:
    args = ["-e", f"TZ={timezone}"]

    if proxy_provider == "anthropic":
        args.extend(["-e", f"ANTHROPIC_BASE_URL=http://{CONTAINER_HOST_GATEWAY}:{credential_proxy_port}"])
        args.extend(["-e", "ANTHROPIC_API_KEY=placeholder"])
    elif proxy_provider == "openai":
        args.extend(["-e", f"OPENAI_BASE_URL=http://{CONTAINER_HOST_GATEWAY}:{credential_proxy_port}"])
        args.extend(["-e", "OPENAI_API_KEY=placeholder"])

    if model:
        if backend == "claude":
            args.extend(["-e", f"CLAUDE_MODEL={model}"])
        elif backend == "iflow":
            args.extend(["-e", f"OPENAI_MODEL={model}"])
        elif backend == "agno":
            args.extend(["-e", f"AGNO_MODEL={model}"])

    return args


def _validate_agno_model(model: str | None) -> None:
    if not model or ":" not in model:
        return
    provider, _ = model.split(":", 1)
    if provider.strip().lower() != "openai":
        raise BackendConfigError("Agno backend only supports OpenAI models. Use `gpt-4o` or `openai:gpt-4o`.")


def _resolve_proxy_provider(backend: str, model: str | None) -> str | None:
    if backend == "claude":
        return "anthropic"
    if backend == "iflow":
        return "openai"
    if backend == "agno":
        _validate_agno_model(model)
        return "openai"
    return None


def _validate_proxy_credentials(proxy_provider: str, credentials: BackendCredentials, backend: str) -> None:
    if proxy_provider == "anthropic":
        if credentials.anthropic_api_key or credentials.claude_oauth_token:
            return
        raise BackendConfigError(
            f"{backend} container backend requires ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN"
        )
    if proxy_provider == "openai":
        if credentials.openai_api_key:
            return
        raise BackendConfigError(f"{backend} container backend requires OPENAI_API_KEY")


def _build_args(
    runtime: str,
    container_name: str,
    mounts: list[tuple[str, str, bool]],
    env_vars: list[str],
    container_image: str = "iflowclaw-agent:latest",
) -> list[str]:
    args = [runtime, "run", "-i", "--rm", "--name", container_name]
    args.extend(env_vars)
    args.extend(_host_gateway_args())

    host_uid = os.getuid() if hasattr(os, "getuid") else None
    host_gid = os.getgid() if hasattr(os, "getgid") else None
    if host_uid is not None and host_uid != 0 and host_uid != 1000:
        args.extend(["--user", f"{host_uid}:{host_gid}"])
        args.extend(["-e", "HOME=/home/node"])

    for host_path, container_path, readonly in mounts:
        if readonly:
            args.extend(["-v", f"{host_path}:{container_path}:ro"])
        else:
            args.extend(["-v", f"{host_path}:{container_path}"])

    args.append(container_image)
    return args


def _ipc_input_dir(data_dir: Path, group_folder: str) -> Path:
    return data_dir / "ipc" / group_folder / "input"


def _write_close_sentinel(data_dir: Path, group_folder: str) -> None:
    ipc_input_dir = _ipc_input_dir(data_dir, group_folder)
    ipc_input_dir.mkdir(parents=True, exist_ok=True)
    (ipc_input_dir / "_close").write_text("", encoding="utf-8")


def _clear_ipc_input(data_dir: Path, group_folder: str) -> None:
    ipc_input_dir = _ipc_input_dir(data_dir, group_folder)
    if not ipc_input_dir.exists():
        return
    for path in ipc_input_dir.iterdir():
        if not path.is_file():
            continue
        if path.name == "_close" or path.name.endswith(".json.tmp"):
            try:
                path.unlink()
            except OSError:
                pass


def _result_from_payload(data: dict[str, Any], fallback_session_id: str | None = None) -> BackendResult:
    result_text = data.get("result")
    return BackendResult(
        status=str(data.get("status", "success")),
        text="" if result_text is None else str(result_text),
        new_session_id=data.get("newSessionId") or fallback_session_id,
        error=data.get("error"),
    )


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
        assistant_name: str = "iFlow",
        timezone: str = "Asia/Shanghai",
        credentials: BackendCredentials | None = None,
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
        self._assistant_name = assistant_name
        self._timezone = timezone
        self._credentials = credentials or BackendCredentials()

    async def run(
        self,
        *,
        user_prompt: str,
        context: BackendContext,
        on_stream: StreamCallback | None = None,
    ) -> BackendResult:
        try:
            runtime = _get_runtime()
        except BackendError:
            raise

        proxy_provider = _resolve_proxy_provider(self._backend, self._model)
        proxy_server = None
        if proxy_provider is not None:
            _validate_proxy_credentials(proxy_provider, self._credentials, self._backend)
            try:
                proxy_server = await start_credential_proxy_with_proxy_config(
                    build_proxy_config_for_provider(proxy_provider, self._credentials),
                    port=self._credential_proxy_port,
                )
            except Exception as e:
                raise BackendExecutionError(f"Failed to start credential proxy: {e}") from e

        _cleanup_orphans()

        return await self._run_with_cleanup(
            runtime=runtime,
            user_prompt=user_prompt,
            context=context,
            on_stream=on_stream,
            proxy_provider=proxy_provider,
            proxy_server=proxy_server,
        )

    async def _run_with_cleanup(
        self,
        *,
        runtime: str,
        user_prompt: str,
        context: BackendContext,
        on_stream: StreamCallback | None,
        proxy_provider: str | None,
        proxy_server: asyncio.AbstractServer | None,
    ) -> BackendResult:
        try:
            return await self._run_container(
                runtime=runtime,
                user_prompt=user_prompt,
                context=context,
                on_stream=on_stream,
                proxy_provider=proxy_provider,
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
        proxy_provider: str | None,
    ) -> BackendResult:
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
            self._timezone,
            self._model,
            proxy_provider,
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
            "assistantName": self._assistant_name,
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
        result_payload: dict[str, Any] | None = None

        timeout_task: asyncio.TimerHandle | None = None
        loop = asyncio.get_running_loop()
        result_future: asyncio.Future[dict[str, Any]] = loop.create_future()

        def _stop_container() -> None:
            try:
                subprocess.run(_stop_container_cmd(container_name), capture_output=True, timeout=15)
            except Exception:
                if proc.returncode is None:
                    proc.kill()

        def _kill_on_timeout() -> None:
            nonlocal timed_out
            timed_out = True
            logger.error("Container %s timed out", container_name)
            _stop_container()

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
                        except Exception:
                            continue

                        sid = data.get("newSessionId")
                        if sid:
                            new_session_id = sid
                        had_streaming_output = True
                        _reset_timeout()
                        if not result_future.done():
                            result_future.set_result(data)
                        if on_stream:
                            result_text = data.get("result")
                            if result_text:
                                task = asyncio.create_task(on_stream(str(result_text)))
                                result_futures.append(task)
                else:
                    for line in text.strip().splitlines():
                        if line:
                            logger.debug("[container:%s] %s", context.group_folder, line)

        stdout_task = asyncio.create_task(_read_stream(proc.stdout, True))
        stderr_task = asyncio.create_task(_read_stream(proc.stderr, False))
        proc_wait_task = asyncio.create_task(proc.wait())

        try:
            if on_stream:
                await asyncio.wait_for(proc_wait_task, timeout=(timeout_ms / 1000) + 60)
            else:
                done, _ = await asyncio.wait(
                    {proc_wait_task, result_future},
                    timeout=(timeout_ms / 1000) + 60,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    timed_out = True
                    _stop_container()
                    try:
                        await asyncio.wait_for(proc_wait_task, timeout=15)
                    except TimeoutError:
                        if proc.returncode is None:
                            proc.kill()
                elif result_future in done:
                    result_payload = result_future.result()
                    if timeout_task:
                        timeout_task.cancel()
                        timeout_task = None
                    try:
                        _write_close_sentinel(self._data_dir, context.group_folder)
                    except OSError:
                        _stop_container()
                    if not proc_wait_task.done():
                        try:
                            await asyncio.wait_for(proc_wait_task, timeout=15)
                        except TimeoutError:
                            _stop_container()
                            try:
                                await asyncio.wait_for(proc_wait_task, timeout=15)
                            except TimeoutError:
                                timed_out = True
        except TimeoutError:
            timed_out = True
            _stop_container()

        if timeout_task:
            timeout_task.cancel()

        await asyncio.sleep(0.1)
        for task in (stdout_task, stderr_task):
            if not task.done():
                task.cancel()

        if result_futures:
            await asyncio.gather(*result_futures, return_exceptions=True)

        stdout_text = "".join(stdout_buf)
        _clear_ipc_input(self._data_dir, context.group_folder)

        if timed_out and result_payload is None:
            if had_streaming_output:
                return BackendResult(status="success", text="", new_session_id=new_session_id)
            raise BackendTimeoutError(timeout_ms / 1000)

        if result_payload is not None:
            return _result_from_payload(result_payload, new_session_id)

        if proc.returncode != 0:
            raise BackendExecutionError(
                f"Container exited with code {proc.returncode}",
                partial_output=stdout_text,
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
            return _result_from_payload(data, new_session_id)
        except Exception as e:
            raise BackendExecutionError(f"Failed to parse output: {e}") from e
