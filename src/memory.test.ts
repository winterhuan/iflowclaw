import { describe, it, expect, beforeEach } from 'vitest';
import {
  _initTestDatabase,
  saveMemory,
  getMemory,
  searchMemories,
  listMemories,
  deleteMemory,
  cleanupExpiredMemories,
  getHighImportanceMemories,
} from './db.js';
import {
  getMemoryContext,
  formatMemoriesForPrompt,
  saveMemoryWithAutoKey,
} from './memory.js';

describe('Memory System', () => {
  beforeEach(() => {
    _initTestDatabase();
  });

  describe('Database Operations', () => {
    it('should save and retrieve a memory', () => {
      const id = saveMemory({
        group_folder: 'test-group',
        category: 'fact',
        key: 'user_name',
        value: '张三',
        importance: 4,
      });

      expect(id).toBeDefined();
      expect(id.startsWith('mem-')).toBe(true);

      const memory = getMemory('test-group', 'user_name');
      expect(memory).toBeDefined();
      expect(memory?.value).toBe('张三');
      expect(memory?.category).toBe('fact');
      expect(memory?.importance).toBe(4);
    });

    it('should update existing memory with same key', () => {
      saveMemory({
        group_folder: 'test-group',
        category: 'fact',
        key: 'user_name',
        value: '张三',
        importance: 3,
      });

      saveMemory({
        group_folder: 'test-group',
        category: 'fact',
        key: 'user_name',
        value: '李四',
        importance: 5,
      });

      const memory = getMemory('test-group', 'user_name');
      expect(memory?.value).toBe('李四');
      expect(memory?.importance).toBe(5);
    });

    it('should search memories by query', () => {
      saveMemory({
        group_folder: 'test-group',
        category: 'fact',
        key: 'company',
        value: '阿里巴巴',
        importance: 4,
      });

      saveMemory({
        group_folder: 'test-group',
        category: 'preference',
        key: 'style',
        value: '喜欢简洁风格',
        importance: 3,
      });

      const results = searchMemories('test-group', '阿里');
      expect(results).toHaveLength(1);
      expect(results[0].key).toBe('company');
    });

    it('should list memories with category filter', () => {
      saveMemory({
        group_folder: 'test-group',
        category: 'fact',
        key: 'name',
        value: '张三',
        importance: 3,
      });

      saveMemory({
        group_folder: 'test-group',
        category: 'task',
        key: 'todo',
        value: '完成任务',
        importance: 4,
      });

      const allMemories = listMemories('test-group');
      expect(allMemories).toHaveLength(2);

      const facts = listMemories('test-group', 'fact');
      expect(facts).toHaveLength(1);
      expect(facts[0].category).toBe('fact');
    });

    it('should delete memory', () => {
      saveMemory({
        group_folder: 'test-group',
        category: 'fact',
        key: 'temp',
        value: '临时数据',
        importance: 1,
      });

      const deleted = deleteMemory('test-group', 'temp');
      expect(deleted).toBe(true);

      const memory = getMemory('test-group', 'temp');
      expect(memory).toBeUndefined();
    });

    it('should get high importance memories', () => {
      saveMemory({
        group_folder: 'test-group',
        category: 'fact',
        key: 'low',
        value: '低重要性',
        importance: 2,
      });

      saveMemory({
        group_folder: 'test-group',
        category: 'decision',
        key: 'high',
        value: '重要决策',
        importance: 5,
      });

      const highMemories = getHighImportanceMemories('test-group', 4);
      expect(highMemories).toHaveLength(1);
      expect(highMemories[0].key).toBe('high');
    });

    it('should cleanup expired memories', () => {
      const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
      
      saveMemory({
        group_folder: 'test-group',
        category: 'fact',
        key: 'expired',
        value: '已过期',
        importance: 3,
        expires_at: yesterday,
      });

      saveMemory({
        group_folder: 'test-group',
        category: 'fact',
        key: 'valid',
        value: '有效',
        importance: 3,
      });

      const cleaned = cleanupExpiredMemories();
      expect(cleaned).toBe(1);

      const memories = listMemories('test-group');
      expect(memories).toHaveLength(1);
      expect(memories[0].key).toBe('valid');
    });
  });

  describe('Memory Service', () => {
    it('should format memories for prompt', () => {
      saveMemory({
        group_folder: 'test-group',
        category: 'fact',
        key: 'name',
        value: '张三',
        importance: 5,
      });

      const context = getMemoryContext('test-group');
      expect(context).toContain('历史记忆');
      expect(context).toContain('张三');
      expect(context).toContain('事实信息');
    });

    it('should return empty string when no high importance memories', () => {
      saveMemory({
        group_folder: 'test-group',
        category: 'fact',
        key: 'low',
        value: '低重要性',
        importance: 2,
      });

      const context = getMemoryContext('test-group');
      expect(context).toBe('');
    });

    it('should save memory with auto-generated key', () => {
      const id = saveMemoryWithAutoKey(
        'test-group',
        'preference',
        '喜欢简洁回答',
        undefined,
        4,
      );

      expect(id).toBeDefined();
      
      const memories = listMemories('test-group', 'preference');
      expect(memories).toHaveLength(1);
      expect(memories[0].value).toBe('喜欢简洁回答');
      expect(memories[0].key.startsWith('preference-')).toBe(true);
    });
  });
});
