/**
 * Summary Generator using iFlow CLI
 * Generates AI-powered conversation summaries asynchronously
 */
import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';

import { logger } from './logger.js';
import { saveMemory } from './db.js';

/**
 * Generate summary using iFlow CLI
 * Runs asynchronously to avoid blocking main flow
 */
export async function generateSummaryWithCLI(
  conversationFile: string,
  outputFile: string,
): Promise<boolean> {
  return new Promise((resolve) => {
    // Check if conversation file exists
    if (!fs.existsSync(conversationFile)) {
      logger.warn({ conversationFile }, 'Conversation file not found for summary');
      resolve(false);
      return;
    }

    // Read conversation content
    let conversationContent: string;
    try {
      const data = JSON.parse(fs.readFileSync(conversationFile, 'utf-8'));
      const messages = data.messages || [];
      
      // Format messages for summarization
      conversationContent = messages
        .map((m: { role: string; content: string }) => {
          const role = m.role === 'user' ? '用户' : '助手';
          // Limit content length to avoid token limits
          const content = m.content.substring(0, 500);
          return `${role}: ${content}`;
        })
        .join('\n\n');
      
      if (conversationContent.length > 8000) {
        conversationContent = conversationContent.substring(0, 8000) + '\n\n...(内容已截断)';
      }
    } catch (err) {
      logger.error({ err, conversationFile }, 'Failed to parse conversation file');
      resolve(false);
      return;
    }

    const prompt = `请总结以下对话的关键信息，包括：
1. 对话主题
2. 重要结论或决策
3. 待办事项（如有）
4. 用户偏好或背景信息（如有）

对话内容：
${conversationContent}

请用简洁的中文总结（300字以内）：`;

    // Spawn iFlow CLI process
    const iflowProcess = spawn('iflow', ['--experimental-acp', '--port', '0'], {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, FORCE_COLOR: '0' },
    });

    let output = '';
    let errorOutput = '';
    let timeout: NodeJS.Timeout;

    // Collect stdout
    iflowProcess.stdout?.on('data', (data) => {
      const text = data.toString();
      output += text;
      
      // Check for TASK_FINISH marker in output
      if (text.includes('TASK_FINISH') || text.includes('task_finish')) {
        // Try to extract summary from output
        const summary = extractSummaryFromOutput(output);
        if (summary) {
          saveSummary(outputFile, summary);
          clearTimeout(timeout);
          iflowProcess.kill();
          resolve(true);
        }
      }
    });

    // Collect stderr for debugging
    iflowProcess.stderr?.on('data', (data) => {
      errorOutput += data.toString();
    });

    // Handle process completion
    iflowProcess.on('close', (code) => {
      clearTimeout(timeout);
      
      if (code === 0 || output.length > 100) {
        // Try to extract summary even if exit code is non-zero
        const summary = extractSummaryFromOutput(output) || '对话历史已保存，摘要生成完成';
        saveSummary(outputFile, summary);
        resolve(true);
      } else {
        logger.warn({ code, errorOutput: errorOutput.substring(0, 500) }, 'iFlow CLI exited with error');
        // Save a fallback summary
        saveSummary(outputFile, '对话历史已保存，但摘要生成过程中遇到问题');
        resolve(false);
      }
    });

    // Set timeout (30 seconds)
    timeout = setTimeout(() => {
      logger.warn('Summary generation timeout, killing process');
      iflowProcess.kill('SIGTERM');
      // Save a fallback summary
      saveSummary(outputFile, '对话历史已保存，但摘要生成超时');
      resolve(false);
    }, 30000);

    // Handle errors
    iflowProcess.on('error', (err) => {
      clearTimeout(timeout);
      logger.error({ err }, 'Failed to spawn iFlow CLI');
      saveSummary(outputFile, '对话历史已保存，但无法启动摘要生成');
      resolve(false);
    });

    // Send prompt to stdin
    try {
      iflowProcess.stdin?.write(prompt + '\n');
      iflowProcess.stdin?.end();
    } catch (err) {
      clearTimeout(timeout);
      logger.error({ err }, 'Failed to write to iFlow CLI stdin');
      resolve(false);
    }
  });
}

/**
 * Extract summary from iFlow CLI output
 */
function extractSummaryFromOutput(output: string): string | null {
  // Try to find assistant responses in the output
  const lines = output.split('\n');
  const summaryLines: string[] = [];
  let inAssistantResponse = false;
  
  for (const line of lines) {
    // Skip control messages
    if (line.startsWith('//') || line.startsWith('{')) continue;
    
    // Look for assistant message indicators
    if (line.includes('assistant_message_chunk') || line.includes('ASSISTANT')) {
      inAssistantResponse = true;
      continue;
    }
    
    // Collect non-empty lines that look like content
    if (inAssistantResponse && line.trim() && !line.startsWith('[') && !line.startsWith('{')) {
      summaryLines.push(line.trim());
    }
    
    // Stop at task finish
    if (line.includes('TASK_FINISH') || line.includes('task_finish')) {
      break;
    }
  }
  
  if (summaryLines.length > 0) {
    return summaryLines.join('\n').substring(0, 1000);
  }
  
  // Fallback: return last non-empty lines
  const nonEmptyLines = lines
    .filter(l => l.trim() && !l.startsWith('//') && !l.startsWith('{') && !l.startsWith('['))
    .slice(-10);
  
  if (nonEmptyLines.length > 0) {
    return nonEmptyLines.join('\n').substring(0, 1000);
  }
  
  return null;
}

/**
 * Save summary to file and as memory
 */
function saveSummary(outputFile: string, summary: string): void {
  try {
    const summaryData = {
      summary,
      generatedAt: new Date().toISOString(),
      generatedBy: 'iflow-cli',
    };
    fs.writeFileSync(outputFile, JSON.stringify(summaryData, null, 2));
    logger.info({ outputFile }, 'Summary saved to file');

    // Also save as memory for automatic context injection
    try {
      // Extract groupFolder from path: .../groups/<groupFolder>/conversations/...
      const pathParts = outputFile.split(path.sep);
      const groupsIndex = pathParts.indexOf('groups');
      if (groupsIndex >= 0 && groupsIndex + 1 < pathParts.length) {
        const groupFolder = pathParts[groupsIndex + 1];
        const timestamp = new Date().toISOString().split('T')[0];

        saveMemory({
          group_folder: groupFolder,
          category: 'summary',
          key: `conversation_summary_${timestamp}`,
          value: summary.substring(0, 500), // Limit to 500 chars for memory
          importance: 4, // High importance so it's included in context
        });
        logger.info({ groupFolder }, 'Summary saved to memories');
      }
    } catch (memErr) {
      logger.warn({ err: memErr }, 'Failed to save summary as memory');
      // Don't throw - memory save is not critical
    }
  } catch (err) {
    logger.error({ err, outputFile }, 'Failed to save summary');
  }
}

/**
 * Generate summary asynchronously (non-blocking)
 * This function returns immediately and generates summary in background
 */
export function generateSummaryAsync(
  conversationFile: string,
  outputFile: string,
): void {
  // Run in background without awaiting
  generateSummaryWithCLI(conversationFile, outputFile).then((success) => {
    if (success) {
      logger.info({ conversationFile, outputFile }, 'Summary generation completed');
    } else {
      logger.warn({ conversationFile, outputFile }, 'Summary generation failed or timed out');
    }
  }).catch((err) => {
    logger.error({ err, conversationFile }, 'Summary generation error');
  });
}
