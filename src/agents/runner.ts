/**
 * Agent Runner - Direct iFlow SDK Integration
 * Runs agent execution directly in the host process using iFlow SDK
 *
 * Authentication:
 * - OAuth: Automatically uses credentials from ~/.iflow/settings.json
 *   Run `iflow login` on the host to authenticate
 */
import fs from 'fs';
import path from 'path';
import { IFlowClient } from '@iflow-ai/iflow-cli-sdk';


import { logger } from '../logger.js';

function log(message: string): void {
  logger.info(`[agent] ${message}`);
}

import { resolveGroupFolderPath, resolveGroupIpcPath } from '../group-folder.js';
import { RegisteredGroup } from '../types.js';
import {
  AgentInput,
  AgentOutput,
  buildIFlowOptions as buildSharedIFlowOptions,
  drainIpcInput,
  executeCustomHook,
  runAgentLoop
} from './common.js';

// Group-level client cache for persistent connections
interface CachedClient {
  client: IFlowClient;
  sessionId: string;
  lastUsedAt: number;
  isActive: boolean;
}

const groupClients = new Map<string, CachedClient>();

/**
 * Get or create cached client for a group
 */
async function getOrCreateGroupClient(
  groupFolder: string,
  options: any,
): Promise<{ client: IFlowClient; isReused: boolean }> {
  // Kill any existing MCP processes for this group to prevent leaks
  // Use precise matching with IFLOWCLAW_GROUP_FOLDER= to avoid killing other groups' processes
  try {
    const { execSync } = await import('child_process');
    // Match the exact environment variable pattern: IFLOWCLAW_GROUP_FOLDER=groupFolder
    const safeGroupFolder = groupFolder.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    execSync(`pkill -f "IFLOWCLAW_GROUP_FOLDER=${safeGroupFolder}" 2>/dev/null || true`);
  } catch {}

  const cached = groupClients.get(groupFolder);

  // Check if we have a valid cached client
  if (cached && cached.isActive) {
    log(`Reusing cached client for group: ${groupFolder}`);
    cached.lastUsedAt = Date.now();
    return { client: cached.client, isReused: true };
  }

  // Create new client
  log(`Creating new client for group: ${groupFolder}`);
  const client = new IFlowClient(options);

  try {
    await client.connect();
    const sessionId = client.getSessionId();

    if (!sessionId) {
      throw new Error('Failed to obtain session ID');
    }

    // Cache the client
    groupClients.set(groupFolder, {
      client,
      sessionId,
      lastUsedAt: Date.now(),
      isActive: true,
    });

    log(`New client created and cached, sessionId: ${sessionId}`);

    // Execute SessionStart hook (new session created) with matcher 'startup'
    await executeCustomHook('SessionStart', { sessionId, matcher: 'startup' });

    return { client, isReused: false };
  } catch (err) {
    // Clean up on error
    try {
      await client.disconnect();
    } catch {}
    throw err;
  }
}

/**
 * Mark client as inactive (on error) and execute SessionEnd hook
 */
async function invalidateGroupClient(groupFolder: string): Promise<void> {
  const cached = groupClients.get(groupFolder);
  if (cached && cached.isActive) {
    cached.isActive = false;
    log(`Client marked as inactive for group: ${groupFolder}`);
    // Execute SessionEnd hook when client is invalidated
    await executeCustomHook('SessionEnd', { sessionId: cached.sessionId });
  }
}

/**
 * Shutdown all cached clients
 */
