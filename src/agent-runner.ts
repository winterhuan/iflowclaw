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
import { fileURLToPath } from 'url';
import { IFlowClient, MessageType, IFlowOptions, MCPServerConfig } from '@iflow-ai/iflow-cli-sdk';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

import { logger } from './logger.js';
import { GROUPS_DIR, DATA_DIR } from './config.js';
import { resolveGroupFolderPath, resolveGroupIpcPath } from './group-folder.js';
import { RegisteredGroup } from './types.js';
import { getMemoryContext } from './memory.js';
import { saveConversationHistory, type ConversationMessage } from './session-history.js';
import { generateSummaryAsync } from './summary-generator.js';
import { incrementMessageCount, getSessionStats } from './db.js';
import { saveMemory } from './db.js';
const IPC_POLL_MS = 500;

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
  try {
    const { execSync } = await import('child_process');
    execSync(`pkill -f "ipc-mcp-stdio.js.*${groupFolder}" 2>/dev/null || true`);
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
 * Mark client as inactive (on error)
 */
function invalidateGroupClient(groupFolder: string): void {
  const cached = groupClients.get(groupFolder);
  if (cached) {
    cached.isActive = false;
    log(`Client marked as inactive for group: ${groupFolder}`);
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

export interface AgentInput {
  prompt: string;
  sessionId?: string;
  groupFolder: string;
  chatJid: string;
  isMain: boolean;
  isScheduledTask?: boolean;
  assistantName?: string;
  [key: string]: unknown;
}

export interface AgentOutput {
  status: 'success' | 'error';
  result: string | null;
  newSessionId?: string;
  error?: string;
}

function log(message: string): void {
  logger.info(`[agent] ${message}`);
}

/**
 * Setup per-group directories
 * Note: All groups share the host's ~/.iflow/ configuration
 */
function setupGroupEnvironment(group: RegisteredGroup): {
  groupDir: string;
  ipcDir: string;
} {
  const groupDir = resolveGroupFolderPath(group.folder);
  const ipcDir = resolveGroupIpcPath(group.folder);

  // Create directories
  fs.mkdirSync(groupDir, { recursive: true });
  fs.mkdirSync(path.join(ipcDir, 'messages'), { recursive: true });
  fs.mkdirSync(path.join(ipcDir, 'tasks'), { recursive: true });
  fs.mkdirSync(path.join(ipcDir, 'input'), { recursive: true });
  fs.mkdirSync(path.join(ipcDir, 'memories'), { recursive: true });

  return { groupDir, ipcDir };
}

/**
 * Build iFlow SDK options
 * Uses group's .iflow/ directory for custom skills, commands, and workflows
 */
function buildIFlowOptions(
  input: AgentInput,
  groupDir: string,
  globalDir: string,
): IFlowOptions {
  // Build system prompt with memory context
  const parts: string[] = [];

  // 1. Inject high-importance memories
  const memoryContext = getMemoryContext(input.groupFolder, 10);
  if (memoryContext) {
    parts.push(memoryContext);
    parts.push('');
  }

  // 2. Load global AGENTS.md as additional system context
  if (!input.isMain && fs.existsSync(globalDir)) {
    const globalAgentsPath = path.join(globalDir, 'AGENTS.md');
    if (fs.existsSync(globalAgentsPath)) {
      parts.push(fs.readFileSync(globalAgentsPath, 'utf-8'));
    }
  }

  const systemPrompt = parts.length > 0 ? parts.join('\n') : undefined;

  // IPC directory for this group
  const ipcDir = path.join(DATA_DIR, 'ipc', input.groupFolder);
  fs.mkdirSync(ipcDir, { recursive: true });

  // Build MCP server config with context env vars
  const mcpServerPath = path.join(__dirname, 'mcps', 'ipc-mcp-stdio.js');
  log(`MCP server path: ${mcpServerPath}`);
  log(`MCP env vars: IFLOWCLAW_GROUP_FOLDER=${input.groupFolder}, IFLOWCLAW_CHAT_JID=${input.chatJid}, IFLOWCLAW_IS_MAIN=${input.isMain}`);

  const mcpServerConfig: MCPServerConfig = {
    name: 'iflowclaw',
    command: 'node',
    args: [mcpServerPath],
    env: [
      { name: 'IFLOWCLAW_GROUP_FOLDER', value: input.groupFolder },
      { name: 'IFLOWCLAW_CHAT_JID', value: input.chatJid },
      { name: 'IFLOWCLAW_IS_MAIN', value: input.isMain ? '1' : '0' },
      { name: 'IFLOWCLAW_IPC_DIR', value: path.join(DATA_DIR, 'ipc') },
    ],
  };

  const mcpsDir = path.join(__dirname, 'mcps');
  const projectRoot = path.dirname(__dirname); // dist -> project root
  const srcDir = path.join(projectRoot, 'src');
  const options: IFlowOptions = {
    logLevel: "DEBUG",
    cwd: groupDir,
    autoStartProcess: true,
    timeout: 1800000, // 30 minute
    mcpServers: [mcpServerConfig],
    sessionSettings: {
      system_prompt: systemPrompt,
      permission_mode: 'yolo', // Auto-approve all tools
      add_dirs: [globalDir, srcDir],
    },
    fileAccess: true,
    fileAllowedDirs: [groupDir, globalDir, mcpsDir, srcDir],
  };
  return options;
}

/**
 * Drain IPC input directory for follow-up messages
 */
function drainIpcInput(ipcDir: string): string[] {
  const inputDir = path.join(ipcDir, 'input');
  try {
    fs.mkdirSync(inputDir, { recursive: true });
    const files = fs.readdirSync(inputDir)
      .filter(f => f.endsWith('.json'))
      .sort();

    const messages: string[] = [];
    for (const file of files) {
      const filePath = path.join(inputDir, file);
      try {
        const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
        fs.unlinkSync(filePath);
        if (data.type === 'message' && data.text) {
          messages.push(data.text);
        }
      } catch (err) {
        log(`Failed to process input file ${file}: ${err}`);
        try { fs.unlinkSync(filePath); } catch { /* ignore */ }
      }
    }
    return messages;
  } catch (err) {
    log(`IPC drain error: ${err}`);
    return [];
  }
}

/**
 * Check if close sentinel exists
 */
function shouldClose(ipcDir: string): boolean {
  const sentinelPath = path.join(ipcDir, 'input', '_close');
  if (fs.existsSync(sentinelPath)) {
    try { fs.unlinkSync(sentinelPath); } catch { /* ignore */ }
    return true;
  }
  return false;
}

/**
 * Wait for next IPC message
 */
function waitForIpcMessage(ipcDir: string): Promise<string | null> {
  return new Promise((resolve) => {
    const poll = () => {
      if (shouldClose(ipcDir)) {
        resolve(null);
        return;
      }
      const messages = drainIpcInput(ipcDir);
      if (messages.length > 0) {
        resolve(messages.join('\n'));
        return;
      }
      setTimeout(poll, IPC_POLL_MS);
    };
    poll();
  });
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

  // Setup environment
  const { groupDir, ipcDir } = setupGroupEnvironment(group);
  const globalDir = path.join(GROUPS_DIR, 'global');

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
  const options = buildIFlowOptions(input, groupDir, globalDir);
  const { client, isReused } = await getOrCreateGroupClient(group.folder, options);
  let currentSessionId = client.getSessionId() || undefined;

  if (!currentSessionId) {
    invalidateGroupClient(group.folder);
    throw new Error('Failed to obtain session ID from SDK');
  }

  log(`Using client for group ${group.folder}, sessionId: ${currentSessionId}, reused: ${isReused}`);

  // Track conversation for history
  const conversationMessages: ConversationMessage[] = [];
  let totalTurns = 0;

  try {
    // Main loop
    let hasOutput = false;
    while (true) {
      totalTurns++;
      log(`Conversation turn ${totalTurns}, sending prompt (${prompt.length} chars)...`);
      
      // Record user message
      conversationMessages.push({
        role: 'user',
        content: prompt,
        timestamp: new Date().toISOString(),
      });

      await client.sendMessage(prompt);
      log('Prompt sent, waiting for response...');

      let messageCount = 0;
      let resultText = '';

      for await (const message of client.receiveMessages()) {
        messageCount++;
        log(`Received message #${messageCount}: type=${message.type}`);

        if (message.type === MessageType.ASSISTANT && message.chunk?.text) {
          resultText += message.chunk.text;
          hasOutput = true;
          log(`Assistant chunk: ${message.chunk.text.substring(0, 50)}...`);
        } else if (message.type === MessageType.TOOL_CALL) {
          // Tool calls are handled by SDK internally, just log for debugging
          const toolName = (message as any).toolName || (message as any).tool_name || 'unknown';
          const toolLabel = (message as any).label || 'no label';
          log(`Tool call: ${toolName}, label: ${toolLabel}, content: ${JSON.stringify(message).substring(0, 200)}`);
        } else if (message.type === MessageType.TASK_FINISH) {
          log('Task finished!');
          break;
        } else if (message.type === MessageType.ERROR) {
          log(`Error: ${message.message}`);
          throw new Error(message.message || 'Unknown error');
        } else if (message.type === MessageType.PERMISSION_REQUEST) {
          // Auto-approve in yolo mode, but log for debugging
          log(`Permission request: ${(message as any).tool_name || 'unknown'}`);
        }

        if (messageCount > 500) {
          log('Too many messages, breaking');
          break;
        }
      }

      log(`Response complete. Messages: ${messageCount}, Result length: ${resultText.length}`);

      // Record assistant response
      if (resultText) {
        conversationMessages.push({
          role: 'assistant',
          content: resultText,
          timestamp: new Date().toISOString(),
        });
      }

      // Stream output to callback
      if (onOutput && resultText) {
        await onOutput({
          status: 'success',
          result: resultText,
          newSessionId: currentSessionId,
        });
      }

      // Check for follow-up messages via IPC
      log('Checking for IPC follow-up messages...');
      const nextMessage = await waitForIpcMessage(ipcDir);
      if (nextMessage === null) {
        log('Close received, exiting');
        break;
      }

      log(`Got new message (${nextMessage.length} chars), continuing...`);
      prompt = nextMessage;
    }

    // Save conversation history and trigger summary if needed
    if (conversationMessages.length > 0) {
      await saveConversationAndSummary(
        group.folder,
        currentSessionId,
        conversationMessages,
        groupDir
      );
    }

    return {
      status: 'success',
      result: hasOutput ? null : 'No response generated',
      newSessionId: currentSessionId,
    };
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    log(`Agent error: ${errorMessage}`);
    // Mark client as invalid on error so next call creates new one
    invalidateGroupClient(group.folder);
    return {
      status: 'error',
      result: null,
      error: errorMessage,
    };
  }
  // Note: We don't disconnect here because client is cached for reuse
}

/**
 * Save conversation history and trigger summary generation if needed
 */
async function saveConversationAndSummary(
  groupFolder: string,
  sessionId: string,
  messages: ConversationMessage[],
  groupDir: string,
): Promise<void> {
  if (messages.length === 0) return;

  try {
    // Update message count in session stats
    const newCount = incrementMessageCount(groupFolder, sessionId);
    log(`Session message count: ${newCount}`);

    // Save conversation history
    const historyFile = saveConversationHistory(groupFolder, {
      sessionId,
      messages,
      startTime: messages[0]?.timestamp || new Date().toISOString(),
      endTime: messages[messages.length - 1]?.timestamp || new Date().toISOString(),
      messageCount: messages.length,
    });
    log(`Conversation history saved: ${historyFile}`);

    // Trigger summary generation if message count exceeds threshold
    const SUMMARY_THRESHOLD = 30; // Generate summary every 30 messages
    if (newCount >= SUMMARY_THRESHOLD && newCount % SUMMARY_THRESHOLD === 0) {
      log(`Message count (${newCount}) reached threshold, triggering summary generation`);
      
      const summaryFile = `${historyFile}.summary.json`;
      generateSummaryAsync(historyFile, summaryFile);
      
      // Note: The summary will be saved as a memory by the summary generator
      // or we can add logic here to wait for it and save to memories table
      log(`Summary generation triggered: ${summaryFile}`);
    }
  } catch (err) {
    log(`Error saving conversation history: ${err}`);
    // Don't throw - conversation history is not critical
  }
}
