from __future__ import annotations

from pathlib import Path

from .config import AppConfig

GROUP_FOLDER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
RESERVED_FOLDERS = {"global"}


def is_valid_group_folder(folder: str) -> bool:
    import re

    if not folder or folder != folder.strip():
        return False
    if folder.lower() in RESERVED_FOLDERS:
        return False
    if "/" in folder or "\\" in folder or ".." in folder:
        return False
    return re.match(GROUP_FOLDER_PATTERN, folder) is not None


def assert_valid_group_folder(folder: str) -> None:
    if not is_valid_group_folder(folder):
        raise ValueError(f'Invalid group folder "{folder}"')


def _ensure_within(base_dir: Path, resolved: Path) -> None:
    resolved.relative_to(base_dir)


def resolve_group_folder_path(config: AppConfig, folder: str) -> Path:
    assert_valid_group_folder(folder)
    path = (config.groups_dir / folder).resolve()
    _ensure_within(config.groups_dir.resolve(), path)
    return path


def resolve_group_ipc_path(config: AppConfig, folder: str) -> Path:
    assert_valid_group_folder(folder)
    base_dir = (config.data_dir / "ipc").resolve()
    path = (base_dir / folder).resolve()
    _ensure_within(base_dir, path)
    return path

