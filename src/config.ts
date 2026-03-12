import os from 'os';
import path from 'path';

import { readEnvFile } from './env.js';

// Read config values from .env (falls back to process.env).
const envConfig = readEnvFile([
  'ASSISTANT_NAME',
  'FEISHU_APP_ID',
  'FEISHU_APP_SECRET',
  'IFLOW_BASE_URL',
  'TZ',
  'AGENT_TIMEOUT',
  'IDLE_TIMEOUT',
  'MAX_CONCURRENT_AGENTS',
  'EMBEDDING_API_KEY',
  'EMBEDDING_BASE_URL',
  'EMBEDDING_MODEL',
]);

export const ASSISTANT_NAME =
  process.env.ASSISTANT_NAME || envConfig.ASSISTANT_NAME || 'iFlow';

// Feishu configuration
export const FEISHU_APP_ID =
  process.env.FEISHU_APP_ID || envConfig.FEISHU_APP_ID || '';
export const FEISHU_APP_SECRET =
  process.env.FEISHU_APP_SECRET || envConfig.FEISHU_APP_SECRET || '';
export const POLL_INTERVAL = 2000;
export const SCHEDULER_POLL_INTERVAL = 60000;
export const IPC_POLL_INTERVAL = 1000;

// Absolute paths
const PROJECT_ROOT = process.cwd();
const HOME_DIR = process.env.HOME || os.homedir();

// Allowlist paths
export const SENDER_ALLOWLIST_PATH = path.join(
  HOME_DIR,
  '.config',
  'iflowclaw',
  'sender-allowlist.json',
);
export const STORE_DIR = path.resolve(PROJECT_ROOT, 'store');
export const GROUPS_DIR = path.resolve(PROJECT_ROOT, 'groups');
export const DATA_DIR = path.resolve(PROJECT_ROOT, 'data');

// Agent timeout (how long to wait for agent response)
export const AGENT_TIMEOUT = parseInt(
  process.env.AGENT_TIMEOUT || '300000',
  10,
); // 5min default
export const IDLE_TIMEOUT = parseInt(process.env.IDLE_TIMEOUT || '180000', 10); // 3min default
export const MAX_CONCURRENT_AGENTS = Math.max(
  1,
  parseInt(process.env.MAX_CONCURRENT_AGENTS || '5', 10) || 5,
);

function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export const TRIGGER_PATTERN = new RegExp(
  `^@${escapeRegex(ASSISTANT_NAME)}\\b`,
  'i',
);

// Timezone for scheduled tasks
export const TIMEZONE =
  process.env.TZ || Intl.DateTimeFormat().resolvedOptions().timeZone;

// iFlow API configuration
export const IFLOW_BASE_URL = process.env.IFLOW_BASE_URL || 'https://apis.iflow.cn/v1';

// Embedding configuration (for semantic memory)
export const EMBEDDING_API_KEY =
  process.env.EMBEDDING_API_KEY || envConfig.EMBEDDING_API_KEY || '';
export const EMBEDDING_BASE_URL =
  process.env.EMBEDDING_BASE_URL ||
  envConfig.EMBEDDING_BASE_URL ||
  'https://integrate.api.nvidia.com/v1';
export const EMBEDDING_MODEL =
  process.env.EMBEDDING_MODEL || envConfig.EMBEDDING_MODEL || 'baai/bge-m3';