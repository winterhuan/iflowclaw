import Database from 'better-sqlite3';
import fs from 'fs';
import path from 'path';

import { ASSISTANT_NAME, DATA_DIR, STORE_DIR } from './config.js';
import { logger } from './logger.js';
import { NewMessage, RegisteredGroup, ScheduledTask, TaskRunLog } from './types.js';

let db: Database.Database;

function createSchema(database: Database.Database): void {
  database.exec(`
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
      PRIMARY KEY (id, chat_jid)
    );
    CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp);

    CREATE TABLE IF NOT EXISTS scheduled_tasks (
      id TEXT PRIMARY KEY,
      group_folder TEXT NOT NULL,
      chat_jid TEXT NOT NULL,
      prompt TEXT NOT NULL,
      schedule_type TEXT NOT NULL,
      schedule_value TEXT NOT NULL,
      next_run TEXT,
      last_run TEXT,
      last_result TEXT,
      status TEXT DEFAULT 'active',
      context_mode TEXT DEFAULT 'isolated',
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_next_run ON scheduled_tasks(next_run);

    CREATE TABLE IF NOT EXISTS task_run_logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      task_id TEXT NOT NULL,
      run_at TEXT NOT NULL,
      duration_ms INTEGER NOT NULL,
      status TEXT NOT NULL,
      result TEXT,
      error TEXT
    );

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
      container_config TEXT,
      requires_trigger INTEGER DEFAULT 1,
      is_main INTEGER DEFAULT 0
    );
  `);
}

export function initDatabase(): void {
  const dbPath = path.join(STORE_DIR, 'messages.db');
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  db = new Database(dbPath);
  createSchema(db);
}

export function _initTestDatabase(): void {
  db = new Database(':memory:');
  createSchema(db);
}

export function storeChatMetadata(
  chatJid: string,
  timestamp: string,
  name?: string,
  channel?: string,
  isGroup?: boolean,
): void {
  const ch = channel ?? null;
  const group = isGroup === undefined ? null : isGroup ? 1 : 0;

  if (name) {
    db.prepare(`
      INSERT INTO chats (jid, name, last_message_time, channel, is_group) VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(jid) DO UPDATE SET
        name = excluded.name,
        last_message_time = MAX(last_message_time, excluded.last_message_time),
        channel = COALESCE(excluded.channel, channel),
        is_group = COALESCE(excluded.is_group, is_group)
    `).run(chatJid, name, timestamp, ch, group);
  } else {
    db.prepare(`
      INSERT INTO chats (jid, name, last_message_time, channel, is_group) VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(jid) DO UPDATE SET
        last_message_time = MAX(last_message_time, excluded.last_message_time),
        channel = COALESCE(excluded.channel, channel),
        is_group = COALESCE(excluded.is_group, is_group)
    `).run(chatJid, chatJid, timestamp, ch, group);
  }
}

export function storeMessage(msg: NewMessage): void {
  db.prepare(`
    INSERT OR REPLACE INTO messages (id, chat_jid, sender, sender_name, content, timestamp, is_from_me, is_bot_message)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
  `).run(msg.id, msg.chat_jid, msg.sender, msg.sender_name, msg.content, msg.timestamp, msg.is_from_me ? 1 : 0, msg.is_bot_message ? 1 : 0);
}

export function getNewMessages(jids: string[], lastTimestamp: string, botPrefix: string): { messages: NewMessage[]; newTimestamp: string } {
  if (jids.length === 0) return { messages: [], newTimestamp: lastTimestamp };
  const placeholders = jids.map(() => '?').join(',');
  const rows = db.prepare(`
    SELECT id, chat_jid, sender, sender_name, content, timestamp, is_from_me
    FROM messages WHERE timestamp > ? AND chat_jid IN (${placeholders})
      AND is_bot_message = 0 AND content NOT LIKE ?
    ORDER BY timestamp
  `).all(lastTimestamp, ...jids, `${botPrefix}:%`) as NewMessage[];

  let newTimestamp = lastTimestamp;
  for (const row of rows) {
    if (row.timestamp > newTimestamp) newTimestamp = row.timestamp;
  }
  return { messages: rows, newTimestamp };
}

