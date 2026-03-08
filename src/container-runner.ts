/**
 * Container Runner for iFlowClaw
 * Spawns agent execution in containers using iFlow SDK
 * 
 * Authentication:
 * - OAuth: Mounts ~/.iflow/ into container for automatic credential discovery
 * - API Key: Passes via stdin secrets (for headless environments)
 */
import { ChildProcess, exec, spawn } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';

import {
  CONTAINER_IMAGE,
  CONTAINER_MAX_OUTPUT_SIZE,
  CONTAINER_TIMEOUT,
  DATA_DIR,
  GROUPS_DIR,
  IDLE_TIMEOUT,
  TIMEZONE,
  IFLOW_API_KEY,
  IFLOW_BASE_URL,
  IFLOW_MODEL_NAME,
} from './config.js';
import { logger } from './logger.js';
import { RegisteredGroup } from './types.js';

const OUTPUT_START_MARKER = '---IFLOWCLAW_OUTPUT_START---';
const OUTPUT_END_MARKER = '---IFLOWCLAW_OUTPUT_END---';

export interface ContainerInput {
  prompt: string;
  sessionId?: string;
  groupFolder: string;
  chatJid: string;
  isMain: boolean;
  isScheduledTask?: boolean;
  assistantName?: string;
  secrets?: Record<string, string>;
}

export interface ContainerOutput {
  status: 'success' | 'error';
  result: string | null;
  newSessionId?: string;
  error?: string;
}

interface VolumeMount {
  hostPath: string;
  containerPath: string;
  readonly: boolean;
}

function resolveGroupFolderPath(folder: string): string {
  return path.join(GROUPS_DIR, folder);
}

function resolveGroupIpcPath(folder: string): string {
  return path.join(DATA_DIR, 'ipc', folder);
}

function buildVolumeMounts(group: RegisteredGroup, isMain: boolean): VolumeMount[] {
  const mounts: VolumeMount[] = [];
  const projectRoot = process.cwd();
  const groupDir = resolveGroupFolderPath(group.folder);
  const homeDir = os.homedir();

  if (isMain) {
    mounts.push({
      hostPath: projectRoot,
      containerPath: '/workspace/project',
      readonly: true,
    });
    mounts.push({
      hostPath: groupDir,
      containerPath: '/workspace/group',
      readonly: false,
    });
  } else {
    mounts.push({
      hostPath: groupDir,
      containerPath: '/workspace/group',
      readonly: false,
    });
    const globalDir = path.join(GROUPS_DIR, 'global');
    if (fs.existsSync(globalDir)) {
      mounts.push({
        hostPath: globalDir,
        containerPath: '/workspace/global',
        readonly: true,
      });
    }
  }

  // Per-group IPC namespace
  const groupIpcDir = resolveGroupIpcPath(group.folder);
  fs.mkdirSync(path.join(groupIpcDir, 'input'), { recursive: true });
  mounts.push({
    hostPath: groupIpcDir,
    containerPath: '/workspace/ipc',
    readonly: false,
  });

  // Mount iFlow config directory for OAuth authentication
  // This allows the SDK to use credentials from `iflow login`
  const iflowConfigDir = path.join(homeDir, '.iflow');
  if (fs.existsSync(iflowConfigDir)) {
    mounts.push({
      hostPath: iflowConfigDir,
      containerPath: '/home/node/.iflow',
      readonly: true, // Read-only for security
    });
    logger.debug('Mounting ~/.iflow for OAuth authentication');
  } else {
    logger.debug('~/.iflow not found, will require API key');
  }

  return mounts;
}

/**
 * Read secrets from environment or return empty.
 * If IFLOW_API_KEY is set, it will be passed to the container.
 * Otherwise, the container will use OAuth credentials from ~/.iflow/
 */
function readSecrets(): Record<string, string> {
  const secrets: Record<string, string> = {};
  if (IFLOW_API_KEY) {
    secrets.IFLOW_API_KEY = IFLOW_API_KEY;
    logger.debug('Using API key authentication');
  }
  if (IFLOW_BASE_URL) secrets.IFLOW_BASE_URL = IFLOW_BASE_URL;
  if (IFLOW_MODEL_NAME) secrets.IFLOW_MODEL_NAME = IFLOW_MODEL_NAME;
  return secrets;
}

