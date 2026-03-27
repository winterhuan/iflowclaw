from __future__ import annotations

import asyncio
import json
import os
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from iflowclaw.agents.backends.base import BackendContext, BackendResult
from iflowclaw.agents.backends.container import (
    OUTPUT_END_MARKER,
    OUTPUT_START_MARKER,
    ContainerBackend,
    _build_env_vars,
    _resolve_proxy_provider,
)
from iflowclaw.agents.backends.base import BackendConfigError
from iflowclaw.agents.runner import AgentRunner
from iflowclaw.config import BackendCredentials, load_config
from iflowclaw.credential_proxy import ProxyConfig, _apply_auth_headers, build_proxy_config_for_provider
from iflowclaw.group_queue import GroupQueue
from iflowclaw.types import AgentConfig, AgentInput

_TEST_ROOT = Path(__file__).resolve().parent / ".tmp_runtime_fixes"


@contextmanager
def workspace_tmp_dir():
    root = _TEST_ROOT / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


class TestConfigAliases(unittest.TestCase):
    def test_load_config_supports_legacy_claude_oauth_token_name(self) -> None:
        with workspace_tmp_dir() as root:
            (root / "store").mkdir(parents=True, exist_ok=True)
            (root / ".env").write_text(
                "FEISHU_APP_ID=test_id\n"
                "FEISHU_APP_SECRET=test_secret\n"
                "CLAUDE_OAUTH_TOKEN=legacy-token\n",
                encoding="utf-8",
            )

            config = load_config(root)

            self.assertEqual(config.credentials.claude_oauth_token, "legacy-token")


class TestCredentialProxyHeaders(unittest.TestCase):
    def test_apply_auth_headers_uses_api_key_mode(self) -> None:
        headers = {"authorization": "Bearer stale", "x-api-key": "stale"}
        proxy_config = ProxyConfig(
            auth_mode="api-key",
            api_key="real-key",
            oauth_token="",
            upstream_url="https://api.anthropic.com",
        )

        _apply_auth_headers(headers, proxy_config)

        self.assertEqual(headers["x-api-key"], "real-key")
        self.assertNotIn("authorization", headers)

    def test_apply_auth_headers_uses_oauth_without_existing_header(self) -> None:
        headers: dict[str, str] = {}
        proxy_config = ProxyConfig(
            auth_mode="oauth",
            api_key="",
            oauth_token="oauth-token",
            upstream_url="https://api.anthropic.com",
        )

        _apply_auth_headers(headers, proxy_config)

        self.assertEqual(headers["authorization"], "Bearer oauth-token")
        self.assertNotIn("x-api-key", headers)

    def test_apply_auth_headers_uses_bearer_mode(self) -> None:
        headers = {"authorization": "Bearer stale", "x-api-key": "stale"}
        proxy_config = ProxyConfig(
            auth_mode="bearer",
            api_key="",
            oauth_token="openai-key",
            upstream_url="https://api.openai.com",
        )

        _apply_auth_headers(headers, proxy_config)

        self.assertEqual(headers["authorization"], "Bearer openai-key")
        self.assertNotIn("x-api-key", headers)

    def test_build_proxy_config_for_openai_provider(self) -> None:
        proxy_config = build_proxy_config_for_provider(
            "openai",
            BackendCredentials(
                openai_api_key="openai-key",
                openai_base_url="https://openai.example/v1",
            ),
        )

        self.assertEqual(proxy_config.auth_mode, "bearer")
        self.assertEqual(proxy_config.oauth_token, "openai-key")
        self.assertEqual(proxy_config.upstream_url, "https://openai.example/v1")


class _FakeContainerBackend:
    init_kwargs: dict[str, object] | None = None

    def __init__(self, **kwargs) -> None:
        type(self).init_kwargs = kwargs

    async def run(self, *, user_prompt: str, context, on_stream=None) -> BackendResult:  # noqa: ANN001
        return BackendResult(status="success", text=user_prompt)


