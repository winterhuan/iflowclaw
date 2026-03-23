from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import AppConfig
from .group_folder import is_valid_group_folder
from .types import AgentConfig, AvailableGroup, ChatInfo, NewMessage, RegisteredGroup, ScheduledTask, TaskRunLog

_conn: sqlite3.Connection | None = None
_lock = threading.RLock()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _ensure_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Database not initialized")
    return _conn


def init_database(config: AppConfig, *, in_memory: bool = False) -> None:
    global _conn
    db_path = ":memory:" if in_memory else str((config.store_dir / "messages.db").resolve())
    if not in_memory:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    with _lock:
        _conn = conn
        _create_schema(conn)


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chats (
          jid TEXT PRIMARY KEY,
          name TEXT,
          last_message_time TEXT,
          channel TEXT,
          is_group INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT,
          chat_jid TEXT,
          sender TEXT,
          sender_name TEXT,
          content TEXT,
          timestamp TEXT,
          is_from_me INTEGER,
          is_bot_message INTEGER DEFAULT 0,
          PRIMARY KEY (id, chat_jid),
          FOREIGN KEY (chat_jid) REFERENCES chats(jid)
        );
        CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp);

        CREATE TABLE IF NOT EXISTS scheduled_tasks (
          id TEXT PRIMARY KEY,
          group_folder TEXT NOT NULL,
          chat_jid TEXT NOT NULL,
          prompt TEXT NOT NULL,
          schedule_type TEXT NOT NULL,
          schedule_value TEXT NOT NULL,
          context_mode TEXT DEFAULT 'isolated',
          next_run TEXT,
          last_run TEXT,
          last_result TEXT,
          status TEXT DEFAULT 'active',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_next_run ON scheduled_tasks(next_run);
        CREATE INDEX IF NOT EXISTS idx_status ON scheduled_tasks(status);

        CREATE TABLE IF NOT EXISTS task_run_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id TEXT NOT NULL,
          run_at TEXT NOT NULL,
          duration_ms INTEGER NOT NULL,
          status TEXT NOT NULL,
          result TEXT,
          error TEXT,
          FOREIGN KEY (task_id) REFERENCES scheduled_tasks(id)
        );
        CREATE INDEX IF NOT EXISTS idx_task_run_logs ON task_run_logs(task_id, run_at);

        CREATE TABLE IF NOT EXISTS router_state (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          group_folder TEXT PRIMARY KEY,
          session_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS registered_groups (
          jid TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          folder TEXT NOT NULL UNIQUE,
          trigger_pattern TEXT NOT NULL,
          added_at TEXT NOT NULL,
          agent_config TEXT,
          requires_trigger INTEGER DEFAULT 1,
          is_main INTEGER DEFAULT 0
        );
        """
    )


def store_chat_metadata(
    chat_jid: str,
    timestamp: str,
    *,
    name: str | None = None,
    channel: str | None = None,
    is_group: bool | None = None,
) -> None:
    conn = _ensure_conn()
    ch = channel
    grp = None if is_group is None else (1 if is_group else 0)

    with _lock:
        if name:
            conn.execute(
                """
                INSERT INTO chats (jid, name, last_message_time, channel, is_group)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(jid) DO UPDATE SET
                  name = excluded.name,
                  last_message_time = MAX(last_message_time, excluded.last_message_time),
                  channel = COALESCE(excluded.channel, channel),
                  is_group = COALESCE(excluded.is_group, is_group)
                """,
                (chat_jid, name, timestamp, ch, grp),
            )
        else:
            conn.execute(
                """
                INSERT INTO chats (jid, name, last_message_time, channel, is_group)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(jid) DO UPDATE SET
                  last_message_time = MAX(last_message_time, excluded.last_message_time),
                  channel = COALESCE(excluded.channel, channel),
                  is_group = COALESCE(excluded.is_group, is_group)
                """,
                (chat_jid, chat_jid, timestamp, ch, grp),
            )
        conn.commit()


def store_message(message: NewMessage) -> None:
    conn = _ensure_conn()
    with _lock:
        store_chat_metadata(
            message.chat_jid,
            message.timestamp,
            name=None,
            channel=_infer_channel_from_jid(message.chat_jid),
            is_group=_infer_is_group_from_jid(message.chat_jid),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO messages
              (id, chat_jid, sender, sender_name, content, timestamp, is_from_me, is_bot_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.id,
                message.chat_jid,
                message.sender,
                message.sender_name,
                message.content,
                message.timestamp,
                1 if message.is_from_me else 0,
                1 if message.is_bot_message else 0,
            ),
        )
        conn.commit()


def get_all_chats() -> list[ChatInfo]:
    conn = _ensure_conn()
    with _lock:
        rows = conn.execute(
            """
            SELECT jid, name, last_message_time, channel, is_group
            FROM chats
            ORDER BY last_message_time DESC
            """
        ).fetchall()
    return [
        ChatInfo(
            jid=row["jid"],
            name=row["name"],
            last_message_time=row["last_message_time"],
            channel=row["channel"],
            is_group=row["is_group"],
        )
        for row in rows
    ]


def get_available_groups(registered_groups: dict[str, RegisteredGroup]) -> list[AvailableGroup]:
    chats = get_all_chats()
    registered_jids = set(registered_groups.keys())
    return [
        AvailableGroup(
            jid=c.jid,
            name=c.name,
            last_activity=c.last_message_time,
            is_registered=c.jid in registered_jids,
        )
        for c in chats
        if c.jid != "__group_sync__" and c.is_group
    ]


def get_messages_since(chat_jid: str, since_timestamp: str, assistant_name: str) -> list[NewMessage]:
    conn = _ensure_conn()
    with _lock:
        rows = conn.execute(
            """
            SELECT id, chat_jid, sender, sender_name, content, timestamp, is_from_me, is_bot_message
            FROM messages
            WHERE chat_jid = ?
              AND timestamp > ?
            ORDER BY timestamp ASC
            """,
            (chat_jid, since_timestamp or ""),
        ).fetchall()
    return [
        NewMessage(
            id=row["id"],
            chat_jid=row["chat_jid"],
            sender=row["sender"],
            sender_name=row["sender_name"],
            content=_strip_legacy_bot_prefix(row["content"], assistant_name),
            timestamp=row["timestamp"],
            is_from_me=bool(row["is_from_me"]),
            is_bot_message=bool(row["is_bot_message"]),
        )
        for row in rows
    ]


def get_new_messages(since_timestamp: str, assistant_name: str, *, limit: int = 200) -> list[NewMessage]:
    conn = _ensure_conn()
    with _lock:
        rows = conn.execute(
            """
            SELECT id, chat_jid, sender, sender_name, content, timestamp, is_from_me, is_bot_message
            FROM messages
            WHERE timestamp > ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (since_timestamp or "", int(limit)),
        ).fetchall()
    return [
        NewMessage(
            id=row["id"],
            chat_jid=row["chat_jid"],
            sender=row["sender"],
            sender_name=row["sender_name"],
            content=_strip_legacy_bot_prefix(row["content"], assistant_name),
            timestamp=row["timestamp"],
            is_from_me=bool(row["is_from_me"]),
            is_bot_message=bool(row["is_bot_message"]),
        )
        for row in rows
    ]


