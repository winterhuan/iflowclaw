/**
 * Model Router
 * Manages model selection, switching, and recovery for each group
 */

import { getRouterState, setRouterState } from './db.js';
import { logger } from './logger.js';
import {
  ModelId,
  DEFAULT_MODEL,
  RECOVERY_COOLDOWN_MS,
  isRecoverableError,
  getNextModelByPriority,
  getModelsByPriority,
  SUPPORTED_MODELS,
} from './model-config.js';

/**
 * State for a single failed model
 */
interface FailedModel {
  failedAt: string; // ISO timestamp
  errorType: string; // Error message or type
}

/**
 * Router state for a single group
 */
export interface ModelRouterState {
  currentModel: ModelId;
  failedModels: Record<string, FailedModel>;
}

/**
 * Model Router class
 * Handles model selection, switching, and recovery with group-level isolation
 */
export class ModelRouter {
  private stateCache = new Map<string, ModelRouterState>();

  /**
   * Get the state key for a group
   */
  private getStateKey(groupFolder: string): string {
    return `model_router:${groupFolder}`;
  }

  /**
   * Get router state for a group (with cache)
   */
  getState(groupFolder: string): ModelRouterState {
    // Check cache first
    const cached = this.stateCache.get(groupFolder);
    if (cached) {
      return cached;
    }

    // Load from database
    const key = this.getStateKey(groupFolder);
    const saved = getRouterState(key);

    if (saved) {
      try {
        const state = JSON.parse(saved) as ModelRouterState;
        this.stateCache.set(groupFolder, state);
        return state;
      } catch {
        logger.warn(`Failed to parse model router state for ${groupFolder}, using default`);
      }
    }

    // Return default state
    const defaultState: ModelRouterState = {
      currentModel: DEFAULT_MODEL,
      failedModels: {},
    };
    this.stateCache.set(groupFolder, defaultState);
    return defaultState;
  }

  /**
   * Save router state for a group
   */
  saveState(groupFolder: string, state: ModelRouterState): void {
    const key = this.getStateKey(groupFolder);
    setRouterState(key, JSON.stringify(state));
    this.stateCache.set(groupFolder, state);
    logger.info(`[model-router] State saved for ${groupFolder}: currentModel=${state.currentModel}`);
  }

  /**
   * Select the model to use for a request
   * Priority: currentModel (with recovery check) > groupDefault > global default
   */
  selectModel(groupFolder: string, groupDefaultModel?: string): ModelId {
    const state = this.getState(groupFolder);
    const now = Date.now();

    // Determine the "preferred" model (group default or global default)
    const preferredModel = (groupDefaultModel as ModelId) || DEFAULT_MODEL;

    // Check if we should attempt to recover to the preferred model
    if (state.currentModel !== preferredModel) {
      const failure = state.failedModels[preferredModel];
      if (failure) {
        const failedAt = new Date(failure.failedAt).getTime();
        if (now - failedAt > RECOVERY_COOLDOWN_MS) {
          // Cooldown period passed, try to recover to preferred model
          logger.info(
            `[model-router] Cooldown passed, attempting recovery to preferred model ${preferredModel} for ${groupFolder}`,
          );
          delete state.failedModels[preferredModel];
          state.currentModel = preferredModel;
          this.saveState(groupFolder, state);
          return preferredModel;
        }
      }
    }

    return state.currentModel;
  }

  /**
   * Handle a model failure
   * Returns the next model to try, or null if no fallback available
   */
  handleFailure(
    groupFolder: string,
    failedModel: string,
    error: Error,
  ): ModelId | null {
    const state = this.getState(groupFolder);

    // Record the failure
    state.failedModels[failedModel] = {
      failedAt: new Date().toISOString(),
      errorType: error.message,
    };

    // Find next available model (not in failedModels)
    const sortedModels = getModelsByPriority();
    const currentPriority = sortedModels.find((m) => m.id === failedModel)?.priority ?? 0;

    for (const model of sortedModels) {
      // Skip models with higher or equal priority (we want lower priority = fallback)
      if (model.priority <= currentPriority) {
        continue;
      }
      // Skip failed models
      if (state.failedModels[model.id]) {
        continue;
      }
      // Found a fallback model
      state.currentModel = model.id;
      this.saveState(groupFolder, state);
      logger.warn(
        `[model-router] Model ${failedModel} failed for ${groupFolder}, switching to ${model.id}`,
      );
      return model.id;
    }

    // No fallback available
    logger.error(
      `[model-router] No fallback model available for ${groupFolder} after ${failedModel} failed`,
    );
    this.saveState(groupFolder, state);
    return null;
  }

  /**
   * Clear failure record for a model (called on success)
   */
  clearFailure(groupFolder: string, model: string): void {
    const state = this.getState(groupFolder);
    if (state.failedModels[model]) {
      delete state.failedModels[model];
      this.saveState(groupFolder, state);
      logger.info(`[model-router] Cleared failure record for ${model} in ${groupFolder}`);
    }
  }

  /**
   * Manually switch to a specific model
   */
  switchModel(groupFolder: string, targetModel: ModelId, reason?: string): boolean {
    // Validate model ID
    if (!SUPPORTED_MODELS.find((m) => m.id === targetModel)) {
      logger.warn(`[model-router] Invalid model ID: ${targetModel}`);
      return false;
    }

    const state = this.getState(groupFolder);
    state.currentModel = targetModel;
    // Clear failure records when manually switching
    state.failedModels = {};
    this.saveState(groupFolder, state);

    logger.info(
      `[model-router] Manually switched to ${targetModel} for ${groupFolder}${reason ? `: ${reason}` : ''}`,
    );
    return true;
  }

  /**
   * Reset a group to use its default model
   */
  resetToDefault(groupFolder: string, groupDefaultModel?: string): void {
    const targetModel = (groupDefaultModel as ModelId) || DEFAULT_MODEL;
    this.switchModel(groupFolder, targetModel, 'Reset to default model');
  }

  /**
   * Get all available models with current status
   */
  getModelsStatus(groupFolder: string, groupDefaultModel?: string): {
    models: Array<{
      id: string;
      name: string;
      priority: number;
      isDefault: boolean;
      isCurrent: boolean;
      isFailed: boolean;
      failedAt?: string;
    }>;
    currentModel: string;
    defaultModel: string;
  } {
    const state = this.getState(groupFolder);
    const preferredModel = (groupDefaultModel as ModelId) || DEFAULT_MODEL;

    const models = getModelsByPriority().map((m) => ({
      id: m.id,
      name: m.name,
      priority: m.priority,
      isDefault: m.id === preferredModel,
      isCurrent: m.id === state.currentModel,
      isFailed: !!state.failedModels[m.id],
      failedAt: state.failedModels[m.id]?.failedAt,
    }));

    return {
      models,
      currentModel: state.currentModel,
      defaultModel: preferredModel,
    };
  }
}

// Singleton instance
export const modelRouter = new ModelRouter();