function buildContainerArgs(mounts: VolumeMount[], containerName: string): string[] {
  const args: string[] = ['run', '-i', '--rm', '--name', containerName];
  args.push('-e', `TZ=${TIMEZONE}`);

  const hostUid = process.getuid?.();
  const hostGid = process.getgid?.();
  if (hostUid != null && hostUid !== 0 && hostUid !== 1000) {
    args.push('--user', `${hostUid}:${hostGid}`);
    args.push('-e', 'HOME=/home/node');
  }

  for (const mount of mounts) {
    const roFlag = mount.readonly ? ':ro' : '';
    args.push('-v', `${mount.hostPath}:${mount.containerPath}${roFlag}`);
  }

  args.push(CONTAINER_IMAGE);
  return args;
}

export async function runContainerAgent(
  group: RegisteredGroup,
  input: ContainerInput,
  onProcess: (proc: ChildProcess, containerName: string) => void,
  onOutput?: (output: ContainerOutput) => Promise<void>,
): Promise<ContainerOutput> {
  const startTime = Date.now();
  const groupDir = resolveGroupFolderPath(group.folder);
  fs.mkdirSync(groupDir, { recursive: true });

  const mounts = buildVolumeMounts(group, input.isMain);
  const safeName = group.folder.replace(/[^a-zA-Z0-9-]/g, '-');
  const containerName = `iflowclaw-${safeName}-${Date.now()}`;
  const containerArgs = buildContainerArgs(mounts, containerName);

  logger.info({ group: group.name, containerName, isMain: input.isMain }, 'Spawning container agent');

  return new Promise((resolve) => {
    const container = spawn('docker', containerArgs, { stdio: ['pipe', 'pipe', 'pipe'] });
    onProcess(container, containerName);

    let stdout = '';
    let stderr = '';
    let parseBuffer = '';
    let outputChain = Promise.resolve();

    // Pass secrets via stdin (empty if using OAuth)
    input.secrets = readSecrets();
    container.stdin.write(JSON.stringify(input));
    container.stdin.end();
    delete input.secrets;

    container.stdout.on('data', (data) => {
      const chunk = data.toString();
      if (stdout.length < CONTAINER_MAX_OUTPUT_SIZE) {
        stdout += chunk;
      }

      if (onOutput) {
        parseBuffer += chunk;
        let startIdx: number;
        while ((startIdx = parseBuffer.indexOf(OUTPUT_START_MARKER)) !== -1) {
          const endIdx = parseBuffer.indexOf(OUTPUT_END_MARKER, startIdx);
          if (endIdx === -1) break;

          const jsonStr = parseBuffer.slice(startIdx + OUTPUT_START_MARKER.length, endIdx).trim();
          parseBuffer = parseBuffer.slice(endIdx + OUTPUT_END_MARKER.length);

          try {
            const parsed: ContainerOutput = JSON.parse(jsonStr);
            outputChain = outputChain.then(() => onOutput(parsed));
          } catch (err) {
            logger.warn({ error: err }, 'Failed to parse output chunk');
          }
        }
      }
    });

    container.stderr.on('data', (data) => {
      stderr += data.toString();
    });

    let timedOut = false;
    const timeoutMs = Math.max(group.containerConfig?.timeout || CONTAINER_TIMEOUT, IDLE_TIMEOUT + 30000);
    const timeout = setTimeout(() => {
      timedOut = true;
      logger.error({ containerName }, 'Container timeout');
      exec(`docker stop ${containerName}`, { timeout: 15000 }, () => {
        container.kill('SIGKILL');
      });
    }, timeoutMs);

    container.on('close', (code) => {
      clearTimeout(timeout);

      if (timedOut) {
        resolve({ status: 'error', result: null, error: 'Container timed out' });
        return;
      }

      if (code !== 0) {
        resolve({ status: 'error', result: null, error: `Container exited with code ${code}: ${stderr.slice(-200)}` });
        return;
      }

      if (onOutput) {
        outputChain.then(() => resolve({ status: 'success', result: null }));
        return;
      }

      try {
        const startIdx = stdout.indexOf(OUTPUT_START_MARKER);
        const endIdx = stdout.indexOf(OUTPUT_END_MARKER);
        if (startIdx !== -1 && endIdx !== -1) {
          const jsonLine = stdout.slice(startIdx + OUTPUT_START_MARKER.length, endIdx).trim();
          resolve(JSON.parse(jsonLine));
        } else {
          resolve({ status: 'error', result: null, error: 'No output markers found' });
        }
      } catch (err) {
        resolve({ status: 'error', result: null, error: `Parse error: ${err}` });
      }
    });

    container.on('error', (err) => {
      clearTimeout(timeout);
      resolve({ status: 'error', result: null, error: err.message });
    });
  });
}