export async function shutdownAllClients(): Promise<void> {
  log(`Shutting down ${groupClients.size} cached clients...`);

  const shutdownPromises: Promise<void>[] = [];

  for (const [groupFolder, cached] of groupClients.entries()) {
    if (cached.isActive) {
      cached.isActive = false;
      shutdownPromises.push(
        (async () => {
          // Execute SessionEnd hook before disconnecting
          await executeCustomHook('SessionEnd', { sessionId: cached.sessionId });
          try {
            log(`Disconnecting client for group: ${groupFolder}`);
            await cached.client.disconnect();
            log(`Client disconnected for group: ${groupFolder}`);
          } catch (err) {
            log(`Error disconnecting client for ${groupFolder}: ${err}`);
          }
        })(),
      );
    }
  }

  await Promise.all(shutdownPromises);
  groupClients.clear();

  // Kill all MCP server processes
  try {
    const { execSync } = await import('child_process');
    execSync('pkill -f "ipc-mcp-stdio.js" 2>/dev/null || true');
    log('All MCP server processes killed');
  } catch {}

  log('All clients shut down');
}

/**
 * Cleanup stale clients (idle for too long)
 */
export async function cleanupStaleClients(maxIdleMs: number = 30 * 60 * 1000): Promise<void> {
  const now = Date.now();
  const staleGroups: string[] = [];

  for (const [groupFolder, cached] of groupClients.entries()) {
    if (cached.isActive && now - cached.lastUsedAt > maxIdleMs) {
      staleGroups.push(groupFolder);
    }
  }

  for (const groupFolder of staleGroups) {
    const cached = groupClients.get(groupFolder);
    if (cached) {
      cached.isActive = false;
      // Execute SessionEnd hook before disconnecting
      await executeCustomHook('SessionEnd', { sessionId: cached.sessionId });
      try {
        log(`Cleaning up stale client for group: ${groupFolder}`);
        await cached.client.disconnect();
      } catch (err) {
        log(`Error cleaning up stale client: ${err}`);
      }
      groupClients.delete(groupFolder);
    }
  }
}

/**
 * Run agent directly using iFlow SDK with smart session management
 */
export async function runAgentDirect(
  group: RegisteredGroup,
  input: AgentInput,
  onOutput?: (output: AgentOutput) => Promise<void>,
): Promise<AgentOutput> {
  log(`Starting direct agent for group: ${group.folder}`);

  const groupDir = resolveGroupFolderPath(group.folder);
  const ipcDir = resolveGroupIpcPath(group.folder);

  // Create directories
  fs.mkdirSync(groupDir, { recursive: true });
  fs.mkdirSync(path.join(ipcDir, 'messages'), { recursive: true });
  fs.mkdirSync(path.join(ipcDir, 'tasks'), { recursive: true });
  fs.mkdirSync(path.join(ipcDir, 'input'), { recursive: true });

  // Clean up close sentinel
  const closeSentinelPath = path.join(ipcDir, 'input', '_close');
  try { fs.unlinkSync(closeSentinelPath); } catch { /* ignore */ }

  // Prepare prompt
  let prompt = input.prompt;
  if (input.isScheduledTask) {
    prompt = `[SCHEDULED TASK - The following message was sent automatically.]\n\n${prompt}`;
  }

  // Drain pending IPC messages
  const pending = drainIpcInput(ipcDir);
  if (pending.length > 0) {
    log(`Draining ${pending.length} pending IPC messages into initial prompt`);
    prompt += '\n' + pending.join('\n');
  }

    // Build options and get or create cached client
  const options = buildSharedIFlowOptions(input, false);
  const { client, isReused } = await getOrCreateGroupClient(group.folder, options);
  let currentSessionId = client.getSessionId() || undefined;

  if (!currentSessionId) {
    await invalidateGroupClient(group.folder);
    throw new Error('Failed to obtain session ID from SDK');
  }

  log(`Using client for group ${group.folder}, sessionId: ${currentSessionId}, reused: ${isReused}`);

  // Run the agent loop (shared with container mode)
  const result = await runAgentLoop(client, prompt, {
    sessionId: currentSessionId,
    ipcDir,
    onOutput,
    log: (msg) => log(msg),
  });

  if (result.status === 'error') {
    await invalidateGroupClient(group.folder);
  }

  return result;
}

// Note: saveConversationAndSummary removed - Claude-Mem handles session history via Hooks
