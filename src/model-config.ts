/**
 * Model Configuration
 * Defines supported models, priorities, and error patterns for model switching
 */

/**
 * Supported models with priority order (lower number = higher priority)
 */
export const SUPPORTED_MODELS = [
  { id: 'glm-5', name: 'GLM 5', priority: 1 },
  { id: 'minimax-m2.5', name: 'MiniMax M2.5', priority: 2 },
  { id: 'kimi-k2.5', name: 'Kimi K2.5', priority: 3 },
  { id: 'deepseek-v3.2-chat', name: 'DeepSeek V3.2', priority: 4 },
  { id: 'glm-4.7', name: 'GLM 4.7', priority: 5 },
  { id: 'qwen3-coder-plus', name: 'Qwen3 Coder+', priority: 6 },
  { id: 'kimi-k2-thinking', name: 'Kimi K2 Thinking', priority: 7 },
  { id: 'kimi-k2-0905', name: 'Kimi K2 (0905)', priority: 8 },
  { id: 'iFlow-ROME-30BA3B', name: 'iFlow ROME', priority: 9 },
] as const;

export type ModelId = (typeof SUPPORTED_MODELS)[number]['id'];

/**
 * Global default model (highest priority)
 */
export const DEFAULT_MODEL: ModelId = 'glm-5';

/**
 * Cooldown period before attempting to recover a failed model (10 minutes)
 */
export const RECOVERY_COOLDOWN_MS = 10 * 60 * 1000;

/**
 * Error patterns that indicate recoverable errors (rate limits, etc.)
 * When these occur, the system will automatically switch to a fallback model
 */
export const RECOVERABLE_ERROR_PATTERNS = [
  'rate limit',
  '速率限制',
  'too many requests',
  '429',
  '当前模型已达到平台速率限制',
  'Internal Error',
];

/**
 * Check if an error message indicates a recoverable error
 */
export function isRecoverableError(errorMessage: string): boolean {
  const lowerMessage = errorMessage.toLowerCase();
  return RECOVERABLE_ERROR_PATTERNS.some((pattern) =>
    lowerMessage.includes(pattern.toLowerCase()),
  );
}

/**
 * Get model info by ID
 */
export function getModelInfo(modelId: string) {
  return SUPPORTED_MODELS.find((m) => m.id === modelId);
}

/**
 * Get models sorted by priority
 */
export function getModelsByPriority() {
  return [...SUPPORTED_MODELS].sort((a, b) => a.priority - b.priority);
}

/**
 * Get next model in priority order after the given model
 * Returns null if the given model is the last one
 */
export function getNextModelByPriority(currentModelId: string): ModelId | null {
  const sortedModels = getModelsByPriority();
  const currentIndex = sortedModels.findIndex((m) => m.id === currentModelId);

  if (currentIndex === -1 || currentIndex >= sortedModels.length - 1) {
    return null;
  }

  return sortedModels[currentIndex + 1].id;
}