def get_router_state(key: str) -> str | None:
    conn = _ensure_conn()
    with _lock:
        row = conn.execute("SELECT value FROM router_state WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def set_router_state(key: str, value: str) -> None:
    conn = _ensure_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO router_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()


def get_all_sessions() -> dict[str, str]:
    conn = _ensure_conn()
    with _lock:
        rows = conn.execute("SELECT group_folder, session_id FROM sessions").fetchall()
    return {str(r["group_folder"]): str(r["session_id"]) for r in rows}


def set_session(group_folder: str, session_id: str) -> None:
    conn = _ensure_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO sessions (group_folder, session_id) VALUES (?, ?)
            ON CONFLICT(group_folder) DO UPDATE SET session_id = excluded.session_id
            """,
            (group_folder, session_id),
        )
        conn.commit()


def get_all_registered_groups() -> dict[str, RegisteredGroup]:
    conn = _ensure_conn()
    with _lock:
        rows = conn.execute(
            """
            SELECT jid, name, folder, trigger_pattern, added_at, requires_trigger, is_main, agent_config
            FROM registered_groups
            """
        ).fetchall()
    groups: dict[str, RegisteredGroup] = {}
    for row in rows:
        agent_config = _decode_agent_config(row["agent_config"])
        groups[str(row["jid"])] = RegisteredGroup(
            name=str(row["name"]),
            folder=str(row["folder"]),
            trigger=str(row["trigger_pattern"]),
            added_at=str(row["added_at"]),
            requires_trigger=bool(row["requires_trigger"]) if row["requires_trigger"] is not None else True,
            is_main=bool(row["is_main"]) if row["is_main"] is not None else False,
            agent_config=agent_config,
        )
    return groups


def set_registered_group(jid: str, group: RegisteredGroup) -> None:
    conn = _ensure_conn()
    if not is_valid_group_folder(group.folder):
        raise ValueError(f"Invalid group folder: {group.folder}")
    with _lock:
        conn.execute(
            """
            INSERT INTO registered_groups
              (jid, name, folder, trigger_pattern, added_at,
               agent_config, requires_trigger, is_main)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(jid) DO UPDATE SET
              name = excluded.name,
              folder = excluded.folder,
              trigger_pattern = excluded.trigger_pattern,
              agent_config = excluded.agent_config,
              requires_trigger = excluded.requires_trigger,
              is_main = excluded.is_main
            """,
            (
                jid,
                group.name,
                group.folder,
                group.trigger,
                group.added_at,
                _encode_agent_config(group.agent_config),
                1 if (group.requires_trigger is None or group.requires_trigger) else 0,
                1 if group.is_main else 0,
            ),
        )
        conn.commit()


def create_task(
    *,
    group_folder: str,
    chat_jid: str,
    prompt: str,
    schedule_type: str,
    schedule_value: str,
    context_mode: str,
    next_run: str | None,
) -> ScheduledTask:
    task_id = str(uuid.uuid4())
    created_at = _utc_now_iso()
    conn = _ensure_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO scheduled_tasks
              (id, group_folder, chat_jid, prompt,
               schedule_type, schedule_value, context_mode,
               next_run, last_run, last_result, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'active', ?)
            """,
            (
                task_id,
                group_folder,
                chat_jid,
                prompt,
                schedule_type,
                schedule_value,
                context_mode,
                next_run,
                created_at,
            ),
        )
        conn.commit()
    return ScheduledTask(
        id=task_id,
        group_folder=group_folder,
        chat_jid=chat_jid,
        prompt=prompt,
        schedule_type=schedule_type,  # type: ignore[assignment]
        schedule_value=schedule_value,
        context_mode=context_mode,  # type: ignore[assignment]
        next_run=next_run,
        last_run=None,
        last_result=None,
        status="active",
        created_at=created_at,
    )


