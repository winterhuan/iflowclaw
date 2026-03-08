/**
 * Channel Registry for iFlowClaw
 * Provides a unified interface for registering communication channels
 */
import { Channel } from '../types.js';
import { logger } from '../logger.js';

const channels: Channel[] = [];

export function registerChannel(factory: () => Channel | null): void {
  const channel = factory();
  if (channel) {
    channels.push(channel);
    logger.info({ channel: channel.name }, 'Channel registered');
  }
}

export function getChannels(): Channel[] {
  return channels;
}

export function findChannelForJid(jid: string): Channel | undefined {
  return channels.find(c => c.ownsJid(jid));
}

export async function connectAllChannels(): Promise<void> {
  for (const channel of channels) {
    try {
      await channel.connect();
      logger.info({ channel: channel.name }, 'Channel connected');
    } catch (err) {
      logger.error({ channel: channel.name, err }, 'Failed to connect channel');
    }
  }
}

export async function disconnectAllChannels(): Promise<void> {
  for (const channel of channels) {
    try {
      await channel.disconnect();
      logger.info({ channel: channel.name }, 'Channel disconnected');
    } catch (err) {
      logger.error({ channel: channel.name, err }, 'Failed to disconnect channel');
    }
  }
}
