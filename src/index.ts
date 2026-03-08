/**
 * iFlowClaw - Main Orchestrator
 * Personal AI assistant using iFlow platform with container isolation
 */
import fs from 'fs';
import path from 'path';
import { ChildProcess } from 'child_process';

import {
  ASSISTANT_NAME,
  GROUPS_DIR,
  POLL_INTERVAL,
  SCHEDULER_POLL_INTERVAL,
  MAX_CONCURRENT_CONTAINERS,
  TRIGGER_PATTERN,
} from './config.js';
import {
  initDatabase,
  getNewMessages,
  getRouterState,
  setRouterState,
  getSession,
  setSession,
  getAllRegisteredGroups,
  getRegisteredGroup,
  setRegisteredGroup,
  storeChatMetadata,
  getDueTasks,
  updateTaskAfterRun,
  logTaskRun,
} from './db.js';
import { logger } from './logger.js';
import { runContainerAgent, ContainerOutput, ContainerInput } from './container-runner.js';
import { Channel, NewMessage, OnInboundMessage, OnChatMetadata, RegisteredGroup } from './types.js';

// Channel registry
const channels: Channel[] = [];
const activeContainers = new Map<string, { process: ChildProcess; containerName: string }>();

export function registerChannel(factory: () => Channel | null): void {
  const channel = factory();
  if (channel) {
    channels.push(channel);
    logger.info({ channel: channel.name }, 'Channel registered');
  }
}

async function connectChannels(): Promise<void> {
  for (const channel of channels) {
    try {
      await channel.connect();
      logger.info({ channel: channel.name }, 'Channel connected');
    } catch (err) {
      logger.error({ channel: channel.name, err }, 'Failed to connect channel');
    }
  }
}

function findChannelForJid(jid: string): Channel | undefined {
  return channels.find(c => c.ownsJid(jid));
}

async function sendToChannel(jid: string, text: string): Promise<void> {
  const channel = findChannelForJid(jid);
  if (!channel) {
    logger.warn({ jid }, 'No channel found for JID');
    return;
  }
  await channel.sendMessage(jid, text);
}

async function handleInboundMessage(chatJid: string, message: NewMessage): Promise<void> {
  // Store message
  storeChatMetadata(chatJid, message.timestamp, undefined, undefined, undefined);
  
  // Check if group is registered
  const group = getRegisteredGroup(chatJid);
  if (!group) {
    logger.debug({ chatJid }, 'Message from unregistered group, ignoring');
    return;
  }

  // Check trigger
  const content = message.content.trim();
  const shouldRespond = !group.requiresTrigger || TRIGGER_PATTERN.test(content);
  if (!shouldRespond) {
    logger.debug({ chatJid }, 'No trigger, ignoring');
    return;
  }

  // Remove trigger from content
  const prompt = group.requiresTrigger ? content.replace(TRIGGER_PATTERN, '').trim() : content;
  if (!prompt) {
    logger.debug({ chatJid }, 'Empty prompt after trigger removal');
    return;
  }

  // Run agent in container
  const input: ContainerInput = {
    prompt,
    sessionId: getSession(group.folder),
    groupFolder: group.folder,
    chatJid,
    isMain: group.isMain || false,
    assistantName: ASSISTANT_NAME,
  };

  const onProcess = (proc: ChildProcess, containerName: string) => {
    activeContainers.set(chatJid, { process: proc, containerName });
  };

  const onOutput = async (output: ContainerOutput) => {
    if (output.result) {
      await sendToChannel(chatJid, output.result);
    }
    if (output.newSessionId) {
      setSession(group.folder, output.newSessionId);
    }
  };

  try {
    const result = await runContainerAgent(group, input, onProcess, onOutput);
    if (result.error) {
      logger.error({ chatJid, error: result.error }, 'Agent error');
      await sendToChannel(chatJid, `Error: ${result.error}`);
    }
  } finally {
    activeContainers.delete(chatJid);
  }
}

async function handleScheduledTasks(): Promise<void> {
  const dueTasks = getDueTasks();
  
  for (const task of dueTasks) {
    const group = getRegisteredGroup(task.chat_jid);
    if (!group) {
      logger.warn({ taskId: task.id }, 'Task for unregistered group');
      continue;
    }

    const startTime = Date.now();
    const input: ContainerInput = {
      prompt: task.prompt,
      sessionId: getSession(group.folder),
      groupFolder: group.folder,
      chatJid: task.chat_jid,
      isMain: group.isMain || false,
      isScheduledTask: true,
      assistantName: ASSISTANT_NAME,
    };

    try {
      const result = await runContainerAgent(group, input, () => {}, async (output) => {
        if (output.newSessionId) {
          setSession(group.folder, output.newSessionId);
        }
      });

      const duration = Date.now() - startTime;
      logTaskRun({
        task_id: task.id,
        run_at: new Date().toISOString(),
        duration_ms: duration,
        status: result.status,
        result: result.result,
        error: result.error || null,
      });

      // Calculate next run
      let nextRun: string | null = null;
      if (task.schedule_type === 'interval') {
        const intervalMs = parseInt(task.schedule_value, 10);
        nextRun = new Date(Date.now() + intervalMs).toISOString();
      } else if (task.schedule_type === 'cron') {
        // Simple next run calculation (would need cron-parser for full support)
        nextRun = new Date(Date.now() + 60000).toISOString();
      }
      // 'once' tasks get nextRun = null, marking them completed

      updateTaskAfterRun(task.id, nextRun, result.result || result.error || '');
    } catch (err) {
      logger.error({ taskId: task.id, err }, 'Scheduled task failed');
    }
  }
}

async function messageLoop(): Promise<void> {
  const groups = getAllRegisteredGroups();
  const jids = Object.keys(groups);
  
  if (jids.length === 0) {
    return;
  }

  const lastTimestamp = getRouterState('last_timestamp') || '';
  const { messages, newTimestamp } = getNewMessages(jids, lastTimestamp, ASSISTANT_NAME);

  for (const message of messages) {
    await handleInboundMessage(message.chat_jid, message);
  }

  if (newTimestamp !== lastTimestamp) {
    setRouterState('last_timestamp', newTimestamp);
  }
}

async function main(): Promise<void> {
  logger.info({ assistant: ASSISTANT_NAME }, 'Starting iFlowClaw');

  // Initialize database
  initDatabase();

  // Ensure main group exists
  const mainGroup = getRegisteredGroup('main');
  if (!mainGroup) {
    setRegisteredGroup('main', {
      name: 'Main Control',
      folder: 'main',
      trigger: '',
      added_at: new Date().toISOString(),
      isMain: true,
      requiresTrigger: false,
    });
    logger.info('Created main control group');
  }

  // Ensure group directories exist
  fs.mkdirSync(path.join(GROUPS_DIR, 'main'), { recursive: true });
  fs.mkdirSync(path.join(GROUPS_DIR, 'global'), { recursive: true });

  // Connect channels
  await connectChannels();

  // Start message loop
  logger.info('Starting message loop');
  setInterval(messageLoop, POLL_INTERVAL);

  // Start scheduler loop
  setInterval(handleScheduledTasks, SCHEDULER_POLL_INTERVAL);

  // Keep process alive
  process.on('SIGINT', () => {
    logger.info('Shutting down...');
    process.exit(0);
  });
}

main().catch(err => {
  logger.fatal({ err }, 'Fatal error');
  process.exit(1);
});
