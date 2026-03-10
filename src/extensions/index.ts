/**
 * Extension Registration
 *
 * All extensions are explicitly imported and registered here.
 * No automatic discovery - each extension must be manually added to the arrays below.
 *
 * To add a new extension:
 * 1. Create a new directory under src/extensions/ (e.g., src/extensions/my-feature/)
 * 2. Export an extension object from index.ts
 * 3. Import and add it to the appropriate array below
 */

import { logger } from '../logger.js';
import type {
  AgentInputContext,
  AgentInputDraft,
  AgentInputExtension,
  MessageHandlerContext,
  MessageHandlerExtension,
} from './types.js';
import type { NewMessage } from '../types.js';

// ========================================================================
// Agent Input Extensions
// These extensions can modify the agent input before it's sent to the container
// ========================================================================

import { imageVisionExtension } from './image-vision/index.js';

const agentInputExtensions: AgentInputExtension[] = [
  imageVisionExtension,
];

export async function runAgentInputExtensions(
  context: AgentInputContext,
  draft: AgentInputDraft,
): Promise<void> {
  for (const ext of agentInputExtensions) {
    if (ext.enhanceAgentInput) {
      await ext.enhanceAgentInput(context, draft);
    }
  }
}

// ========================================================================
// Message Handler Extensions
// These extensions can intercept and transform messages
// ========================================================================

const messageHandlerExtensions: MessageHandlerExtension[] = [
  // No message handlers for now
];

export async function runMessageHandlers(
  message: NewMessage,
  context: MessageHandlerContext,
): Promise<NewMessage | null> {
  let result: NewMessage | null = message;

  for (const ext of messageHandlerExtensions) {
    if (result === null) break;
    if (ext.handleMessage) {
      result = await ext.handleMessage(result, context);
    }
  }

  return result;
}

// ========================================================================
// Extension Initialization
// ========================================================================

export async function bootstrapExtensions(): Promise<void> {
  // Initialize all extensions
  for (const ext of agentInputExtensions) {
    try {
      if (ext.initialize) {
        await ext.initialize();
      }
    } catch (err: any) {
      logger.warn({ extension: ext.name, error: err.message }, 'Failed to initialize extension');
    }
  }

  for (const ext of messageHandlerExtensions) {
    try {
      if (ext.initialize) {
        await ext.initialize();
      }
    } catch (err: any) {
      logger.warn({ extension: ext.name, error: err.message }, 'Failed to initialize extension');
    }
  }
}

// Re-export types
export type {
  AgentInputContext,
  AgentInputDraft,
  AgentInputExtension,
  MessageHandlerExtension,
} from './types.js';
