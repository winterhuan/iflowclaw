from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ChatAllowlistEntry:
    allow: str | list[str] = "*"
    mode: str = "trigger"


@dataclass(slots=True)
class SenderAllowlistConfig:
    default: ChatAllowlistEntry = field(
        default_factory=lambda: ChatAllowlistEntry(allow="*", mode="trigger")
    )
    chats: dict[str, ChatAllowlistEntry] = field(default_factory=dict)
    log_denied: bool = True


def load_sender_allowlist(path: Path) -> SenderAllowlistConfig:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return SenderAllowlistConfig()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return SenderAllowlistConfig()

    default = parsed.get("default") or {}
    chats = {}
    for jid, value in (parsed.get("chats") or {}).items():
        chats[jid] = ChatAllowlistEntry(
            allow=value.get("allow", "*"),
            mode=value.get("mode", "trigger"),
        )
    return SenderAllowlistConfig(
        default=ChatAllowlistEntry(
            allow=default.get("allow", "*"),
            mode=default.get("mode", "trigger"),
        ),
        chats=chats,
        log_denied=parsed.get("logDenied", True),
    )


def _get_entry(chat_jid: str, config: SenderAllowlistConfig) -> ChatAllowlistEntry:
    return config.chats.get(chat_jid, config.default)


def is_sender_allowed(chat_jid: str, sender: str, config: SenderAllowlistConfig) -> bool:
    entry = _get_entry(chat_jid, config)
    return entry.allow == "*" or sender in entry.allow


def should_drop_message(chat_jid: str, config: SenderAllowlistConfig) -> bool:
    return _get_entry(chat_jid, config).mode == "drop"


def is_trigger_allowed(chat_jid: str, sender: str, config: SenderAllowlistConfig) -> bool:
    return is_sender_allowed(chat_jid, sender, config)

