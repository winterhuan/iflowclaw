/**
 * Agent utilities - shared helper functions
 */
import fs from 'fs';
import path from 'path';

import { AGENT_TIMEOUT } from './config.js';
import { resolveGroupFolderPath, resolveGroupIpcPath } from './group-folder.js';
import { logger } from './logger.js';
import { runAgentDirect, type AgentInput, type AgentOutput } from './agent-runner.js';
import { AvailableGroup, RegisteredGroup } from './types.js';

export { AgentInput, AgentOutput };

/**
 * Run agent directly using iFlow SDK
 */
export async function runAgent(
  group: RegisteredGroup,
  input: AgentInput,
  onProcess: (proc: { kill: (signal: string) => void; stdin?: { write: (data: string) => void; end: () => void } }, containerName: string) => void,
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
  const ipcDir = resolveGroupIpcPath(groupFolder);
  fs.mkdirSync(ipcDir, { recursive: true });
  const tasksFile = path.join(ipcDir, 'tasks_snapshot.json');
  const visibleTasks = isMain ? tasks : tasks.filter((t) => t.groupFolder === groupFolder);
  fs.writeFileSync(tasksFile, JSON.stringify({ tasks: visibleTasks }, null, 2));
}

/**
 * Write available groups snapshot for agent to read
 */
export function writeGroupsSnapshot(
  groupFolder: string,
  isMain: boolean,
  availableGroups: AvailableGroup[],
  registeredJids: Set<string>,
): void {
  const ipcDir = resolveGroupIpcPath(groupFolder);
  fs.mkdirSync(ipcDir, { recursive: true });
  const groupsFile = path.join(ipcDir, 'available_groups.json');
  const data = {
    groups: isMain ? availableGroups : [],
    registered: Array.from(registeredJids),
    lastSync: new Date().toISOString(),
  };
  fs.writeFileSync(groupsFile, JSON.stringify(data, null, 2));
}

// Backwards compatibility aliases
export type ContainerInput = AgentInput;
export type ContainerOutput = AgentOutput;
export const runContainerAgent = runAgent;