class TestContainerRunnerWiring(unittest.IsolatedAsyncioTestCase):
    async def test_runner_passes_host_config_to_container_backend(self) -> None:
        with workspace_tmp_dir() as root:
            (root / "store").mkdir(parents=True, exist_ok=True)
            (root / "groups" / "test_group").mkdir(parents=True, exist_ok=True)
            (root / "data" / "ipc" / "test_group").mkdir(parents=True, exist_ok=True)
            os.environ["FEISHU_APP_ID"] = "test_id"
            os.environ["FEISHU_APP_SECRET"] = "test_secret"

            config = load_config(root)
            config.container_image = "custom-image:latest"
            config.assistant_name = "TestBot"
            config.timezone = "UTC"
            config.agno_model = "openai:gpt-4o-mini"
            config.credentials = BackendCredentials(
                anthropic_api_key="anthropic-key",
                anthropic_base_url="https://anthropic.example",
                claude_oauth_token="oauth-token",
                openai_api_key="openai-key",
                openai_base_url="https://openai.example",
            )

            runner = AgentRunner(config)
            agent_input = AgentInput(
                prompt="hello",
                group_folder="test_group",
                chat_jid="feishu:test",
                is_main=False,
            )
            agent_config = AgentConfig(
                backend="agno",
                execution_mode="container",
            )

            with patch.dict("iflowclaw.agents.runner._BACKEND_MAP", {"container": _FakeContainerBackend}):
                result = await runner.run(
                    agent_input=agent_input,
                    agent_config=agent_config,
                    user_prompt="hello",
                )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.text, "hello")
            self.assertIsNotNone(_FakeContainerBackend.init_kwargs)
            self.assertEqual(_FakeContainerBackend.init_kwargs["backend"], "agno")
            self.assertEqual(_FakeContainerBackend.init_kwargs["model"], "openai:gpt-4o-mini")
            self.assertEqual(_FakeContainerBackend.init_kwargs["container_image"], "custom-image:latest")
            self.assertEqual(_FakeContainerBackend.init_kwargs["assistant_name"], "TestBot")
            self.assertEqual(_FakeContainerBackend.init_kwargs["timezone"], "UTC")
            self.assertEqual(_FakeContainerBackend.init_kwargs["credentials"].openai_api_key, "openai-key")

    async def test_runner_supports_container_as_default_backend(self) -> None:
        with workspace_tmp_dir() as root:
            (root / "store").mkdir(parents=True, exist_ok=True)
            (root / "groups" / "test_group").mkdir(parents=True, exist_ok=True)
            (root / "data" / "ipc" / "test_group").mkdir(parents=True, exist_ok=True)
            os.environ["FEISHU_APP_ID"] = "test_id"
            os.environ["FEISHU_APP_SECRET"] = "test_secret"

            config = load_config(root)
            config.default_backend = "container"
            config.claude_model = "sonnet"

            runner = AgentRunner(config)
            agent_input = AgentInput(
                prompt="hello",
                group_folder="test_group",
                chat_jid="feishu:test",
                is_main=True,
            )

            with patch.dict("iflowclaw.agents.runner._BACKEND_MAP", {"container": _FakeContainerBackend}):
                result = await runner.run(
                    agent_input=agent_input,
                    agent_config=AgentConfig(),
                    user_prompt="hello",
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(_FakeContainerBackend.init_kwargs)
            self.assertEqual(_FakeContainerBackend.init_kwargs["backend"], "claude")
            self.assertEqual(_FakeContainerBackend.init_kwargs["model"], "sonnet")


class TestContainerBackendLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_run_container_returns_after_first_output_and_preserves_unconsumed_ipc(self) -> None:
        with workspace_tmp_dir() as root:
            data_dir = root / "data"
            groups_dir = root / "groups"
            group_dir = groups_dir / "test_group"
            input_dir = data_dir / "ipc" / "test_group" / "input"
            group_dir.mkdir(parents=True, exist_ok=True)
            input_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "pending.json").write_text('{"type":"message","text":"follow-up"}', encoding="utf-8")

            backend = ContainerBackend(
                backend="agno",
                project_root=str(root),
                data_dir=str(data_dir),
                groups_dir=str(groups_dir),
                idle_timeout_ms=500,
                container_timeout_ms=5_000,
            )
            context = BackendContext(
                group_folder="test_group",
                chat_jid="feishu:test",
                is_main=False,
                session_id="existing-session",
                group_dir=str(group_dir),
                ipc_dir=str(data_dir / "ipc" / "test_group"),
                system_prompt=None,
                timeout_s=5.0,
            )

            class _FakeStdin:
                def __init__(self) -> None:
                    self.payload = b""

                def write(self, data: bytes) -> None:
                    self.payload += data

                async def drain(self) -> None:
                    return None

                def close(self) -> None:
                    return None

                async def wait_closed(self) -> None:
                    return None

            class _FakeProc:
                def __init__(self) -> None:
                    self.stdin = _FakeStdin()
                    self.stdout = asyncio.StreamReader()
                    self.stderr = asyncio.StreamReader()
                    self.returncode: int | None = None
                    self.wait_calls = 0
                    payload = (
                        f"{OUTPUT_START_MARKER}\n"
                        + json.dumps(
                            {
                                "status": "success",
                                "result": "hello from container",
                                "newSessionId": "session-123",
                            }
                        )
                        + f"\n{OUTPUT_END_MARKER}\n"
                    )
                    self.stdout.feed_data(payload.encode("utf-8"))
                    self.stdout.feed_eof()
                    self.stderr.feed_eof()

                async def wait(self) -> int:
                    self.wait_calls += 1
                    while not (input_dir / "_close").exists():
                        await asyncio.sleep(0.01)
                    self.returncode = 0
                    return 0

                def kill(self) -> None:
                    self.returncode = -9

            proc_holder: dict[str, _FakeProc] = {}

            async def _fake_create_subprocess_exec(*args, **kwargs) -> _FakeProc:  # noqa: ANN002, ANN003
                proc = _FakeProc()
                proc_holder["proc"] = proc
                return proc

            with (
                patch("iflowclaw.agents.backends.container._sync_skills_for_container"),
                patch(
                    "iflowclaw.agents.backends.container.asyncio.create_subprocess_exec",
                    new=_fake_create_subprocess_exec,
                ),
            ):
                result = await backend._run_container(
                    runtime="docker",
                    user_prompt="hello",
                    context=context,
                    on_stream=None,
                    proxy_provider="openai",
                )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.text, "hello from container")
            self.assertEqual(result.new_session_id, "session-123")
            self.assertIn("proc", proc_holder)
            self.assertEqual(proc_holder["proc"].wait_calls, 1)
            self.assertFalse((input_dir / "_close").exists())
            self.assertTrue((input_dir / "pending.json").exists())

    async def test_iflow_container_backend_starts_openai_proxy(self) -> None:
        backend = ContainerBackend(
            backend="iflow",
            credentials=BackendCredentials(
                openai_api_key="openai-key",
                openai_base_url="https://openai.example/v1",
            ),
        )
        context = BackendContext(
            group_folder="test_group",
            chat_jid="feishu:test",
            is_main=False,
            session_id=None,
            group_dir="/tmp/group",
            ipc_dir="/tmp/ipc",
            system_prompt=None,
            timeout_s=5.0,
        )
        captured: dict[str, object] = {}

        async def _fake_start_proxy(proxy_config, *, port, host="127.0.0.1"):  # noqa: ANN001
            captured["proxy_config"] = proxy_config
            captured["port"] = port
            captured["host"] = host

            class _FakeServer:
                def close(self) -> None:
                    captured["closed"] = True

                async def wait_closed(self) -> None:
                    captured["wait_closed"] = True

            return _FakeServer()

        async def _fake_run_with_cleanup(**kwargs):  # noqa: ANN003
            captured["proxy_provider"] = kwargs["proxy_provider"]
            return BackendResult(status="success", text="ok")

        with (
            patch("iflowclaw.agents.backends.container._get_runtime", return_value="docker"),
            patch("iflowclaw.agents.backends.container._cleanup_orphans"),
            patch(
                "iflowclaw.agents.backends.container.start_credential_proxy_with_proxy_config",
                new=_fake_start_proxy,
            ),
            patch.object(backend, "_run_with_cleanup", new=_fake_run_with_cleanup),
        ):
            result = await backend.run(user_prompt="hello", context=context)

        self.assertEqual(result.status, "success")
        self.assertEqual(captured["proxy_provider"], "openai")
        proxy_config = captured["proxy_config"]
        self.assertEqual(proxy_config.auth_mode, "bearer")
        self.assertEqual(proxy_config.oauth_token, "openai-key")
        self.assertEqual(proxy_config.upstream_url, "https://openai.example/v1")


