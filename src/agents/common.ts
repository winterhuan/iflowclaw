import fs from 'fs';
import path from 'path';
import os from 'os';
import { IFlowClient, MessageType, IFlowOptions, MCPServerConfig, HookConfigs } from '@iflow-ai/iflow-cli-sdk';
import { logger } from '../logger.js';
import { GROUPS_DIR } from '../config.js';
import { resolveGroupFolderPath, resolveGroupIpcPath } from '../group-folder.js';

export interface AgentInput {
  prompt: string;
  sessionId?: string;
  groupFolder: string;
  chatJid: string;
  isMain: boolean;
  isScheduledTask?: boolean;
  assistantName?: string;
  extensionInput?: Record<string, unknown>;
}

export interface AgentOutput {
  status: 'success' | 'error';
  result: string | null;
  newSessionId?: string;
  error?: string;
}

// Custom hook types not supported by SDK but we handle ourselves
export interface CustomHookCommand {
  type: 'command';
  command: string;
  timeout?: number;
}

export interface CustomHookConfig {
  matcher?: string;
  hooks: CustomHookCommand[];
}

export interface CustomHooks {
  SessionStart?: CustomHookConfig[];
  UserPromptSubmit?: CustomHookConfig[];
  SessionEnd?: CustomHookConfig[];
}

/**
 * Load custom hooks from settings.json
 */
export function loadCustomHooks(): CustomHooks {
  const settingsPath = path.join(os.homedir(), '.iflow', 'settings.json');
  if (fs.existsSync(settingsPath)) {
    try {
      const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'));
      const customTypes = ['SessionStart', 'UserPromptSubmit', 'SessionEnd'];
      const hooks: CustomHooks = {};
      for (const type of customTypes) {
        if (settings.hooks?.[type]) {
          hooks[type as keyof CustomHooks] = settings.hooks[type];
        }
      }
      return hooks;
    } catch (err) {
      logger.error(`Failed to load custom hooks: ${err}`);
    }
  }
  return {};
}

/**
 * Execute a custom hook command
 */
export async function executeCustomHook(
  hookType: keyof CustomHooks,
  context?: { matcher?: string; prompt?: string; sessionId?: string; stdin?: string }
): Promise<void> {
  const hooks = loadCustomHooks();
  const hookConfigs = hooks[hookType];
  if (!hookConfigs || hookConfigs.length === 0) return;

  for (const config of hookConfigs) {
    // Check matcher: if config has matcher, we must have a matching context.matcher
    if (config.matcher) {
      if (!context?.matcher) continue; // Skip if no matcher context provided
      const regex = new RegExp(config.matcher, 'i');
      if (!regex.test(context.matcher)) continue;
    }

    for (const hook of config.hooks) {
      try {
        logger.info(`Executing custom hook ${hookType}: ${hook.command}`);
        const { exec } = await import('child_process');
        await new Promise<void>((resolve, reject) => {
          const timeout = hook.timeout || 60;
          // Build stdin data based on hook type
          // All hooks expect JSON format with session_id
          // UserPromptSubmit also includes prompt
          let stdinData: string;
          if (context?.stdin) {
            stdinData = context.stdin;
          } else if (hookType === 'UserPromptSubmit') {
            stdinData = JSON.stringify({
              prompt: context?.prompt || '',
              session_id: context?.sessionId || '',
            });
          } else {
            stdinData = JSON.stringify({
              session_id: context?.sessionId || '',
            });
          }

          exec(hook.command, {
            env: {
              ...process.env,
              IFLOW_HOOK_TYPE: hookType,
              IFLOW_SESSION_ID: context?.sessionId || '',
              IFLOW_PROMPT: context?.prompt || '',
            },
            maxBuffer: 10 * 1024 * 1024,
            timeout: timeout * 1000,
          }, (error, stdout, stderr) => {
            if (stdout) logger.info(`Hook stdout: ${stdout}`);
            if (stderr) logger.info(`Hook stderr: ${stderr}`);
            if (error) {
              const details = [error.message];
              if (stderr) details.push(`stderr: ${stderr}`);
              if (stdout) details.push(`stdout: ${stdout}`);
              reject(new Error(details.join(' | ')));
            } else {
              resolve();
            }
          }).stdin?.end(stdinData);
        });
        logger.info(`Custom hook ${hookType} completed`);
      } catch (err) {
        logger.error(`Custom hook ${hookType} failed: ${err}`);
      }
    }
  }
}

