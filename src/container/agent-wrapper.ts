/**
 * iFlow Agent Wrapper for Container Mode
 * Runs inside a container using iFlow CLI SDK (same as direct mode)
 *
 * Input protocol:
 *   Stdin: Full ContainerInput JSON (read until EOF)
 *   IPC:   Follow-up messages written as JSON files to /workspace/ipc/input/
 *
 * Stdout protocol:
 *   Each result is wrapped in OUTPUT_START_MARKER / OUTPUT_END_MARKER pairs.
 */
import fs from 'fs';
import path from 'path';
import { IFlowClient } from '@iflow-ai/iflow-cli-sdk';

import {
  AgentInput,
  AgentOutput,
  buildIFlowOptions as buildSharedIFlowOptions,
  runAgentLoop,
  drainIpcInput
} from '../agents/common.js';

// Paths inside container
const IPC_DIR = '/workspace/ipc';
const IPC_INPUT_DIR = path.join(IPC_DIR, 'input');
const OUTPUT_START_MARKER = '---IFLOW_OUTPUT_START---';
const OUTPUT_END_MARKER = '---IFLOW_OUTPUT_END---';

/**
 * Write output with markers for streaming parsing
 */
function writeOutput(output: AgentOutput): void {
  process.stdout.write(OUTPUT_START_MARKER + '\n');
  process.stdout.write(JSON.stringify(output) + '\n');
  process.stdout.write(OUTPUT_END_MARKER + '\n');
}

/**
 * Log to stderr (doesn't interfere with stdout protocol)
 */
function log(message: string): void {
  const timestamp = new Date().toISOString();
  process.stderr.write(`[${timestamp}] [agent-wrapper] ${message}\n`);
}

/**
 * Read stdin until EOF
 */
async function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

/**
 * Run agent using iFlow SDK (same logic as agent-runner.ts)
 */
async function runAgent(input: AgentInput): Promise<AgentOutput> {
  log(`Starting iFlow SDK agent for group: ${input.groupFolder}`);

  // Build options
  const options = buildSharedIFlowOptions(input, true);
  const client = new IFlowClient(options);

  try {
    // Connect
    await client.connect();
    const sessionId = client.getSessionId();

    if (!sessionId) {
      throw new Error('Failed to obtain session ID');
    }

    log(`Connected, sessionId: ${sessionId}`);

    // Prepare prompt
    let prompt = input.prompt;
    if (input.isScheduledTask) {
      prompt = `[SCHEDULED TASK - The following message was sent automatically.]\n\n${prompt}`;
    }

    // Drain pending IPC messages
    const pending = drainIpcInput(IPC_DIR);
    if (pending.length > 0) {
      log(`Draining ${pending.length} pending IPC messages`);
      prompt += '\n' + pending.join('\n');
    }

    // Run the agent loop (shared with host mode)
    const result = await runAgentLoop(client, prompt, {
      sessionId,
      ipcDir: IPC_DIR,
      onOutput: async (output) => {
        writeOutput(output);
      },
      log: (msg) => log(msg),
    });

    // Disconnect
    await client.disconnect();

    return result;
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    log(`Agent error: ${errorMessage}`);
    try {
      await client.disconnect();
    } catch { /* ignore */ }
    return {
      status: 'error',
      result: null,
      error: errorMessage,
    };
  }
}

/**
 * Main entry point
 */
async function main(): Promise<void> {
  log('='.repeat(50));
  log('iFlow Agent Wrapper Starting (Container Mode)');
  log('='.repeat(50));

  try {
    // Log environment
    log(`Node version: ${process.version}`);
    log(`Working directory: ${process.cwd()}`);

    // Ensure directories exist
    fs.mkdirSync(IPC_INPUT_DIR, { recursive: true });

    // Read input from stdin
    const inputData = await readStdin();
    if (!inputData) {
      throw new Error('No input provided via stdin');
    }

    const input: AgentInput = JSON.parse(inputData);
    log(`Input parsed:`);
    log(`  Group: ${input.groupFolder}`);
    log(`  Chat: ${input.chatJid}`);
    log(`  Is Main: ${input.isMain}`);
    log(`  Prompt length: ${input.prompt.length} chars`);

    // Run agent
    const output = await runAgent(input);

    // Write final output
    log(`Final output status: ${output.status}`);
    writeOutput(output);

    process.exit(0);
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    log(`FATAL ERROR: ${errorMessage}`);

    writeOutput({
      status: 'error',
      result: null,
      error: errorMessage,
    });

    process.exit(1);
  }
}

main();
