/**
 * Workflow module types
 * Re-exports from main types and adds internal types
 */
import type {
  WorkflowDefinition,
  WorkflowRun,
  WorkflowStepRun,
  WorkflowAgent,
  WorkflowStep,
} from '../types.js';

export type {
  WorkflowDefinition,
  WorkflowRun,
  WorkflowStepRun,
  WorkflowAgent,
  WorkflowStep,
};

/**
 * Context passed to each step during execution
 */
export interface StepContext {
  task: string;
  runId: string;
  previousSteps: StepOutput[];
}

/**
 * Output from a completed step
 */
export interface StepOutput {
  stepId: string;
  agentId: string;
  output: string;
  status: 'done' | 'failed' | 'skipped';
}

/**
 * Result of step execution
 */
export interface StepExecutionResult {
  success: boolean;
  output: string;
  error?: string;
}

/**
 * Callback for step completion
 */
export type OnStepComplete = (
  runId: string,
  stepIndex: number,
  result: StepExecutionResult,
) => Promise<void>;

/**
 * Callback for sending messages
 */
export type SendMessageFn = (text: string) => Promise<void>;
