from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BLOCKED_PATTERNS = [
    ".ssh",
    ".gnupg",
    ".gpg",
    ".aws",
    ".azure",
    ".gcloud",
    ".kube",
    ".docker",
    "credentials",
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "id_rsa",
    "id_ed25519",
    "private_key",
    ".secret",
]

_cached_allowlist: dict[str, Any] | None = None
_allowlist_load_error: str | None = None


def _default_allowlist_path() -> Path:
    return Path.home() / ".config" / "iflowclaw" / "mount-allowlist.json"


def load_mount_allowlist(path: Path | None = None) -> dict[str, Any] | None:
    global _cached_allowlist, _allowlist_load_error  # noqa: PLW0603

    if _cached_allowlist is not None:
        return _cached_allowlist
    if _allowlist_load_error is not None:
        return None

    allowlist_path = path or _default_allowlist_path()

    try:
        if not allowlist_path.exists():
            _allowlist_load_error = f"Mount allowlist not found at {allowlist_path}"
            logger.warning(
                "Mount allowlist not found at %s - additional mounts will be BLOCKED",
                allowlist_path,
            )
            return None

        content = allowlist_path.read_text(encoding="utf-8")
        allowlist = json.loads(content)

        if not isinstance(allowlist.get("allowedRoots"), list):
            raise ValueError("allowedRoots must be an array")
        if not isinstance(allowlist.get("blockedPatterns"), list):
            raise ValueError("blockedPatterns must be an array")
        if not isinstance(allowlist.get("nonMainReadOnly"), bool):
            raise ValueError("nonMainReadOnly must be a boolean")

        merged = list(set(DEFAULT_BLOCKED_PATTERNS + allowlist["blockedPatterns"]))
        allowlist["blockedPatterns"] = merged

        _cached_allowlist = allowlist
        logger.info(
            "Mount allowlist loaded: %d roots, %d blocked patterns",
            len(allowlist["allowedRoots"]),
            len(allowlist["blockedPatterns"]),
        )
        return _cached_allowlist
    except Exception as e:
        _allowlist_load_error = str(e)
        logger.error("Failed to load mount allowlist: %s", e)
        return None


def _expand_path(p: str) -> str:
    if p.startswith("~/"):
        return str(Path.home() / p[2:])
    if p == "~":
        return str(Path.home())
    return str(Path(p).resolve())


def _get_real_path(p: str) -> str | None:
    try:
        return str(Path(p).resolve())
    except Exception:
        return None


def _matches_blocked_pattern(real_path: str, blocked_patterns: list[str]) -> str | None:
    parts = real_path.split(os.sep)
    for pattern in blocked_patterns:
        for part in parts:
            if part == pattern or part.startswith(pattern + "."):
                return pattern
    return None


def _find_allowed_root(real_path: str, allowed_roots: list[dict[str, Any]]) -> dict[str, Any] | None:
    for root in allowed_roots:
        expanded = _expand_path(root["path"])
        real_root = _get_real_path(expanded)
        if real_root is None:
            continue
        try:
            Path(real_path).resolve().relative_to(Path(real_root))
            return root
        except ValueError:
            continue
    return None


def _is_valid_container_path(container_path: str) -> bool:
    if ".." in container_path:
        return False
    if container_path.startswith("/"):
        return False
    if not container_path or not container_path.strip():
        return False
    return True


@dataclass(frozen=True, slots=True)
class MountValidationResult:
    allowed: bool
    reason: str
    real_host_path: str | None = None
    resolved_container_path: str | None = None
    effective_readonly: bool = True


def validate_mount(
    mount_host_path: str, mount_container_path: str | None, mount_readonly: bool, is_main: bool
) -> MountValidationResult:
    allowlist = load_mount_allowlist()
    if allowlist is None:
        return MountValidationResult(allowed=False, reason="No mount allowlist configured")

    container_path = mount_container_path or Path(mount_host_path).name
    if not _is_valid_container_path(container_path):
        return MountValidationResult(allowed=False, reason=f"Invalid container path: {container_path}")

    expanded = _expand_path(mount_host_path)
    real_path = _get_real_path(expanded)
    if real_path is None:
        return MountValidationResult(allowed=False, reason=f"Host path does not exist: {mount_host_path}")

    blocked = _matches_blocked_pattern(real_path, allowlist["blockedPatterns"])
    if blocked is not None:
        return MountValidationResult(allowed=False, reason=f"Path matches blocked pattern '{blocked}': {real_path}")

    root = _find_allowed_root(real_path, allowlist["allowedRoots"])
    if root is None:
        return MountValidationResult(allowed=False, reason=f"Path not under any allowed root: {real_path}")

    effective_readonly = True
    if not mount_readonly:
        if not is_main and allowlist.get("nonMainReadOnly", True):
            effective_readonly = True
        elif not root.get("allowReadWrite", False):
            effective_readonly = True
        else:
            effective_readonly = False

    return MountValidationResult(
        allowed=True,
        reason=f"Allowed under root '{root['path']}'",
        real_host_path=real_path,
        resolved_container_path=container_path,
        effective_readonly=effective_readonly,
    )


def validate_additional_mounts(
    mounts: list[dict[str, Any]],
    group_name: str,
    is_main: bool,
) -> list[tuple[str, str, bool]]:
    validated: list[tuple[str, str, bool]] = []
    for mount in mounts:
        host_path = mount.get("hostPath") or mount.get("host_path", "")
        container_path = mount.get("containerPath") or mount.get("container_path")
        readonly = mount.get("readonly", True)
        result = validate_mount(host_path, container_path, readonly, is_main)
        if result.allowed and result.real_host_path and result.resolved_container_path:
            validated.append(
                (
                    result.real_host_path,
                    f"/workspace/extra/{result.resolved_container_path}",
                    result.effective_readonly,
                )
            )
        else:
            logger.warning("Additional mount REJECTED for %s: %s", group_name, result.reason)
    return validated
