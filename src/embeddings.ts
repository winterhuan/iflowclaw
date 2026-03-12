/**
 * Embedding Service
 * 使用 NVIDIA API 生成文本向量嵌入
 */
import OpenAI from 'openai';
import {
  EMBEDDING_API_KEY,
  EMBEDDING_BASE_URL,
  EMBEDDING_MODEL,
} from './config.js';
import { logger } from './logger.js';

const apiKey = EMBEDDING_API_KEY;
const baseURL = EMBEDDING_BASE_URL;
const model = EMBEDDING_MODEL;

// 检查配置
if (!apiKey) {
  logger.warn('EMBEDDING_API_KEY not set, embedding features will be disabled');
}

const openai = new OpenAI({
  apiKey: apiKey || 'dummy-key',
  baseURL,
});

/**
 * 获取文本的向量嵌入
 * @param text 输入文本
 * @returns 向量数组 (1024 维 for bge-m3)
 */
export async function getEmbedding(text: string): Promise<number[]> {
  if (!apiKey) {
    throw new Error('EMBEDDING_API_KEY not configured');
  }

  logger.debug({ textLength: text.length }, 'Getting embedding');

  try {
    const response = await openai.embeddings.create({
      input: [text],
      model,
      encoding_format: 'float',
    });

    const embedding = response.data[0].embedding;
    logger.debug({ embeddingLength: embedding.length }, 'Embedding generated');

    return embedding;
  } catch (err) {
    logger.error({ err, textLength: text.length }, 'Failed to get embedding');
    throw err;
  }
}

/**
 * 批量获取文本的向量嵌入
 * @param texts 文本数组
 * @returns 向量数组的数组
 */
export async function getEmbeddings(texts: string[]): Promise<number[][]> {
  if (!apiKey) {
    throw new Error('EMBEDDING_API_KEY not configured');
  }

  if (texts.length === 0) {
    return [];
  }

  logger.debug({ count: texts.length }, 'Getting batch embeddings');

  try {
    const response = await openai.embeddings.create({
      input: texts,
      model,
      encoding_format: 'float',
    });

    const embeddings = response.data.map((d: { embedding: number[] }) => d.embedding);
    logger.debug({ count: embeddings.length }, 'Batch embeddings generated');

    return embeddings;
  } catch (err) {
    logger.error({ err, count: texts.length }, 'Failed to get batch embeddings');
    throw err;
  }
}

/**
 * 计算两个向量的余弦相似度
 * @param a 向量 A
 * @param b 向量 B
 * @returns 相似度 (-1 到 1，越接近 1 越相似)
 */
export function cosineSimilarity(a: number[], b: number[]): number {
  if (a.length !== b.length) {
    throw new Error(`Vector dimensions mismatch: ${a.length} vs ${b.length}`);
  }

  let dotProduct = 0;
  let normA = 0;
  let normB = 0;

  for (let i = 0; i < a.length; i++) {
    dotProduct += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }

  if (normA === 0 || normB === 0) {
    return 0;
  }

  return dotProduct / (Math.sqrt(normA) * Math.sqrt(normB));
}

/**
 * 检查 embedding 功能是否可用
 */
export function isEmbeddingEnabled(): boolean {
  return !!apiKey;
}

/**
 * 获取 embedding 配置信息
 */
export function getEmbeddingConfig(): {
  enabled: boolean;
  baseURL: string;
  model: string;
} {
  return {
    enabled: !!apiKey,
    baseURL,
    model,
  };
}