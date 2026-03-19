/**
 * Container runtime abstraction for iFlow
 * Based on nanoclaw's container-runtime.ts
 * Simplified for iFlow's hybrid mode
 */
import { execSync } from 'child_process';
import fs from 'fs';
import os from 'os';

import { logger } from '../logger.js';

/** The container runtime binary name */
export const CONTAINER_RUNTIME_BIN = 'docker';

/** Hostname containers use to reach the host machine */
export const CONTAINER_HOST_GATEWAY = 'host.docker.internal';

/**
 * Address the credential proxy binds to
 */
export const PROXY_BIND_HOST =
  process.env.IFLOW_PROXY_HOST || detectProxyBindHost();

function detectProxyBindHost(): string {
  if (os.platform() === 'darwin') return '127.0.0.1';

  // WSL uses Docker Desktop
  if (fs.existsSync('/proc/sys/fs/binfmt_misc/WSLInterop')) return '127.0.0.1';

  // Bare-metal Linux: bind to docker0 bridge
  const ifaces = os.networkInterfaces();
  const docker0 = ifaces['docker0'];
  if (docker0) {
    const ipv4 = docker0.find((a) => a.family === 'IPv4');
    if (ipv4) return ipv4.address;
  }
  return '0.0.0.0';
}

/** CLI args for host gateway */
export function hostGatewayArgs(): string[] {
  if (os.platform() === 'linux') {
    return ['--add-host=host.docker.internal:host-gateway'];
  }
  return [];
}

/** CLI args for readonly bind mount */
export function readonlyMountArgs(
  hostPath: string,
  containerPath: string,
): string[] {
  return ['-v', `${hostPath}:${containerPath}:ro`];
}

/** Stop container command */
export function stopContainer(name: string): string {
  return `${CONTAINER_RUNTIME_BIN} stop -t 10 ${name}`;
}

/** Check if container runtime is available (for hybrid mode) */
export function isContainerRuntimeAvailable(): boolean {
  try {
    execSync(`${CONTAINER_RUNTIME_BIN} info`, {
      stdio: 'pipe',
      timeout: 5000,
    });
    return true;
  } catch {
    return false;
  }
}

/** Ensure container runtime is running */
export function ensureContainerRuntimeRunning(): void {
  try {
    execSync(`${CONTAINER_RUNTIME_BIN} info`, {
      stdio: 'pipe',
      timeout: 10000,
    });
    logger.debug('Container runtime ready');
  } catch (err) {
    logger.error({ err }, 'Docker not available');
    throw new Error(
      'Docker is required for container mode but not available. ' +
      'Please install Docker or switch to direct mode.'
    );
  }
}

/** Cleanup orphaned containers */
export function cleanupOrphans(): void {
  try {
    const output = execSync(
      `${CONTAINER_RUNTIME_BIN} ps --filter name=iflow-agent- --format '{{.Names}}'`,
      { stdio: ['pipe', 'pipe', 'pipe'], encoding: 'utf-8' }
    );
    const orphans = output.trim().split('\n').filter(Boolean);
    for (const name of orphans) {
      try {
        execSync(stopContainer(name), { stdio: 'pipe' });
      } catch {
        /* already stopped */
      }
    }
    if (orphans.length > 0) {
      logger.info(
        { count: orphans.length, names: orphans },
        'Stopped orphaned containers'
      );
    }
  } catch (err) {
    logger.warn({ err }, 'Failed to clean up orphaned containers');
  }
}