/**
 * Memory Service
 * High-level memory operations for context management
 */
import {
  getHighImportanceMemories,
  listMemories,
  saveMemory,
  searchMemories,
  saveMemoryWithEmbedding,
  findSimilarMemory,
  searchMemoriesSemantic,
  isSemanticSearchAvailable,
  type Memory,
  type MemoryCategory,
} from './db.js';
import { getEmbedding, isEmbeddingEnabled } from './embeddings.js';
import { logger } from './logger.js';

/**
 * Get memory context formatted for prompt injection
 * Returns high-importance memories formatted as text
 */
export function getMemoryContext(
  groupFolder: string,
  limit: number = 10,
): string {
  logger.debug({ groupFolder, limit }, 'Getting memory context for prompt');

  try {
    const memories = getHighImportanceMemories(groupFolder, 4, limit);

    if (memories.length === 0) {
      logger.debug({ groupFolder }, 'No high importance memories found for context');
      return '';
    }

    const context = formatMemoriesForPrompt(memories);
    logger.info(
      { groupFolder, memoryCount: memories.length, contextLength: context.length },
      'Memory context generated successfully'
    );

    return context;
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

  logger.debug(
    { groupFolder, category, key: finalKey, hasCustomKey: !!key, importance, expiresInDays },
    'Saving memory with auto key'
  );

  const id = saveMemory({
    group_folder: groupFolder,
    category,
    key: finalKey,
    value,
    importance: importance ?? 3,
    expires_at: expiresAt,
  });

  logger.info(
    { groupFolder, category, key: finalKey, id },
    'Memory saved with auto key'
  );

  return id;
}

/**
 * Smart memory save with semantic deduplication
 * Automatically detects similar memories and updates instead of creating duplicates
 */
export async function saveMemorySmart(
  groupFolder: string,
  category: MemoryCategory,
  value: string,
  key?: string,
  importance?: number,
  expiresInDays?: number,
): Promise<string> {
  // Check if semantic search is available
  if (!isEmbeddingEnabled() || !isSemanticSearchAvailable()) {
    logger.debug('Semantic search not available, falling back to regular save');
    return saveMemoryWithAutoKey(groupFolder, category, value, key, importance, expiresInDays);
  }

  logger.debug({ groupFolder, category, hasCustomKey: !!key }, 'Saving memory with semantic deduplication');

  try {
    // Get embedding for the new memory
    const embedding = await getEmbedding(value);

    // Check for similar existing memory
    const similar = findSimilarMemory(groupFolder, embedding, 0.9);

    if (similar) {
      logger.info({ 
        groupFolder, 
        similarId: similar.id, 
        similarity: similar.similarity,
        key: similar.key 
      }, 'Similar memory found, updating existing');

      // Update existing memory with new value
      const expiresAt = expiresInDays
        ? new Date(Date.now() + expiresInDays * 24 * 60 * 60 * 1000).toISOString()
        : undefined;

      return saveMemoryWithEmbedding(
        {
          id: similar.id,
          group_folder: groupFolder,
          category,
          key: similar.key,
          value,  // Update with new value
          importance: importance ?? 3,
          expires_at: expiresAt,
        },
        embedding
      );
    }

    // No similar memory found, create new
    const finalKey = key || generateMemoryKey(category, value);
    const expiresAt = expiresInDays
      ? new Date(Date.now() + expiresInDays * 24 * 60 * 60 * 1000).toISOString()
      : undefined;

    const id = saveMemoryWithEmbedding(
      {
        group_folder: groupFolder,
        category,
        key: finalKey,
        value,
        importance: importance ?? 3,
        expires_at: expiresAt,
      },
      embedding
    );

    logger.info({ groupFolder, category, key: finalKey, id }, 'New memory saved with embedding');
    return id;

  } catch (err) {
    logger.error({ groupFolder, category, err }, 'Failed to save memory with semantic deduplication, falling back');
    return saveMemoryWithAutoKey(groupFolder, category, value, key, importance, expiresInDays);
  }
}

/**
 * Search memories using semantic similarity
 * Falls back to keyword search if semantic search is not available
 */
export async function searchMemoriesSemanticOrKeyword(
  groupFolder: string,
  query: string,
  category?: string,
  limit: number = 5,
): Promise<Array<Memory & { similarity?: number }>> {
  // Try semantic search first
  if (isEmbeddingEnabled() && isSemanticSearchAvailable()) {
    try {
      logger.debug({ groupFolder, query }, 'Attempting semantic search');
      const embedding = await getEmbedding(query);
      const results = searchMemoriesSemantic(groupFolder, embedding, limit);
      
      if (results.length > 0) {
        logger.info({ groupFolder, query, resultCount: results.length }, 'Semantic search successful');
        return results;
      }
    } catch (err) {
      logger.warn({ groupFolder, query, err }, 'Semantic search failed, falling back to keyword');
    }
  }

  // Fallback to keyword search
  logger.debug({ groupFolder, query }, 'Using keyword search');
  return searchMemories(groupFolder, query, category, limit);
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
  logger.debug({ groupFolder, query, category, limit }, 'Searching and formatting memories');

  const memories = searchMemories(groupFolder, query, category, limit);

  if (memories.length === 0) {
    logger.info({ groupFolder, query }, 'No memories found for search query');
    return '没有找到相关记忆。';
  }

  const lines: string[] = [];
  lines.push(`找到 ${memories.length} 条相关记忆：`);
  lines.push('');

  for (const mem of memories) {
    lines.push(`- [${mem.category}] ${mem.key}: ${mem.value}`);
  }

  const result = lines.join('\n');
  logger.info(
    { groupFolder, query, resultCount: memories.length, resultLength: result.length },
    'Search results formatted'
  );

  return result;
}

/**
 * List all memories and format results
 */
export function listAndFormatMemories(
  groupFolder: string,
  category?: string,
  limit: number = 20,
): string {
  logger.debug({ groupFolder, category, limit }, 'Listing and formatting memories');

  const memories = listMemories(groupFolder, category, limit);

  if (memories.length === 0) {
    logger.info({ groupFolder, category }, 'No memories found for list query');
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

  const result = lines.join('\n');
  logger.info(
    { groupFolder, category, resultCount: memories.length, resultLength: result.length },
    'Memory list formatted'
  );

  return result;
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
  logger.debug({ groupFolder, basePromptLength: basePrompt.length }, 'Building system prompt with memory');

  const memoryContext = getMemoryContext(groupFolder, 10);

  if (!memoryContext) {
    logger.info({ groupFolder }, 'No memory context, using base prompt only');
    return basePrompt;
  }

  const parts: string[] = [];
  parts.push(basePrompt);
  parts.push('');
  parts.push(memoryContext);

  const result = parts.join('\n');
  logger.info(
    { groupFolder, basePromptLength: basePrompt.length, finalPromptLength: result.length, memoryContextLength: memoryContext.length },
    'System prompt built with memory context'
  );

  return result;
}