def list_tasks(group_folder: str | None = None) -> list[ScheduledTask]:
    conn = _ensure_conn()
    with _lock:
        if group_folder:
            rows = conn.execute(
                """
                SELECT id, group_folder, chat_jid, prompt, schedule_type, schedule_value, context_mode,
                       next_run, last_run, last_result, status, created_at
                FROM scheduled_tasks
                WHERE group_folder = ?
                ORDER BY created_at DESC
                """,
                (group_folder,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, group_folder, chat_jid, prompt, schedule_type, schedule_value, context_mode,
                       next_run, last_run, last_result, status, created_at
                FROM scheduled_tasks
                ORDER BY created_at DESC
                """
            ).fetchall()
    return [_row_to_task(r) for r in rows]


def get_due_tasks(now_iso: str) -> list[ScheduledTask]:
    conn = _ensure_conn()
    with _lock:
        rows = conn.execute(
            """
            SELECT id, group_folder, chat_jid, prompt, schedule_type, schedule_value, context_mode,
                   next_run, last_run, last_result, status, created_at
            FROM scheduled_tasks
            WHERE status = 'active'
              AND next_run IS NOT NULL
              AND next_run <= ?
            ORDER BY next_run ASC
            """,
            (now_iso,),
        ).fetchall()
    return [_row_to_task(r) for r in rows]


def set_task_status(task_id: str, status: str) -> None:
    conn = _ensure_conn()
    with _lock:
        conn.execute("UPDATE scheduled_tasks SET status = ? WHERE id = ?", (status, task_id))
        conn.commit()


def delete_task(task_id: str) -> None:
    conn = _ensure_conn()
    with _lock:
        conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        conn.commit()


def update_task(
    task_id: str,
    *,
    prompt: str | None = None,
    schedule_type: str | None = None,
    schedule_value: str | None = None,
    context_mode: str | None = None,
    next_run: str | None = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if prompt is not None:
        fields.append("prompt = ?")
        values.append(prompt)
    if schedule_type is not None:
        fields.append("schedule_type = ?")
        values.append(schedule_type)
    if schedule_value is not None:
        fields.append("schedule_value = ?")
        values.append(schedule_value)
    if context_mode is not None:
        fields.append("context_mode = ?")
        values.append(context_mode)
    if next_run is not None:
        fields.append("next_run = ?")
        values.append(next_run)
    if not fields:
        return
    values.append(task_id)
    conn = _ensure_conn()
    with _lock:
        conn.execute(f"UPDATE scheduled_tasks SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()


def update_task_after_run(
    task_id: str,
    *,
    last_run: str,
    last_result: str | None,
    next_run: str | None,
    status: str | None = None,
) -> None:
    conn = _ensure_conn()
    with _lock:
        if status:
            conn.execute(
                """
                UPDATE scheduled_tasks
                SET last_run = ?, last_result = ?, next_run = ?, status = ?
                WHERE id = ?
                """,
                (last_run, last_result, next_run, status, task_id),
            )
        else:
            conn.execute(
                """
                UPDATE scheduled_tasks
                SET last_run = ?, last_result = ?, next_run = ?
                WHERE id = ?
                """,
                (last_run, last_result, next_run, task_id),
            )
        conn.commit()


def log_task_run(entry: TaskRunLog) -> None:
    conn = _ensure_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO task_run_logs (task_id, run_at, duration_ms, status, result, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry.task_id,
                entry.run_at,
                int(entry.duration_ms),
                entry.status,
                entry.result,
                entry.error,
            ),
        )
        conn.commit()


def _row_to_task(row: sqlite3.Row) -> ScheduledTask:
    return ScheduledTask(
        id=str(row["id"]),
        group_folder=str(row["group_folder"]),
        chat_jid=str(row["chat_jid"]),
        prompt=str(row["prompt"]),
        schedule_type=str(row["schedule_type"]),  # type: ignore[assignment]
        schedule_value=str(row["schedule_value"]),
        context_mode=str(row["context_mode"]),  # type: ignore[assignment]
        next_run=None if row["next_run"] is None else str(row["next_run"]),
        last_run=None if row["last_run"] is None else str(row["last_run"]),
        last_result=None if row["last_result"] is None else str(row["last_result"]),
        status=str(row["status"]),  # type: ignore[assignment]
        created_at=str(row["created_at"]),
    )


def _encode_agent_config(cfg: AgentConfig | None) -> str | None:
    if cfg is None:
        return None
    return json.dumps(asdict(cfg), ensure_ascii=False)


def _decode_agent_config(raw: Any) -> AgentConfig | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return AgentConfig(
        timeout=data.get("timeout"),
        backend=data.get("backend"),
        model=data.get("model"),
        system_prompt=data.get("system_prompt"),
        metadata=data.get("metadata") or {},
    )


def _strip_legacy_bot_prefix(content: str, assistant_name: str) -> str:
    prefix = f"{assistant_name}:"
    if content.startswith(prefix):
        return content[len(prefix) :].lstrip()
    return content


def _infer_channel_from_jid(jid: str) -> str | None:
    if jid.startswith("feishu:"):
        return "feishu"
    if jid.startswith("tg:"):
        return "telegram"
    if jid.startswith("dc:"):
        return "discord"
    if "@g.us" in jid or "@s.whatsapp.net" in jid:
        return "whatsapp"
    return None


def _infer_is_group_from_jid(jid: str) -> bool | None:
    if jid.startswith("feishu:"):
        return True
    if jid.startswith("tg:"):
        return True
    if jid.startswith("dc:"):
        return True
    if "@g.us" in jid:
        return True
    if "@s.whatsapp.net" in jid:
        return False
    return None