class TestContainerProxyHelpers(unittest.TestCase):
    def test_resolve_proxy_provider_for_container_backends(self) -> None:
        self.assertEqual(_resolve_proxy_provider("claude", "sonnet"), "anthropic")
        self.assertEqual(_resolve_proxy_provider("iflow", "gpt-4o"), "openai")
        self.assertEqual(_resolve_proxy_provider("agno", "openai:gpt-4o-mini"), "openai")
        self.assertEqual(_resolve_proxy_provider("agno", "gpt-4o-mini"), "openai")

    def test_resolve_proxy_provider_rejects_non_openai_agno_models(self) -> None:
        with self.assertRaises(BackendConfigError):
            _resolve_proxy_provider("agno", "anthropic:claude-sonnet")

        with self.assertRaises(BackendConfigError):
            _resolve_proxy_provider("agno", "google:gemini-2.0-flash")

    def test_build_env_vars_routes_openai_backends_through_proxy(self) -> None:
        env_vars = _build_env_vars(
            "iflow",
            3001,
            "UTC",
            "gpt-4o",
            "openai",
        )

        self.assertIn("OPENAI_BASE_URL=http://host.docker.internal:3001", env_vars)
        self.assertIn("OPENAI_API_KEY=placeholder", env_vars)
        self.assertIn("OPENAI_MODEL=gpt-4o", env_vars)

    def test_build_env_vars_routes_agno_through_openai_proxy(self) -> None:
        env_vars = _build_env_vars(
            "agno",
            3001,
            "UTC",
            "openai:gpt-4o-mini",
            "openai",
        )

        self.assertIn("OPENAI_BASE_URL=http://host.docker.internal:3001", env_vars)
        self.assertIn("OPENAI_API_KEY=placeholder", env_vars)
        self.assertIn("AGNO_MODEL=openai:gpt-4o-mini", env_vars)


class TestGroupQueueContainerInput(unittest.TestCase):
    def test_send_message_does_not_push_live_input_to_container_sessions(self) -> None:
        queue = GroupQueue(max_concurrent=1, idle_timeout_ms=1_000)
        queue.register_container("feishu:test")

        result = queue.send_message("feishu:test", "<context>hello</context>")

        self.assertFalse(result)