/**
 * Write tasks snapshot for agent to read
 */
export function writeTasksSnapshot(
  groupFolder: string,
  isMain: boolean,
  tasks: Array<{
    id: number | string;
    groupFolder: string;
    prompt: string;
    schedule_type: string;
    schedule_value: string | null;
    status: string;
    next_run: string | null;
  }>,
): void {
  const groupIpcDir = resolveGroupIpcPath(groupFolder);
  fs.mkdirSync(groupIpcDir, { recursive: true });

  // Main sees all tasks, others only see their own
  const filteredTasks = isMain
    ? tasks
    : tasks.filter((t) => t.groupFolder === groupFolder);

  const tasksFile = path.join(groupIpcDir, 'current_tasks.json');
  fs.writeFileSync(tasksFile, JSON.stringify(filteredTasks, null, 2));
}

export interface AvailableGroup {
  jid: string;
  name: string;
  lastActivity: string;
  isRegistered: boolean;
}

/**
 * Write available groups snapshot for the container to read.
 * Only main group can see all available groups (for activation).
 * Non-main groups only see their own registration status.
 */
export function writeGroupsSnapshot(
  groupFolder: string,
  isMain: boolean,
  groups: AvailableGroup[],
  registeredJids: Set<string>,
): void {
  const groupIpcDir = resolveGroupIpcPath(groupFolder);
  fs.mkdirSync(groupIpcDir, { recursive: true });

  // Main sees all groups; others see nothing (they can't activate groups)
  const visibleGroups = isMain ? groups : [];

  const groupsFile = path.join(groupIpcDir, 'available_groups.json');
  fs.writeFileSync(
    groupsFile,
    JSON.stringify(
      {
        groups: visibleGroups,
        registered: Array.from(registeredJids),
        lastSync: new Date().toISOString(),
      },
      null,
      2,
    ),
  );
}

/**
 * Strip XML message tags from formatted messages.
 */
export function stripMessageXml(formatted: string): string {
  // Remove context header
  let result = formatted.replace(/<context timezone="[^"]*" \/>\n?/g, '');

  // Remove outer messages tags
  result = result.replace(/<\/?messages>\n?/g, '');

  // Convert message tags to plain text format: [sender time]: content
  result = result.replace(
    /<message sender="([^"]*)" time="([^"]*)">([\s\S]*?)<\/message>/g,
    '[$1 $2]: $3'
  );

  // Unescape XML entities
  result = result
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"');

  return result.trim();
}

/**
 * Replace path placeholders in AGENTS.md content
 */
function processAgentsMarkdown(
  content: string,
  paths: { groupDir: string; globalDir: string; ipcDir: string }
): string {
  return content
    .replace(/\{\{GROUP_DIR\}\}/g, paths.groupDir)
    .replace(/\{\{GLOBAL_DIR\}\}/g, paths.globalDir)
    .replace(/\{\{IPC_DIR\}\}/g, paths.ipcDir);
}

/**
 * Build iFlow SDK options (shared logic)
 */
