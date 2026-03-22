from __future__ import annotations

from pathlib import Path


def read_env_file(keys: list[str], project_root: Path) -> dict[str, str]:
    env_file = project_root / ".env"
    try:
        content = env_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}

    wanted = set(keys)
    result: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in wanted:
            continue
        value = value.strip().strip("\"'")
        if value:
            result[key] = value
    return result

