import type { NewMessage, Channel, RegisteredGroup } from '../types.js';

/**
 * Extension System Types
 *
 * This module provides extension points for iFlowClaw.
 * Extensions are explicitly registered in src/extensions/index.ts
 * No automatic discovery or dynamic loading.
 */

export interface AgentInputContext {
  chatJid: string;
  group: RegisteredGroup;
  channel: Channel;
  messages: NewMessage[];
}

export interface AgentInputDraft {
  prompt: string;
  containerInput: Record<string, unknown>;
}

export interface MessageHandlerContext {
  chatJid: string;
  group?: RegisteredGroup;
  channel: Channel;
}

/**
 * Extension interface for modules that enhance agent input
 */
export interface AgentInputExtension {
  name: string;
  version: string;
  enhanceAgentInput?: (
    context: AgentInputContext,
    draft: AgentInputDraft,
  ) => void | Promise<void>;
  initialize?: () => void | Promise<void>;
}

/**
 * Extension interface for modules that handle messages
 */
export interface MessageHandlerExtension {
  name: string;
  version: string;
  handleMessage?: (
    message: NewMessage,
    context: MessageHandlerContext,
  ) => NewMessage | null | Promise<NewMessage | null>;
  initialize?: () => void | Promise<void>;
}
