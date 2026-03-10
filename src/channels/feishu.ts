import * as lark from '@larksuiteoapi/node-sdk';

import { ASSISTANT_NAME, TRIGGER_PATTERN } from '../config.js';
import { readEnvFile } from '../env.js';
import { logger } from '../logger.js';
import { registerChannel, ChannelOpts } from './registry.js';
import {
  Channel,
  OnChatMetadata,
  OnInboundMessage,
  RegisteredGroup,
} from '../types.js';

export interface FeishuChannelOpts {
  onMessage: OnInboundMessage;
  onChatMetadata: OnChatMetadata;
  registeredGroups: () => Record<string, RegisteredGroup>;
  autoRegisterGroup?: (jid: string, name: string, channel: string) => boolean;
}

/**
 * Feishu (Lark) channel implementation using WebSocket long connection.
 *
 * Uses the Lark SDK's WSClient for event streaming — no public webhook
 * URL or encryption configuration required.
 */
export class FeishuChannel implements Channel {
  name = 'feishu';

  private client: lark.Client;
  private wsClient: lark.WSClient;
  private eventDispatcher: lark.EventDispatcher;
  private connected = false;
  private opts: FeishuChannelOpts;

  constructor(appId: string, appSecret: string, opts: FeishuChannelOpts) {
    this.opts = opts;

    this.client = new lark.Client({
      appId,
      appSecret,
      appType: lark.AppType.SelfBuild,
      domain: lark.Domain.Feishu,
    });

    this.wsClient = new lark.WSClient({
      appId,
      appSecret,
      domain: lark.Domain.Feishu,
      loggerLevel: lark.LoggerLevel.info,
    });

    this.eventDispatcher = new lark.EventDispatcher({
      verificationToken: '',
      encryptKey: '',
      loggerLevel: lark.LoggerLevel.info,
    }).register({
      'im.message.receive_v1': this.handleMessage.bind(this),
    });
  }

  async connect(): Promise<void> {
    await this.wsClient.start({
      eventDispatcher: this.eventDispatcher,
    });
    this.connected = true;
    logger.info('Feishu long connection established');
    console.log('\n  Feishu bot connected via WebSocket long connection\n');
  }

  async sendMessage(jid: string, text: string): Promise<void> {
    if (!this.connected) {
      logger.warn('Feishu channel not connected');
      return;
    }

    try {
      const chatId = jid.replace(/^feishu:/, '');

      await this.client.im.message.create({
        params: { receive_id_type: 'chat_id' },
        data: {
          receive_id: chatId,
          msg_type: 'text',
          content: JSON.stringify({ text }),
        },
      });

      logger.info({ jid, length: text.length }, 'Feishu message sent');
    } catch (err) {
      logger.error({ jid, err }, 'Failed to send Feishu message');
    }
  }

  isConnected(): boolean {
    return this.connected;
  }

  ownsJid(jid: string): boolean {
    return jid.startsWith('feishu:');
  }

  async disconnect(): Promise<void> {
    this.connected = false;
    logger.info('Feishu channel disconnected');
  }

  async setTyping(_jid: string, _isTyping: boolean): Promise<void> {
    // Feishu doesn't support typing indicators
  }

  private async handleMessage(data: any): Promise<void> {
    try {
      const message = data.message;
      const sender = data.sender;

      if (!message || !sender) {
        logger.warn({ data }, 'Missing message or sender in Feishu event');
        return;
      }

      const rawChatId = message.chat_id;
      const chatJid = `feishu:${rawChatId}`;
      const messageType = message.message_type;
      const messageId = message.message_id;
      const timestamp = new Date(parseInt(message.create_time)).toISOString();
      const senderId =
        sender.sender_id?.user_id || sender.sender_id?.open_id || '';

      // Store chat metadata for discovery
      // Feishu: treat all chats as groups for management purposes
      const isGroup = true;
      this.opts.onChatMetadata(
        chatJid,
        new Date().toISOString(),
        undefined,
        'feishu',
        isGroup,
      );

      // Only deliver for registered groups
      let group = this.opts.registeredGroups()[chatJid];
      if (!group) {
        // Try auto-register as main group on first message
        const chatName = message.chat_id || rawChatId;
        if (this.opts.autoRegisterGroup?.(chatJid, chatName, 'feishu')) {
          group = this.opts.registeredGroups()[chatJid];
          logger.info({ chatJid, name: chatName }, 'Auto-registered Feishu chat as main group');
        } else {
          logger.info({ chatJid, sender: senderId, messageType }, 'Message from unregistered Feishu chat - use this JID to register the group');
          return;
        }
      }

      // Handle non-text messages as placeholders
      if (messageType !== 'text') {
        const placeholders: Record<string, string> = {
          image: '[Photo]',
          video: '[Video]',
          audio: '[Audio]',
          file: '[File]',
          sticker: '[Sticker]',
          location: '[Location]',
        };
        const placeholder = placeholders[messageType] || `[${messageType}]`;

        this.opts.onMessage(chatJid, {
          id: messageId,
          chat_jid: chatJid,
          sender: senderId,
          sender_name: senderId,
          content: placeholder,
          timestamp,
          is_from_me: false,
        });
        return;
      }

      const parsed = JSON.parse(message.content);
      let text: string = parsed.text;

      // Replace mention placeholders (@_user_1 etc.) with actual names.
      // Translate bot @mentions into TRIGGER_PATTERN format so the router
      // recognises them, following the same approach as Telegram.
      let botMentioned = false;
      if (message.mentions && Array.isArray(message.mentions)) {
        for (const mention of message.mentions) {
          if (mention.key && mention.name) {
            const isBotMention =
              mention.name.toLowerCase() === ASSISTANT_NAME.toLowerCase();
            if (isBotMention) {
              botMentioned = true;
              text = text.replace(mention.key, `@${ASSISTANT_NAME}`);
            } else {
              text = text.replace(mention.key, `@${mention.name}`);
            }
          }
        }
      }

      if (botMentioned && !TRIGGER_PATTERN.test(text)) {
        text = `@${ASSISTANT_NAME} ${text}`;
      }

      this.opts.onMessage(chatJid, {
        id: messageId,
        chat_jid: chatJid,
        sender: senderId,
        sender_name: senderId,
        content: text,
        timestamp,
        is_from_me: false,
      });

      logger.info({ chatJid, sender: senderId }, 'Feishu message stored');
    } catch (err) {
      logger.error({ err }, 'Error handling Feishu message');
    }
  }
}

registerChannel('feishu', (opts: ChannelOpts) => {
  const envVars = readEnvFile(['FEISHU_APP_ID', 'FEISHU_APP_SECRET']);
  const appId = process.env.FEISHU_APP_ID || envVars.FEISHU_APP_ID || '';
  const appSecret =
    process.env.FEISHU_APP_SECRET || envVars.FEISHU_APP_SECRET || '';
  if (!appId || !appSecret) {
    logger.warn('Feishu: FEISHU_APP_ID or FEISHU_APP_SECRET not set');
    return null;
  }
  return new FeishuChannel(appId, appSecret, opts);
});
