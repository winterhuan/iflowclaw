import { logger } from '../logger.js';

let loaded = false;

/**
 * Load Feishu channel module.
 */
export async function loadChannelModules(): Promise<void> {
  if (loaded) return;

  // Import Feishu channel - it will self-register via registerChannel()
  try {
    await import('./feishu.js');
    logger.debug({ channel: 'feishu' }, 'Channel loaded');
  } catch (err: any) {
    logger.error({ channel: 'feishu', error: err.message }, 'Failed to load channel');
    throw err;
  }

  loaded = true;
}
