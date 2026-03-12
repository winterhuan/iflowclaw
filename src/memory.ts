/**
 * Memory Service
 * High-level memory operations for context management
 */
import {
  getHighImportanceMemories,
  listMemories,
  saveMemory,
  searchMemories,
  type Memory,
  type MemoryCategory,
} from './db.js';
import { logger } from './logger.js';

/**
 * Get memory context formatted for prompt injection
 * Returns high-importance memories formatted as text
 */
export function getMemoryContext(
  groupFolder: string,
  limit: number = 10,
): string {
  try {
    const memories = getHighImportanceMemories(groupFolder, 4, limit);

    if (memories.length === 0) {
      return '';
    }

    return formatMemoriesForPrompt(memories);
  } catch (err) {
    logger.error({ groupFolder, err }, 'Failed to get memory context');
    return '';
  }
}

/**
 * Format memories for inclusion in system prompt
 */
export function formatMemoriesForPrompt(memories: Memory[]): string {
  if (memories.length === 0) {
    return '';
  }

  const lines: string[] = [];
  lines.push('=== 历史记忆 ===');
  lines.push('');

  // Group by category
  const byCategory = new Map<string, Memory[]>();
  for (const mem of memories) {
    const list = byCategory.get(mem.category) || [];
    list.push(mem);
    byCategory.set(mem.category, list);
  }

  // Format each category
  const categoryNames: Record<string, string> = {
    fact: '事实信息',
    preference: '用户偏好',
    decision: '重要决策',
    task: '待办事项',
    summary: '会话摘要',
    context: '上下文信息',
  };

  for (const [category, items] of byCategory) {
    const name = categoryNames[category] || category;
    lines.push(`【${name}】`);
    for (const mem of items) {
      lines.push(`- ${mem.key}: ${mem.value}`);
    }
    lines.push('');
  }

  return lines.join('\n');
}

/**
 * Save a memory with auto-generated key if not provided
 */
export function saveMemoryWithAutoKey(
  groupFolder: string,
  category: MemoryCategory,
  value: string,
  key?: string,
  importance?: number,
  expiresInDays?: number,
): string {
  const finalKey = key || generateMemoryKey(category, value);
  const expiresAt = expiresInDays
    ? new Date(Date.now() + expiresInDays * 24 * 60 * 60 * 1000).toISOString()
    : undefined;

  return saveMemory({
    group_folder: groupFolder,
    category,
    key: finalKey,
    value,
    importance: importance ?? 3,
    expires_at: expiresAt,
  });
}

/**
 * Search memories and format results
 */
export function searchAndFormatMemories(
  groupFolder: string,
  query: string,
  category?: string,
  limit: number = 5,
): string {
  const memories = searchMemories(groupFolder, query, category, limit);

  if (memories.length === 0) {
    return '没有找到相关记忆。';
  }

  const lines: string[] = [];
  lines.push(`找到 ${memories.length} 条相关记忆：`);
  lines.push('');

  for (const mem of memories) {
    lines.push(`- [${mem.category}] ${mem.key}: ${mem.value}`);
  }

  return lines.join('\n');
}

/**
 * List all memories and format results
 */
export function listAndFormatMemories(
  groupFolder: string,
  category?: string,
  limit: number = 20,
): string {
  const memories = listMemories(groupFolder, category, limit);

  if (memories.length === 0) {
    return category
      ? `该群组没有类别为 "${category}" 的记忆。`
      : '该群组没有保存任何记忆。';
  }

  const lines: string[] = [];
  lines.push(
    category
      ? `类别 "${category}" 的记忆（共 ${memories.length} 条）：`
      : `所有记忆（共 ${memories.length} 条）：`,
  );
  lines.push('');

  for (const mem of memories) {
    const importance = '⭐'.repeat(mem.importance);
    lines.push(`- ${mem.key} ${importance}`);
    lines.push(`  ${mem.value}`);
    if (mem.expires_at) {
      const days = Math.ceil(
        (new Date(mem.expires_at).getTime() - Date.now()) / (24 * 60 * 60 * 1000),
      );
      lines.push(`  (还有 ${days} 天过期)`);
    }
    lines.push('');
  }

  return lines.join('\n');
}

/**
 * Generate a memory key from category and value
 */
function generateMemoryKey(category: string, value: string): string {
  // Take first 30 chars of value and sanitize
  const sanitized = value
    .slice(0, 30)
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .toLowerCase();
  return `${category}-${sanitized}-${Date.now().toString(36).slice(-4)}`;
}

/**
 * Build system prompt with memory context
 */
export function buildSystemPromptWithMemory(
  basePrompt: string,
  groupFolder: string,
): string {
  const memoryContext = getMemoryContext(groupFolder, 10);

  if (!memoryContext) {
    return basePrompt;
  }

  const parts: string[] = [];
  parts.push(basePrompt);
  parts.push('');
  parts.push(memoryContext);

  return parts.join('\n');
}