export function buildIFlowOptions(
  input: AgentInput,
  isContainer: boolean = false
): IFlowOptions {
  const groupDir = isContainer ? '/workspace/group' : resolveGroupFolderPath(input.groupFolder);
  const globalDir = isContainer ? '/workspace/global' : path.join(GROUPS_DIR, 'global');
  const ipcDir = isContainer ? '/workspace/ipc' : resolveGroupIpcPath(input.groupFolder);

  const pathContext = { groupDir, globalDir, ipcDir };

  // Build system prompt from AGENTS.md
  const parts: string[] = [];

  // 1. Load group's AGENTS.md
  const groupAgentsPath = path.join(groupDir, 'AGENTS.md');
  if (fs.existsSync(groupAgentsPath)) {
    const content = fs.readFileSync(groupAgentsPath, 'utf-8');
    parts.push(processAgentsMarkdown(content, pathContext));
  }

  // 2. Load global AGENTS.md for non-main groups
  if (!input.isMain) {
    const globalAgentsPath = path.join(globalDir, 'AGENTS.md');
    if (fs.existsSync(globalAgentsPath)) {
      const content = fs.readFileSync(globalAgentsPath, 'utf-8');
      parts.push('');
      parts.push('---');
      parts.push(processAgentsMarkdown(content, pathContext));
    }
  }

  const systemPrompt = parts.length > 0 ? parts.join('\n') : undefined;

  // MCP server config
  const mcpServerPath = isContainer
    ? '/app/dist/mcps/ipc-mcp-stdio.js'
    : path.resolve(process.cwd(), 'dist', 'mcps', 'ipc-mcp-stdio.js');

  const mcpServerConfig: MCPServerConfig = {
    name: 'iflowclaw',
    command: 'node',
    args: [mcpServerPath],
    env: [
      { name: 'IFLOWCLAW_GROUP_FOLDER', value: input.groupFolder },
      { name: 'IFLOWCLAW_CHAT_JID', value: input.chatJid },
      { name: 'IFLOWCLAW_IS_MAIN', value: input.isMain ? '1' : '0' },
      { name: 'IFLOWCLAW_IPC_DIR', value: isContainer ? '/workspace/ipc' : ipcDir },
    ],
  };

  // Load hooks from ~/.iflow/settings.json
  let sdkHooks: HookConfigs | undefined;
  const settingsPath = path.join(os.homedir(), '.iflow', 'settings.json');
  if (fs.existsSync(settingsPath)) {
    try {
      const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'));
      if (settings.hooks) {
        const supportedTypes = ['PreToolUse', 'PostToolUse', 'Stop', 'SubagentStop', 'SetUpEnvironment'];
        const filteredHooks: HookConfigs = {};
        for (const type of supportedTypes) {
          if (settings.hooks[type]) {
            filteredHooks[type as keyof HookConfigs] = settings.hooks[type];
          }
        }
        if (Object.keys(filteredHooks).length > 0) {
          sdkHooks = filteredHooks;
        }
      }
    } catch (err) {
      logger.error(`Failed to load SDK hooks: ${err}`);
    }
  }

  // Main group in direct mode can access project root
  const projectRoot = process.cwd();
  const allowedDirs = input.isMain && !isContainer
    ? [groupDir, globalDir, projectRoot]
    : [groupDir, globalDir];

  const options: IFlowOptions = {
    transportMode: 'stdio',
    logLevel: 'DEBUG',
    cwd: groupDir,
    autoStartProcess: true,
    timeout: 1800, // 30 minutes in seconds (SDK expects seconds, not milliseconds)
    mcpServers: [mcpServerConfig],
    hooks: sdkHooks as HookConfigs,
    sessionSettings: {
      system_prompt: systemPrompt,
      permission_mode: isContainer ? 'yolo' : 'default', // Auto-approve in container
      add_dirs: input.isMain && !isContainer ? [globalDir, projectRoot] : [globalDir],
    },
    fileAccess: true,
    fileAllowedDirs: allowedDirs,
  };

  return options;
}

const IPC_POLL_MS = 500;

/**
 * Drain IPC input directory for follow-up messages
 */
export function drainIpcInput(ipcDir: string): string[] {
  const inputDir = path.join(ipcDir, 'input');
  try {
    if (!fs.existsSync(inputDir)) {
      fs.mkdirSync(inputDir, { recursive: true });
      return [];
    }

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
        logger.error(`Failed to process input file ${file}: ${err}`);
        try { fs.unlinkSync(filePath); } catch { /* ignore */ }
      }
    }
    return messages;
  } catch (err) {
    logger.error(`IPC drain error: ${err}`);
    return [];
  }
}

/**
 * Check if close sentinel exists
 */
