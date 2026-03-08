/**
 * iFlowClaw Agent Runner
 * Runs inside a container, receives config via stdin, outputs result to stdout
 * Uses iFlow SDK with automatic authentication from ~/.iflow/settings.json
 *
 * Authentication:
 * - If IFLOW_API_KEY is provided via stdin, use it
 * - Otherwise, SDK will use credentials from ~/.iflow/settings.json (OAuth login)
 *
 * Input protocol:
 *   Stdin: Full ContainerInput JSON (read until EOF)
 *   IPC:   Follow-up messages written as JSON files to /workspace/ipc/input/
 *          Sentinel: /workspace/ipc/input/_close — signals session end
 *
 * Stdout protocol:
 *   Each result is wrapped in OUTPUT_START_MARKER / OUTPUT_END_MARKER pairs.
 */

import fs from 'fs';
import path from 'path';
import { IFlowClient, MessageType, IFlowOptions, MCPServerConfig } from '@iflow-ai/iflow-cli-sdk';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

interface ContainerInput {
  prompt: string;
  sessionId?: string;
  groupFolder: string;
  chatJid: string;
  isMain: boolean;
  isScheduledTask?: boolean;
  assistantName?: string;
  secrets?: Record<string, string>;
}

interface ContainerOutput {
  status: 'success' | 'error';
  result: string | null;
  error?: string;
}

const IPC_INPUT_DIR = '/workspace/ipc/input';
const IPC_INPUT_CLOSE_SENTINEL = path.join(IPC_INPUT_DIR, '_close');
const IPC_POLL_MS = 500;

const OUTPUT_START_MARKER = '---IFLOWCLAW_OUTPUT_START---';
const OUTPUT_END_MARKER = '---IFLOWCLAW_OUTPUT_END---';

function writeOutput(output: ContainerOutput): void {
  console.log(OUTPUT_START_MARKER);
  console.log(JSON.stringify(output));
  console.log(OUTPUT_END_MARKER);
}

function log(message: string): void {
  console.error(`[agent-runner] ${message}`);
}

async function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => { data += chunk; });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

function shouldClose(): boolean {
  if (fs.existsSync(IPC_INPUT_CLOSE_SENTINEL)) {
    try { fs.unlinkSync(IPC_INPUT_CLOSE_SENTINEL); } catch { /* ignore */ }
    return true;
  }
  return false;
}

