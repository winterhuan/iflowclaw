from __future__ import annotations

from pathlib import Path

from ..config import AppConfig
from ..group_folder import resolve_group_folder_path, resolve_group_ipc_path


def _process_agents_markdown(content: str, *, group_dir: Path, global_dir: Path, ipc_dir: Path) -> str:
    return (
        content.replace("{{GROUP_DIR}}", str(group_dir))
        .replace("{{GLOBAL_DIR}}", str(global_dir))
        .replace("{{IPC_DIR}}", str(ipc_dir))
    )


def build_system_prompt(config: AppConfig, *, group_folder: str, is_main: bool) -> str | None:
    group_dir = resolve_group_folder_path(config, group_folder)
    global_dir = (config.groups_dir / "global").resolve()
    ipc_dir = resolve_group_ipc_path(config, group_folder)

    parts: list[str] = []

    group_agents = group_dir / "AGENTS.md"
    if group_agents.exists():
        parts.append(
            _process_agents_markdown(
                group_agents.read_text(encoding="utf-8"),
                group_dir=group_dir,
                global_dir=global_dir,
                ipc_dir=ipc_dir,
            )
        )

    if not is_main:
        global_agents = global_dir / "AGENTS.md"
        if global_agents.exists():
            parts.append("")
            parts.append("---")
            parts.append(
                _process_agents_markdown(
                    global_agents.read_text(encoding="utf-8"),
                    group_dir=group_dir,
                    global_dir=global_dir,
                    ipc_dir=ipc_dir,
                )
            )

    if not parts:
        return None
    return "\n".join(parts)
