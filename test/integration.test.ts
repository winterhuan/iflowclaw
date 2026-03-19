import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';
import fs from 'fs';
import path from 'path';
import { _switchToTestMode, processOnce, stopMessageLoop, _testChannels, loadState } from '../src/index';
import { setRegisteredGroup, storeMessage, storeChatMetadata } from '../src/db';
import { GROUPS_DIR, DATA_DIR, ASSISTANT_NAME } from '../src/config';
import { RegisteredGroup, NewMessage, Channel } from '../src/types';
import * as agentUtils from '../src/agents/utils.js';

const TEST_TIMEOUT = 120000; // Real tests need more time

// Conditional mocking based on environment
const SHOULD_MOCK = process.env.REAL_TEST !== 'true';

if (SHOULD_MOCK) {
  // Mock the hybrid runAgent directly
  vi.mock('../src/agents/utils', async (importOriginal) => {
    const original = await importOriginal<typeof agentUtils>();
    return {
      ...original,
      runAgent: vi.fn().mockImplementation((group) => {
        console.error(`DEBUG: Mock runAgent called for ${group.name}, mode: ${group.agentConfig?.executionMode}`);
        const groupDir = path.join(GROUPS_DIR, group.folder);
        fs.mkdirSync(groupDir, { recursive: true });
        fs.writeFileSync(path.join(groupDir, 'agent-called.txt'), group.agentConfig?.executionMode || 'auto');
        return Promise.resolve({
          status: 'success',
          result: 'Mocked response',
        });
      }),
    };
  });
}

// Mock channel
const mockChannel: Channel = {
  name: 'test-channel',
  connect: async () => {},
  disconnect: async () => {},
  isConnected: () => true,
  ownsJid: (jid: string) => true,
  sendMessage: async (jid: string, text: string) => {
    console.log(`Mock channel sent message to ${jid}: ${text}`);
  },
};

describe('Integration Tests - Execution Modes', () => {
  beforeAll(() => {
    _switchToTestMode();
    _testChannels.push(mockChannel);
  });

  afterAll(() => {
    stopMessageLoop();
    if (SHOULD_MOCK) {
      vi.restoreAllMocks();
    }
    _testChannels.length = 0;
  });

  it('Direct mode: should process message using direct runner', async () => {
    const groupInfo = {
      jid: 'direct@g.us',
      folder: 'test-direct',
      name: 'Test Direct',
      trigger: ASSISTANT_NAME,
      added_at: new Date().toISOString(),
    };

    // Setup
    const groupDir = path.join(GROUPS_DIR, groupInfo.folder);
    fs.mkdirSync(groupDir, { recursive: true });

    // Set execution mode to 'direct'
    setRegisteredGroup(groupInfo.jid, {
      ...groupInfo,
      agentConfig: { executionMode: 'direct' }
    } as RegisteredGroup);
    loadState();

    // Simulate message
    const mockMessage: NewMessage = {
      id: 'msg-direct',
      chat_jid: groupInfo.jid,
      content: `@${ASSISTANT_NAME} hello direct`,
      sender: 'user1',
      sender_name: 'User 1',
      timestamp: new Date().toISOString()
    };
    storeChatMetadata(mockMessage.chat_jid, new Date().toISOString(), groupInfo.name, 'test-channel', true);
    storeMessage(mockMessage);

    // Run
    await processOnce();

    // Wait for queue processing
    await new Promise(resolve => setTimeout(resolve, 2000));

    // Assert
    if (SHOULD_MOCK) {
      const callFile = path.join(groupDir, 'agent-called.txt');
      expect(fs.existsSync(callFile)).toBe(true);
      expect(fs.readFileSync(callFile, 'utf-8')).toBe('direct');
    } else {
      // Real test assertions
      // In real direct mode, it should have been processed by SDK
      console.log('Real direct test completed. Manual check of logs recommended.');
    }

    // Cleanup
    fs.rmSync(groupDir, { recursive: true, force: true });
  }, TEST_TIMEOUT);

  it('Container mode: should attempt to use container runner', async () => {
    const groupInfo = {
      jid: 'container@g.us',
      folder: 'test-container',
      name: 'Test Container',
      trigger: ASSISTANT_NAME,
      added_at: new Date().toISOString(),
    };

    // Setup
    const groupDir = path.join(GROUPS_DIR, groupInfo.folder);
    fs.mkdirSync(groupDir, { recursive: true });

    // Set execution mode to 'container'
    setRegisteredGroup(groupInfo.jid, {
      ...groupInfo,
      agentConfig: { executionMode: 'container' }
    } as RegisteredGroup);
    loadState();

    // Simulate message
    const mockMessage: NewMessage = {
      id: 'msg-container',
      chat_jid: groupInfo.jid,
      content: `@${ASSISTANT_NAME} hello container`,
      sender: 'user2',
      sender_name: 'User 2',
      timestamp: new Date().toISOString()
    };
    storeChatMetadata(mockMessage.chat_jid, new Date().toISOString(), groupInfo.name, 'test-channel', true);
    storeMessage(mockMessage);

    // Run
    await processOnce();

    // Wait for queue processing
    await new Promise(resolve => setTimeout(resolve, 2000));

    // Assert
    if (SHOULD_MOCK) {
      const callFile = path.join(groupDir, 'agent-called.txt');
      expect(fs.existsSync(callFile)).toBe(true);
      expect(fs.readFileSync(callFile, 'utf-8')).toBe('container');
    } else {
      console.log('Real container test completed. Manual check of logs recommended.');
    }

    // Cleanup
    fs.rmSync(groupDir, { recursive: true, force: true });
  }, TEST_TIMEOUT);

  it('Auto mode: should pick auto execution', async () => {
    const groupInfo = {
      jid: 'auto@g.us',
      folder: 'test-auto',
      name: 'Test Auto',
      trigger: ASSISTANT_NAME,
      added_at: new Date().toISOString(),
    };

    const groupDir = path.join(GROUPS_DIR, groupInfo.folder);
    fs.mkdirSync(groupDir, { recursive: true });

    // Set execution mode to 'auto' (default)
    setRegisteredGroup(groupInfo.jid, {
      ...groupInfo,
      agentConfig: { executionMode: 'auto' }
    } as RegisteredGroup);
    loadState();

    // Simulate message
    const mockMessage: NewMessage = {
      id: 'msg-auto',
      chat_jid: groupInfo.jid,
      content: `@${ASSISTANT_NAME} hello auto`,
      sender: 'user3',
      sender_name: 'User 3',
      timestamp: new Date().toISOString()
    };
    storeChatMetadata(mockMessage.chat_jid, new Date().toISOString(), groupInfo.name, 'test-channel', true);
    storeMessage(mockMessage);

    // Run
    await processOnce();

    // Wait for queue processing
    await new Promise(resolve => setTimeout(resolve, 2000));

    // Assert
    if (SHOULD_MOCK) {
      const callFile = path.join(groupDir, 'agent-called.txt');
      expect(fs.existsSync(callFile)).toBe(true);
      expect(fs.readFileSync(callFile, 'utf-8')).toBe('auto');
    } else {
      console.log('Real auto test completed. Manual check of logs recommended.');
    }

    // Cleanup
    fs.rmSync(groupDir, { recursive: true, force: true });
  }, TEST_TIMEOUT);
});
