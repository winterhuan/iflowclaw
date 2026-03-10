/**
 * Session History Management
 * Handles saving conversation history, generating summaries, and context injection
 */
import fs from 'fs';
import path from 'path';

import { logger } from './logger.js';
import { resolveGroupFolderPath } from './group-folder.js';

export interface ConversationMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

export interface ConversationHistory {
  sessionId: string;
  messages: ConversationMessage[];
  startTime: string;
  endTime: string;
  messageCount: number;
}

export interface SessionSummary {
  sessionId: string;
  summary: string;
  keyPoints: string[];
  messageCount: number;
  generatedAt: string;
}

const MAX_MESSAGES_PER_FILE = 1000; // 单个文件最多保存的消息数

/**
 * Get the conversations directory for a group
 */
function getConversationsDir(groupFolder: string): string {
  const groupDir = resolveGroupFolderPath(groupFolder);
  const convDir = path.join(groupDir, 'conversations');
  fs.mkdirSync(convDir, { recursive: true });
  return convDir;
}

/**
 * Save conversation history to file
 */
export function saveConversationHistory(
  groupFolder: string,
  history: ConversationHistory,
): string {
  const convDir = getConversationsDir(groupFolder);
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const filename = `history_${timestamp}_${history.sessionId.slice(0, 8)}.json`;
  const filepath = path.join(convDir, filename);

  fs.writeFileSync(filepath, JSON.stringify(history, null, 2));
  logger.info({ groupFolder, filepath, messageCount: history.messageCount }, 'Conversation history saved');
  
  return filepath;
}

/**
 * Save session summary to file
 */
export function saveSessionSummary(
  groupFolder: string,
  summary: SessionSummary,
): string {
  const convDir = getConversationsDir(groupFolder);
  const filename = `summary_${summary.sessionId.slice(0, 8)}.json`;
  const filepath = path.join(convDir, filename);

  fs.writeFileSync(filepath, JSON.stringify(summary, null, 2));
  logger.info({ groupFolder, filepath }, 'Session summary saved');
  
  return filepath;
}

/**
 * Get recent conversation files
 */
export function getRecentConversations(groupFolder: string, limit: number = 10): string[] {
  try {
    const convDir = getConversationsDir(groupFolder);
    const files = fs.readdirSync(convDir)
      .filter(f => f.startsWith('history_') && f.endsWith('.json'))
      .map(f => ({
        name: f,
        path: path.join(convDir, f),
        mtime: fs.statSync(path.join(convDir, f)).mtime,
      }))
      .sort((a, b) => b.mtime.getTime() - a.mtime.getTime())
      .slice(0, limit)
      .map(f => f.path);
    
    return files;
  } catch {
    return [];
  }
}

/**
 * Get the most recent summary file
 */
export function getLatestSummary(groupFolder: string): SessionSummary | undefined {
  try {
    const convDir = getConversationsDir(groupFolder);
    const files = fs.readdirSync(convDir)
      .filter(f => f.startsWith('summary_') && f.endsWith('.json'))
      .map(f => ({
        name: f,
        path: path.join(convDir, f),
        mtime: fs.statSync(path.join(convDir, f)).mtime,
      }))
      .sort((a, b) => b.mtime.getTime() - a.mtime.getTime());
    
    if (files.length === 0) return undefined;
    
    const content = fs.readFileSync(files[0].path, 'utf-8');
    return JSON.parse(content) as SessionSummary;
  } catch {
    return undefined;
  }
}

/**
 * Load conversation history from file
 */
export function loadConversationHistory(filepath: string): ConversationHistory | undefined {
  try {
    const content = fs.readFileSync(filepath, 'utf-8');
    return JSON.parse(content) as ConversationHistory;
  } catch {
    return undefined;
  }
}

/**
 * Format conversation for AI summary generation
 */
export function formatConversationForSummary(messages: ConversationMessage[]): string {
  return messages.map(m => {
    const time = new Date(m.timestamp).toLocaleString('zh-CN');
    return `[${time}] ${m.role}: ${m.content}`;
  }).join('\n');
}

/**
 * Build context prompt from summary and recent messages
 */
export function buildContextPrompt(
  summary?: SessionSummary,
  recentMessages?: ConversationMessage[],
): string {
  const parts: string[] = [];
  
  if (summary) {
    parts.push('=== 历史对话摘要 ===');
    parts.push(summary.summary);
    if (summary.keyPoints && summary.keyPoints.length > 0) {
      parts.push('\n关键信息：');
      summary.keyPoints.forEach((point, i) => {
        parts.push(`${i + 1}. ${point}`);
      });
    }
    parts.push('');
  }
  
  if (recentMessages && recentMessages.length > 0) {
    parts.push('=== 最近消息 ===');
    recentMessages.slice(-10).forEach(m => {
      parts.push(`${m.role}: ${m.content}`);
    });
    parts.push('');
  }
  
  if (parts.length > 0) {
    parts.push('=== 新消息 ===');
    return parts.join('\n');
  }
  
  return '';
}

/**
 * Collect messages for history from formatted prompt
 */
export function extractMessagesFromPrompt(prompt: string): ConversationMessage[] {
  const messages: ConversationMessage[] = [];
  
  // Simple extraction - look for message patterns in the prompt
  const lines = prompt.split('\n');
  let currentRole: 'user' | 'assistant' | null = null;
  let currentContent: string[] = [];
  
  for (const line of lines) {
    // Check for message sender patterns
    const userMatch = line.match(/<message[^>]*sender="([^"]+)"[^>]*>(.*)<\/message>/);
    if (userMatch) {
      if (currentRole && currentContent.length > 0) {
        messages.push({
          role: currentRole,
          content: currentContent.join('\n'),
          timestamp: new Date().toISOString(),
        });
      }
      currentRole = 'user';
      currentContent = [userMatch[2]];
    } else if (line.trim() && currentRole) {
      currentContent.push(line);
    }
  }
  
  // Add last message
  if (currentRole && currentContent.length > 0) {
    messages.push({
      role: currentRole,
      content: currentContent.join('\n'),
      timestamp: new Date().toISOString(),
    });
  }
  
  return messages;
}

/**
 * Clean up old conversation files (keep last 30 days)
 */
export function cleanupOldConversations(groupFolder: string, maxAgeDays: number = 30): void {
  try {
    const convDir = getConversationsDir(groupFolder);
    const cutoff = Date.now() - maxAgeDays * 24 * 60 * 60 * 1000;
    
    const files = fs.readdirSync(convDir)
      .filter(f => f.endsWith('.json'))
      .map(f => ({
        name: f,
        path: path.join(convDir, f),
        mtime: fs.statSync(path.join(convDir, f)).mtime,
      }));
    
    let deleted = 0;
    for (const file of files) {
      if (file.mtime.getTime() < cutoff) {
        fs.unlinkSync(file.path);
        deleted++;
      }
    }
    
    if (deleted > 0) {
      logger.info({ groupFolder, deleted }, 'Old conversation files cleaned up');
    }
  } catch (err) {
    logger.warn({ groupFolder, err }, 'Failed to cleanup old conversations');
  }
}