// Task functions
export function createTask(task: Omit<ScheduledTask, 'last_run' | 'last_result'>): void {
  db.prepare(`
    INSERT INTO scheduled_tasks (id, group_folder, chat_jid, prompt, schedule_type, schedule_value, context_mode, next_run, status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(task.id, task.group_folder, task.chat_jid, task.prompt, task.schedule_type, task.schedule_value, task.context_mode || 'isolated', task.next_run, task.status, task.created_at);
}

export function getTaskById(id: string): ScheduledTask | undefined {
  return db.prepare('SELECT * FROM scheduled_tasks WHERE id = ?').get(id) as ScheduledTask | undefined;
}

export function getAllTasks(): ScheduledTask[] {
  return db.prepare('SELECT * FROM scheduled_tasks ORDER BY created_at DESC').all() as ScheduledTask[];
}

export function getDueTasks(): ScheduledTask[] {
  const now = new Date().toISOString();
  return db.prepare(`SELECT * FROM scheduled_tasks WHERE status = 'active' AND next_run IS NOT NULL AND next_run <= ? ORDER BY next_run`).all(now) as ScheduledTask[];
}

export function updateTaskAfterRun(id: string, nextRun: string | null, lastResult: string): void {
  const now = new Date().toISOString();
  db.prepare(`UPDATE scheduled_tasks SET next_run = ?, last_run = ?, last_result = ?, status = CASE WHEN ? IS NULL THEN 'completed' ELSE status END WHERE id = ?`).run(nextRun, now, lastResult, nextRun, id);
}

export function deleteTask(id: string): void {
  db.prepare('DELETE FROM task_run_logs WHERE task_id = ?').run(id);
  db.prepare('DELETE FROM scheduled_tasks WHERE id = ?').run(id);
}

export function logTaskRun(log: TaskRunLog): void {
  db.prepare(`INSERT INTO task_run_logs (task_id, run_at, duration_ms, status, result, error) VALUES (?, ?, ?, ?, ?, ?)`).run(log.task_id, log.run_at, log.duration_ms, log.status, log.result, log.error);
}

// Router state
export function getRouterState(key: string): string | undefined {
  const row = db.prepare('SELECT value FROM router_state WHERE key = ?').get(key) as { value: string } | undefined;
  return row?.value;
}

export function setRouterState(key: string, value: string): void {
  db.prepare('INSERT OR REPLACE INTO router_state (key, value) VALUES (?, ?)').run(key, value);
}

// Session
export function getSession(groupFolder: string): string | undefined {
  const row = db.prepare('SELECT session_id FROM sessions WHERE group_folder = ?').get(groupFolder) as { session_id: string } | undefined;
  return row?.session_id;
}

export function setSession(groupFolder: string, sessionId: string): void {
  db.prepare('INSERT OR REPLACE INTO sessions (group_folder, session_id) VALUES (?, ?)').run(groupFolder, sessionId);
}

// Registered groups
export function getRegisteredGroup(jid: string): (RegisteredGroup & { jid: string }) | undefined {
  const row = db.prepare('SELECT * FROM registered_groups WHERE jid = ?').get(jid) as any;
  if (!row) return undefined;
  return {
    jid: row.jid,
    name: row.name,
    folder: row.folder,
    trigger: row.trigger_pattern,
    added_at: row.added_at,
    containerConfig: row.container_config ? JSON.parse(row.container_config) : undefined,
    requiresTrigger: row.requires_trigger === 1,
    isMain: row.is_main === 1,
  };
}

export function setRegisteredGroup(jid: string, group: RegisteredGroup): void {
  db.prepare(`INSERT OR REPLACE INTO registered_groups (jid, name, folder, trigger_pattern, added_at, container_config, requires_trigger, is_main) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`).run(
    jid, group.name, group.folder, group.trigger, group.added_at,
    group.containerConfig ? JSON.stringify(group.containerConfig) : null,
    group.requiresTrigger === false ? 0 : 1,
    group.isMain ? 1 : 0
  );
}

export function getAllRegisteredGroups(): Record<string, RegisteredGroup> {
  const rows = db.prepare('SELECT * FROM registered_groups').all() as any[];
  const result: Record<string, RegisteredGroup> = {};
  for (const row of rows) {
    result[row.jid] = {
      name: row.name,
      folder: row.folder,
      trigger: row.trigger_pattern,
      added_at: row.added_at,
      containerConfig: row.container_config ? JSON.parse(row.container_config) : undefined,
      requiresTrigger: row.requires_trigger === 1,
      isMain: row.is_main === 1,
    };
  }
  return result;
}

export interface ChatInfo {
  jid: string;
  name: string;
  last_message_time: string;
  channel: string;
  is_group: number;
}

export function getAllChats(): ChatInfo[] {
  return db.prepare('SELECT jid, name, last_message_time, channel, is_group FROM chats ORDER BY last_message_time DESC').all() as ChatInfo[];
}
