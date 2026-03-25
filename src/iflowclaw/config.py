from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .env import read_env_file

RuntimeBackend = Literal["iflow", "claude", "agno", "container"]


@dataclass(slots=True)
class BackendCredentials:
    """各后端的凭证配置"""

    # Claude 后端
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    claude_oauth_token: str | None = None

    # OpenAI 兼容 API（iFlow 和 Agno 后端共用）
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com"
    openai_model: str | None = None


@dataclass(slots=True)
class AppConfig:
    project_root: Path
    store_dir: Path
    groups_dir: Path
    data_dir: Path
    logs_dir: Path
    sender_allowlist_path: Path
    mount_allowlist_path: Path
    assistant_name: str
    feishu_app_id: str
    feishu_app_secret: str
    poll_interval_ms: int
    scheduler_poll_interval_ms: int
    ipc_poll_interval_ms: int
    agent_timeout_ms: int
    idle_timeout_ms: int
    max_concurrent_agents: int
    container_timeout_ms: int
    container_image: str
    credential_proxy_port: int
    timezone: str
    default_backend: RuntimeBackend
    default_execution_mode: str
    claude_model: str | None
    agno_model: str | None
    trigger_pattern: re.Pattern[str]
    credentials: BackendCredentials = field(default_factory=BackendCredentials)


def load_config(project_root: Path | None = None) -> AppConfig:
    root = project_root or Path.cwd()
    env_values = read_env_file(
        [
            "ASSISTANT_NAME",
            "FEISHU_APP_ID",
            "FEISHU_APP_SECRET",
            "TZ",
            "AGENT_TIMEOUT",
            "IDLE_TIMEOUT",
            "MAX_CONCURRENT_AGENTS",
            "AGENT_BACKEND",
            "DEFAULT_EXECUTION_MODE",
            "CLAUDE_MODEL",
            "AGNO_MODEL",
            "CONTAINER_TIMEOUT",
            "CONTAINER_IMAGE",
            "CREDENTIAL_PROXY_PORT",
            # 凭证
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "CLAUDE_OAUTH_TOKEN",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "OPENAI_MODEL",
        ],
        root,
    )

    def _env(key: str, default: str = "") -> str:
        return os.environ.get(key) or env_values.get(key, default)

    assistant_name = _env("ASSISTANT_NAME", "iFlow")
    timezone = _env("TZ", "Asia/Shanghai")
    backend = _env("AGENT_BACKEND", "iflow").strip().lower()
    default_backend: RuntimeBackend = "claude" if backend == "claude" else ("agno" if backend == "agno" else "iflow")
    escaped_name = re.escape(assistant_name)
    default_execution_mode = _env("DEFAULT_EXECUTION_MODE", "direct").strip().lower()
    config_dir = Path(os.environ.get("HOME", str(Path.home()))) / ".config" / "iflowclaw"

    # 构建凭证配置
    credentials = BackendCredentials(
        anthropic_api_key=_env("ANTHROPIC_API_KEY") or None,
        anthropic_base_url=_env("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        claude_oauth_token=_env("CLAUDE_CODE_OAUTH_TOKEN") or _env("CLAUDE_OAUTH_TOKEN") or None,
        openai_api_key=_env("OPENAI_API_KEY") or None,
        openai_base_url=_env("OPENAI_BASE_URL", "https://api.openai.com"),
        openai_model=_env("OPENAI_MODEL") or None,
    )

    return AppConfig(
        project_root=root,
        store_dir=root / "store",
        groups_dir=root / "groups",
        data_dir=root / "data",
        logs_dir=root / "logs",
        sender_allowlist_path=config_dir / "sender-allowlist.json",
        mount_allowlist_path=config_dir / "mount-allowlist.json",
        assistant_name=assistant_name,
        feishu_app_id=_env("FEISHU_APP_ID"),
        feishu_app_secret=_env("FEISHU_APP_SECRET"),
        poll_interval_ms=2000,
        scheduler_poll_interval_ms=60000,
        ipc_poll_interval_ms=1000,
        agent_timeout_ms=int(_env("AGENT_TIMEOUT", "300000")),
        idle_timeout_ms=int(_env("IDLE_TIMEOUT", "180000")),
        max_concurrent_agents=max(1, int(_env("MAX_CONCURRENT_AGENTS", "5"))),
        container_timeout_ms=int(_env("CONTAINER_TIMEOUT", "1800000")),
        container_image=_env("CONTAINER_IMAGE", "iflowclaw-agent:latest"),
        credential_proxy_port=int(_env("CREDENTIAL_PROXY_PORT", "3001")),
        timezone=timezone,
        default_backend=default_backend,
        default_execution_mode=default_execution_mode,
        claude_model=_env("CLAUDE_MODEL"),
        agno_model=_env("AGNO_MODEL"),
        trigger_pattern=re.compile(rf"^@{escaped_name}\b", re.IGNORECASE),
        credentials=credentials,
    )
