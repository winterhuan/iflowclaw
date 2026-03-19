import os from 'os';
import path from 'path';

import { readEnvFile } from './env.js';

// Read config values from .env (falls back to process.env).
const envConfig = readEnvFile([
  'ASSISTANT_NAME',
  'FEISHU_APP_ID',
  'FEISHU_APP_SECRET',
  'TZ',
  'AGENT_TIMEOUT',
  'IDLE_TIMEOUT',
  'MAX_CONCURRENT_AGENTS',
  // Note: EMBEDDING_* vars removed - using Claude-Mem instead
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
export const MOUNT_ALLOWLIST_PATH = path.join(
  HOME_DIR,
  '.config',
  'iflowclaw',
  'mount-allowlist.json',
);
export const STORE_DIR = path.resolve(PROJECT_ROOT, 'store');
export const GROUPS_DIR = path.resolve(PROJECT_ROOT, 'groups');
export const DATA_DIR = path.resolve(PROJECT_ROOT, 'data');

// Container configuration
export const CONTAINER_IMAGE =
  process.env.IFLOW_CONTAINER_IMAGE || 'iflow-agent:latest';
export const CONTAINER_TIMEOUT = parseInt(
  process.env.IFLOW_CONTAINER_TIMEOUT || '1800000',
  10,
); // 30min default
export const CONTAINER_MAX_OUTPUT_SIZE = parseInt(
  process.env.IFLOW_CONTAINER_MAX_OUTPUT_SIZE || '10485760',
  10,
); // 10MB default

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

export const TRIGGER_PATTERN = new RegExp(
  `^@${ASSISTANT_NAME.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`,
  'i',
);

// Timezone for scheduled tasks
export const TIMEZONE =
  process.env.TZ || Intl.DateTimeFormat().resolvedOptions().timeZone;

// Note: Embedding configuration removed - using Claude-Mem for semantic search
