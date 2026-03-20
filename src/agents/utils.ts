/**
 * Agent utilities - shared helper functions
 * Hybrid mode: supports both direct execution and container execution
 * Based on nanoclaw's container-runner.ts
 */
import { ChildProcess } from 'child_process';
import fs from 'fs';
import path from 'path';

import { AGENT_TIMEOUT } from '../config.js';
import { resolveGroupFolderPath, resolveGroupIpcPath } from '../group-folder.js';
import { logger } from '../logger.js';
import { runAgentDirect } from './runner.js';
import { runContainerAgent } from './container-runner.js';
import { isContainerRuntimeAvailable } from './container-runtime.js';
import { AvailableGroup, RegisteredGroup } from '../types.js';
import type { AgentInput, AgentOutput } from './common.js';

// Execution mode type
type ExecutionMode = 'direct' | 'container' | 'auto';

/**
 * Get execution mode for a group
 * - Main group: defaults to 'direct' (host machine)
 * - Other groups: defaults to 'container' (Docker sandbox)
 */
function getExecutionMode(group: RegisteredGroup): ExecutionMode {
  // 1. Check group config (highest priority)
  if (group.agentConfig?.executionMode) {
    return group.agentConfig.executionMode as ExecutionMode;
  }

  // 2. Check environment variable
  const envMode = process.env.IFLOW_DEFAULT_EXECUTION_MODE as ExecutionMode;
  if (envMode) return envMode;

  // 3. Default based on group type
  // Main group -> direct (host machine, no sandbox)
  // Other groups -> container (Docker sandbox for isolation)
  // Note: group.isMain can be undefined, true, or false
  // Use explicit check to avoid treating undefined as false
  return group.isMain === true ? 'direct' : 'container';
}

/**
 * Run agent with hybrid mode support
 * Routes to container or direct execution based on configuration
 */
export async function runAgent(
  group: RegisteredGroup,
  input: AgentInput,
  onProcess: (proc: ChildProcess | { kill: (signal: string) => void; stdin?: { write: (data: string) => void; end: () => void } }, containerName: string) => void,
  onOutput?: (output: AgentOutput) => Promise<void>,
): Promise<AgentOutput> {
  const mode = getExecutionMode(group);
  const hasContainerRuntime = isContainerRuntimeAvailable();

  // Determine actual execution mode
  let actualMode: 'direct' | 'container';
  if (mode === 'auto') {
    actualMode = hasContainerRuntime ? 'container' : 'direct';
  } else {
    actualMode = mode;
  }

  // Fallback if container requested but not available
  if (actualMode === 'container' && !hasContainerRuntime) {
    logger.warn(
      { group: group.name, requestedMode: mode },
      'Container mode requested but Docker not available, falling back to direct'
    );
    actualMode = 'direct';
  }

  logger.info(
    { group: group.name, requestedMode: mode, actualMode, hasContainerRuntime },
    'Agent execution mode'
  );

  // Route to appropriate executor
  if (actualMode === 'container') {
    return runAgentInContainer(group, input, onProcess, onOutput);
  } else {
    return runAgentDirectly(group, input, onProcess, onOutput);
  }
}

/**
 * Run agent in container (based on nanoclaw)
 */
async function runAgentInContainer(
  group: RegisteredGroup,
  input: AgentInput,
  onProcess: (proc: ChildProcess | { kill: (signal: string) => void; stdin?: { write: (data: string) => void; end: () => void } }, containerName: string) => void,
  onOutput?: (output: AgentOutput) => Promise<void>,
): Promise<AgentOutput> {
  const result = await runContainerAgent(
    group,
    input,
    onProcess,
    onOutput
  );

  return result;
}

/**
 * Run agent directly (original implementation)
 */
async function runAgentDirectly(
  group: RegisteredGroup,
  input: AgentInput,
  onProcess: (proc: ChildProcess | { kill: (signal: string) => void; stdin?: { write: (data: string) => void; end: () => void } }, containerName: string) => void,
  onOutput?: (output: AgentOutput) => Promise<void>,
): Promise<AgentOutput> {
  const startTime = Date.now();
  const safeName = group.folder.replace(/[^a-zA-Z0-9-]/g, '-');
  const agentId = `agent-${safeName}-${Date.now()}`;

  logger.info(
    { group: group.name, agentId, isMain: input.isMain },
    'Starting direct agent',
  );

  const groupDir = resolveGroupFolderPath(group.folder);
  fs.mkdirSync(groupDir, { recursive: true });

  const abortController = new AbortController();

  const mockProcess = {
    kill: (signal: string) => {
      logger.debug({ group: group.name, signal }, 'Kill signal received');
      abortController.abort();
    },
    stdin: {
      write: (data: string) => {
        const ipcDir = resolveGroupIpcPath(group.folder);
        const inputDir = path.join(ipcDir, 'input');
        fs.mkdirSync(inputDir, { recursive: true });
        const timestamp = Date.now();
        const filePath = path.join(inputDir, `${timestamp}.json`);
        fs.writeFileSync(filePath, JSON.stringify({ type: 'message', text: data }));
      },
      end: () => {
        const ipcDir = resolveGroupIpcPath(group.folder);
        const closeSentinel = path.join(ipcDir, 'input', '_close');
        fs.writeFileSync(closeSentinel, '');
      },
    },
  };

  onProcess(mockProcess, agentId);

  const timeoutMs = group.agentConfig?.timeout || AGENT_TIMEOUT;
  const timeoutId = setTimeout(() => {
    logger.warn({ group: group.name, agentId, timeoutMs }, 'Agent timeout, aborting');
    abortController.abort();
  }, timeoutMs);

  try {
    const result = await runAgentDirect(group, input, onOutput);

    const duration = Date.now() - startTime;
    logger.info(
      { group: group.name, agentId, duration, status: result.status },
      'Agent completed',
    );

    return result;
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    logger.error({ group: group.name, agentId, err }, 'Agent failed');
    return {
      status: 'error',
      result: null,
      error: errorMessage,
    };
  } finally {
    clearTimeout(timeoutId);
  }
}