export function shouldClose(ipcDir: string): boolean {
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
export function waitForIpcMessage(ipcDir: string): Promise<string | null> {
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
 * Common execution loop for both direct and container mode
 */
export async function runAgentLoop(
  client: IFlowClient,
  initialPrompt: string,
  options: {
    sessionId: string;
    ipcDir?: string;
    onOutput?: (output: AgentOutput) => Promise<void>;
    log: (msg: string) => void;
  }
): Promise<AgentOutput> {
  const { sessionId, ipcDir, onOutput, log } = options;
  let prompt = initialPrompt;
  let hasOutput = false;
  let totalTurns = 0;

  try {
    let askUserQuestionsRequestId: number | string | undefined;

    while (true) {
      totalTurns++;
      log(`Conversation turn ${totalTurns}, sending prompt (${prompt.length} chars)...`);

      // Execute UserPromptSubmit hook
      await executeCustomHook('UserPromptSubmit', {
        sessionId,
        prompt: stripMessageXml(prompt),
      });

      await client.sendMessage(prompt);
      log('Prompt sent, waiting for response...');

      let messageCount = 0;
      let resultText = '';

      for await (const message of client.receiveMessages()) {
        messageCount++;
        if (message.type === MessageType.ASSISTANT && message.chunk?.text) {
          resultText += message.chunk.text;
          hasOutput = true;
        } else if (message.type === MessageType.ASK_USER_QUESTIONS) {
          const askMsg = message as any;
          askUserQuestionsRequestId = askMsg.requestId || askMsg.id;
          log(`Received ask_user_questions request: ${askUserQuestionsRequestId}`);

          // Extract question text to display to user
          let questionText = '';
          if (askMsg.questions && askMsg.questions.length > 0) {
            questionText = askMsg.questions.map((q: any, idx: number) => {
              let text = q.question || q.label || q.text || '';
              if (q.options && q.options.length > 0) {
                const optionsText = q.options.map((opt: any, optIdx: number) => {
                  return `  ${optIdx + 1}. ${opt.label || opt.text || opt.value || ''}`;
                }).join('\n');
                text += `\nOptions:\n${optionsText}`;
              }
              return `${idx + 1}. ${text}`;
            }).join('\n\n');
          } else if (askMsg.text) {
            questionText = askMsg.text;
          }

          if (questionText) {
            resultText += questionText;
            hasOutput = true;
          }

          // Break to send questions to user and wait for response
          break;
        } else if (message.type === MessageType.TASK_FINISH) {
          log('Task finished');
          break;
        } else if (message.type === MessageType.ERROR) {
          throw new Error(message.message || 'Unknown agent error');
        }

        if (messageCount > 1000) {
          log('Too many messages in turn, breaking');
          break;
        }
      }

      log(`Turn ${totalTurns} complete. Messages: ${messageCount}, Result length: ${resultText.length}`);

      if (resultText && onOutput) {
        await onOutput({
          status: 'success',
          result: resultText,
          newSessionId: sessionId,
        });
      }

      if (!ipcDir) break;

      log('Checking for IPC follow-up...');
      const nextMessage = await waitForIpcMessage(ipcDir);
      if (nextMessage === null) {
        log('Close sentinel received, exiting loop');
        break;
      }

      // If we have a pending ask_user_questions request, respond to it
      if (askUserQuestionsRequestId !== undefined) {
        log(`Responding to ask_user_questions request ${askUserQuestionsRequestId} with user answer`);
        const answers: Record<string, string | string[]> = {};
        const lines = nextMessage.split('\n').filter(l => l.trim());

        lines.forEach((line, idx) => {
          const match = line.match(/^\d+[.:\s]+(.+)$/);
          if (match) {
            answers[`question_${idx}`] = match[1].trim();
          } else if (idx === 0 && lines.length === 1) {
            answers['question_0'] = line.trim();
          } else {
            answers[`question_${idx}`] = line.trim();
          }
        });

        if (Object.keys(answers).length === 0) {
          answers['question_0'] = nextMessage.trim();
        }

        await client.respondToAskUserQuestions(answers);
        askUserQuestionsRequestId = undefined;
        continue;
      }

      log(`Got follow-up message (${nextMessage.length} chars)`);
      prompt = nextMessage;
    }

    return {
      status: 'success',
      result: hasOutput ? null : 'No response generated',
      newSessionId: sessionId,
    };
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    log(`Agent loop error: ${errorMessage}`);
    return {
      status: 'error',
      result: null,
      error: errorMessage,
    };
  }
}
