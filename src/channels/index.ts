/**
 * Channel barrel export
 * Import this module to trigger all channel self-registrations
 */

// Re-export registry functions
export { registerChannel, getChannels, findChannelForJid, connectAllChannels, disconnectAllChannels } from './registry.js';

// Import channel implementations to trigger self-registration
// Add new channels here as they are implemented
// import './whatsapp.js';
// import './telegram.js';
// import './discord.js';
// import './slack.js';
// import './feishu.js';