function drainIpcInput(): string[] {
  try {
    fs.mkdirSync(IPC_INPUT_DIR, { recursive: true });
    const files = fs.readdirSync(IPC_INPUT_DIR)
      .filter(f => f.endsWith('.json'))
      .sort();

    const messages: string[] = [];
    for (const file of files) {
      const filePath = path.join(IPC_INPUT_DIR, file);
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

function waitForIpcMessage(): Promise<string | null> {
  return new Promise((resolve) => {
    const poll = () => {
      if (shouldClose()) {
        resolve(null);
        return;
      }
      const messages = drainIpcInput();
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
 * Build iFlow options from container input.
 * Supports both API Key and OAuth (via ~/.iflow/settings.json)
 */
function buildIFlowOptions(containerInput: ContainerInput, mcpServerPath: string): IFlowOptions {
  // Load global CLAUDE.md as additional system context
  const globalClaudeMdPath = '/workspace/global/CLAUDE.md';
  let systemPrompt: string | undefined;
  if (!containerInput.isMain && fs.existsSync(globalClaudeMdPath)) {
    systemPrompt = fs.readFileSync(globalClaudeMdPath, 'utf-8');
  }

  // Discover additional directories mounted at /workspace/extra/*
  const extraDirs: string[] = [];
  const extraBase = '/workspace/extra';
  if (fs.existsSync(extraBase)) {
    for (const entry of fs.readdirSync(extraBase)) {
      const fullPath = path.join(extraBase, entry);
      if (fs.statSync(fullPath).isDirectory()) {
        extraDirs.push(fullPath);
      }
    }
  }

  // Build MCP server config
  const mcpServers: MCPServerConfig[] = [{
    name: 'iflowclaw',
    command: 'node',
    args: [mcpServerPath],
    env: [
      { name: 'IFLOWCLAW_CHAT_JID', value: containerInput.chatJid },
      { name: 'IFLOWCLAW_GROUP_FOLDER', value: containerInput.groupFolder },
      { name: 'IFLOWCLAW_IS_MAIN', value: containerInput.isMain ? '1' : '0' },
    ]
  }];

  // Build options - SDK will automatically use ~/.iflow/settings.json if no API key provided
  const options: IFlowOptions = {
    cwd: '/workspace/group',
    // autoStartProcess: true lets SDK manage iFlow process automatically
    // It will use credentials from ~/.iflow/settings.json (OAuth login)
    autoStartProcess: true,
    timeout: 1800000, // 30 minutes default
    mcpServers,
    sessionSettings: {
      system_prompt: systemPrompt,
      allowed_tools: [
        'Bash',
        'Read', 'Write', 'Edit', 'Glob', 'Grep',
        'WebSearch', 'WebFetch',
        'Task', 'TaskOutput', 'TaskStop',
        'TeamCreate', 'TeamDelete', 'SendMessage',
        'TodoWrite', 'ToolSearch', 'Skill',
        'NotebookEdit',
        'mcp__iflowclaw__*'
      ],
      permission_mode: 'yolo', // bypass permissions in container
      add_dirs: extraDirs.length > 0 ? extraDirs : undefined,
    },
    fileAccess: true,
    fileAllowedDirs: ['/workspace'],
  };

  // If API key is provided via secrets, use it (for headless environments)
  const secrets = containerInput.secrets || {};
  if (secrets.IFLOW_API_KEY) {
    options.authMethodId = 'api_key';
    options.authMethodInfo = {
      apiKey: secrets.IFLOW_API_KEY,
      baseUrl: secrets.IFLOW_BASE_URL,
      modelName: secrets.IFLOW_MODEL_NAME,
    };
    log('Using API key authentication');
  } else {
    log('Using OAuth credentials from ~/.iflow/settings.json');
  }

  return options;
}

/**
 * Run a single query and stream results.
 */
async function runQuery(
  client: IFlowClient,
  prompt: string,
): Promise<{ result: string | null; closedDuringQuery: boolean }> {
  let resultParts: string[] = [];
  let closedDuringQuery = false;
  let ipcPolling = true;

  const pollIpcDuringQuery = async () => {
    while (ipcPolling) {
      if (shouldClose()) {
        log('Close sentinel detected during query');
        closedDuringQuery = true;
        return;
      }
      const messages = drainIpcInput();
      for (const text of messages) {
        log(`Piping IPC message into active query (${text.length} chars)`);
        try {
          await client.sendMessage(text);
        } catch (e) {
          log(`Failed to send IPC message: ${e}`);
        }
      }
      await new Promise(r => setTimeout(r, IPC_POLL_MS));
    }
  };
  const ipcPromise = pollIpcDuringQuery();

  try {
    await client.sendMessage(prompt);

    for await (const message of client.receiveMessages()) {
      if (message.type === MessageType.ASSISTANT && message.chunk.text) {
        resultParts.push(message.chunk.text);
        process.stdout.write(message.chunk.text);
      } else if (message.type === MessageType.TOOL_CALL) {
        log(`Tool call: ${message.toolName || 'unknown'} - status: ${message.status}`);
      } else if (message.type === MessageType.PLAN) {
        log(`Plan received with ${message.entries.length} entries`);
      } else if (message.type === MessageType.TASK_FINISH) {
        log('Task finished');
        break;
      } else if (message.type === MessageType.ERROR) {
        log(`Error: ${message.message}`);
        throw new Error(message.message);
      }
    }
  } finally {
    ipcPolling = false;
    await ipcPromise;
  }

  return { 
    result: resultParts.length > 0 ? resultParts.join('') : null, 
    closedDuringQuery 
  };
}

async function main(): Promise<void> {
  let containerInput: ContainerInput;

  try {
    const stdinData = await readStdin();
    containerInput = JSON.parse(stdinData);
    try { fs.unlinkSync('/tmp/input.json'); } catch { /* may not exist */ }
    log(`Received input for group: ${containerInput.groupFolder}`);
  } catch (err) {
    writeOutput({
      status: 'error',
      result: null,
      error: `Failed to parse input: ${err}`
    });
    process.exit(1);
  }

  const mcpServerPath = path.join(__dirname, 'ipc-mcp-stdio.js');
  fs.mkdirSync(IPC_INPUT_DIR, { recursive: true });
  try { fs.unlinkSync(IPC_INPUT_CLOSE_SENTINEL); } catch { /* ignore */ }

  let prompt = containerInput.prompt;
  if (containerInput.isScheduledTask) {
    prompt = `[SCHEDULED TASK - The following message was sent automatically.]\n\n${prompt}`;
  }
  const pending = drainIpcInput();
  if (pending.length > 0) {
    log(`Draining ${pending.length} pending IPC messages into initial prompt`);
    prompt += '\n' + pending.join('\n');
  }

  const options = buildIFlowOptions(containerInput, mcpServerPath);
  const client = new IFlowClient(options);

  try {
    await client.connect();
    log('Connected to iFlow');

    while (true) {
      log(`Starting query...`);

      const queryResult = await runQuery(client, prompt);

      writeOutput({
        status: 'success',
        result: queryResult.result,
      });

      if (queryResult.closedDuringQuery) {
        log('Close sentinel consumed during query, exiting');
        break;
      }

      log('Query ended, waiting for next IPC message...');

      const nextMessage = await waitForIpcMessage();
      if (nextMessage === null) {
        log('Close sentinel received, exiting');
        break;
      }

      log(`Got new message (${nextMessage.length} chars), starting new query`);
      prompt = nextMessage;
    }
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    log(`Agent error: ${errorMessage}`);
    writeOutput({
      status: 'error',
      result: null,
      error: errorMessage
    });
    process.exit(1);
  } finally {
    await client.disconnect();
  }
}

main();
