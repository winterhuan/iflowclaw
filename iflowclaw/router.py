from __future__ import annotations

from zoneinfo import ZoneInfo
from datetime import datetime

from .types import Channel, NewMessage


def escape_xml(text: str) -> str:
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def format_local_time(timestamp: str, timezone: str) -> str:
    value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return value.astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M:%S")


def format_messages(messages: list[NewMessage], timezone: str) -> str:
    lines = [
        f'<message sender="{escape_xml(message.sender_name)}" '
        f'time="{escape_xml(format_local_time(message.timestamp, timezone))}">'
        f"{escape_xml(message.content)}</message>"
        for message in messages
    ]
    return f'<context timezone="{escape_xml(timezone)}" />\n<messages>\n' + "\n".join(lines) + "\n</messages>"


def strip_internal_tags(text: str) -> str:
    import re

    return re.sub(r"<internal>[\s\S]*?</internal>", "", text).strip()


def format_outbound(raw_text: str) -> str:
    return strip_internal_tags(raw_text)


def find_channel(channels: list[Channel], jid: str) -> Channel | None:
    for channel in channels:
        if channel.owns_jid(jid):
            return channel
    return None

