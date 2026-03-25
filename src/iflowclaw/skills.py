"""Skills sync - 将项目 skills/ 同步到各 backend 标准目录

各 backend 的 skills 目录:
- Claude: .claude/skills/ (SDK 自动发现)
- iFlow: .iflow/skills/ (CLI 自动加载)
- Agno: LocalSkills(path) 显式传入

同步时对 .md 文件做模板变量替换:
- {{GROUP_DIR}} -> 群组目录路径
- {{GLOBAL_DIR}} -> 全局目录路径
- {{IPC_DIR}} -> IPC 目录路径
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .logging import get_logger

logger = get_logger(__name__)

# 项目级 skills 源目录名
SKILLS_SOURCE_DIR = "skills"


def get_skills_source_dir(project_root: Path) -> Path:
    """获取项目 skills 源目录"""
    return (project_root / SKILLS_SOURCE_DIR).resolve()


def sync_skills_to_claude(
    project_root: Path,
    target_dir: Path,
    *,
    group_dir: str,
    global_dir: str,
    ipc_dir: str,
    project_dir: str,
) -> Path:
    """同步 skills 到 .claude/skills/ 目录 (Claude Agent SDK)"""
    src = get_skills_source_dir(project_root)
    dst = target_dir / ".claude" / "skills"
    _sync_directory(src, dst, group_dir=group_dir, global_dir=global_dir, ipc_dir=ipc_dir, project_dir=project_dir)
    return dst


def sync_skills_to_iflow(
    project_root: Path,
    target_dir: Path,
    *,
    group_dir: str,
    global_dir: str,
    ipc_dir: str,
    project_dir: str,
) -> Path:
    """同步 skills 到 .iflow/skills/ 目录 (iFlow CLI)"""
    src = get_skills_source_dir(project_root)
    dst = target_dir / ".iflow" / "skills"
    _sync_directory(src, dst, group_dir=group_dir, global_dir=global_dir, ipc_dir=ipc_dir, project_dir=project_dir)
    return dst


def get_skills_path_for_agno(
    project_root: Path,
    target_dir: Path,
    *,
    group_dir: str,
    global_dir: str,
    ipc_dir: str,
    project_dir: str,
) -> Path:
    """获取 Agno backend 的 skills 路径"""
    src = get_skills_source_dir(project_root)
    dst = target_dir / "skills"
    _sync_directory(src, dst, group_dir=group_dir, global_dir=global_dir, ipc_dir=ipc_dir, project_dir=project_dir)
    return dst


def sync_skills_for_backend(
    backend: str,
    project_root: Path,
    target_dir: Path,
    *,
    group_dir: str,
    global_dir: str,
    ipc_dir: str,
    project_dir: str,
) -> Path | None:
    """根据 backend 类型同步 skills

    Args:
        backend: backend 名称 (claude/iflow/agno)
        project_root: 项目根目录
        target_dir: 目标根目录
        group_dir: 群组目录路径 (替换 {{GROUP_DIR}})
        global_dir: 全局目录路径 (替换 {{GLOBAL_DIR}})
        ipc_dir: IPC 目录路径 (替换 {{IPC_DIR}})
        project_dir: 项目目录路径 (替换 {{PROJECT_DIR}})

    Returns:
        同步后的 skills 路径
    """
    src = get_skills_source_dir(project_root)
    if not src.is_dir():
        logger.debug("skills: source directory not found: %s", src)
        return None

    kwargs = dict(group_dir=group_dir, global_dir=global_dir, ipc_dir=ipc_dir, project_dir=project_dir)

    if backend == "claude":
        return sync_skills_to_claude(project_root, target_dir, **kwargs)
    elif backend == "iflow":
        return sync_skills_to_iflow(project_root, target_dir, **kwargs)
    elif backend == "agno":
        return get_skills_path_for_agno(project_root, target_dir, **kwargs)
    else:
        logger.warning("skills: unknown backend '%s', skipping sync", backend)
        return None


def _sync_directory(
    src: Path,
    dst: Path,
    *,
    group_dir: str,
    global_dir: str,
    ipc_dir: str,
    project_dir: str,
) -> None:
    """同步目录内容，对 .md 文件做模板替换"""
    if not src.is_dir():
        return

    dst.mkdir(parents=True, exist_ok=True)

    for item in src.iterdir():
        if not item.is_dir():
            continue
        src_sub = item
        dst_sub = dst / item.name
        try:
            if dst_sub.exists():
                shutil.rmtree(dst_sub)
            shutil.copytree(src_sub, dst_sub)
            # 对 .md 文件做模板替换
            _apply_templates(dst_sub, group_dir=group_dir, global_dir=global_dir, ipc_dir=ipc_dir, project_dir=project_dir)
        except Exception as e:
            logger.warning("skills: failed to sync %s -> %s: %s", src_sub, dst_sub, e)


def _apply_templates(
    dir_path: Path,
    *,
    group_dir: str,
    global_dir: str,
    ipc_dir: str,
    project_dir: str,
) -> None:
    """对目录内所有 .md 文件做模板变量替换"""
    replacements = {
        "{{GROUP_DIR}}": group_dir,
        "{{GLOBAL_DIR}}": global_dir,
        "{{IPC_DIR}}": ipc_dir,
        "{{PROJECT_DIR}}": project_dir,
    }
    for md_file in dir_path.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            for placeholder, value in replacements.items():
                content = content.replace(placeholder, value)
            md_file.write_text(content, encoding="utf-8")
        except Exception as e:
            logger.warning("skills: failed to apply templates in %s: %s", md_file, e)
