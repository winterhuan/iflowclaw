from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .env import read_env_file

RuntimeBackend = Literal["iflow", "claude"]


@dataclass(slots=True)
class AppConfig:
    project_root: Path
    store_dir: Path
    groups_dir: Path
    data_dir: Path
    logs_dir: Path
    sender_allowlist_path: Path
    assistant_name: str
    feishu_app_id: str
    feishu_app_secret: str
    poll_interval_ms: int
    scheduler_poll_interval_ms: int
    ipc_poll_interval_ms: int
    agent_timeout_ms: int
    idle_timeout_ms: int
    max_concurrent_agents: int
    timezone: str
    default_backend: RuntimeBackend
    iflow_model: str | None
    claude_model: str | None
    trigger_pattern: re.Pattern[str]


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
            "IFLOW_MODEL",
            "CLAUDE_MODEL",
        ],
        root,
    )

    assistant_name = os.environ.get("ASSISTANT_NAME") or env_values.get(
        "ASSISTANT_NAME", "iFlow"
    )
    timezone = os.environ.get("TZ") or env_values.get("TZ") or "Asia/Shanghai"
    backend = (os.environ.get("AGENT_BACKEND") or env_values.get("AGENT_BACKEND") or "iflow").strip().lower()
    default_backend: RuntimeBackend = "claude" if backend == "claude" else "iflow"
    escaped_name = re.escape(assistant_name)
    return AppConfig(
        project_root=root,
        store_dir=root / "store",
        groups_dir=root / "groups",
        data_dir=root / "data",
        logs_dir=root / "logs",
        sender_allowlist_path=Path(
            os.environ.get("HOME", str(Path.home()))
        )
        / ".config"
        / "iflowclaw"
        / "sender-allowlist.json",
        assistant_name=assistant_name,
        feishu_app_id=os.environ.get("FEISHU_APP_ID")
        or env_values.get("FEISHU_APP_ID", ""),
        feishu_app_secret=os.environ.get("FEISHU_APP_SECRET")
        or env_values.get("FEISHU_APP_SECRET", ""),
        poll_interval_ms=2000,
        scheduler_poll_interval_ms=60000,
        ipc_poll_interval_ms=1000,
        agent_timeout_ms=int(os.environ.get("AGENT_TIMEOUT") or env_values.get("AGENT_TIMEOUT") or "300000"),
        idle_timeout_ms=int(os.environ.get("IDLE_TIMEOUT") or env_values.get("IDLE_TIMEOUT") or "180000"),
        max_concurrent_agents=max(
            1,
            int(
                os.environ.get("MAX_CONCURRENT_AGENTS")
                or env_values.get("MAX_CONCURRENT_AGENTS")
                or "5"
            ),
        ),
        timezone=timezone,
        default_backend=default_backend,
        iflow_model=os.environ.get("IFLOW_MODEL") or env_values.get("IFLOW_MODEL"),
        claude_model=os.environ.get("CLAUDE_MODEL") or env_values.get("CLAUDE_MODEL"),
        trigger_pattern=re.compile(rf"^@{escaped_name}\b", re.IGNORECASE),
    )

