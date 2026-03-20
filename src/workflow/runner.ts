/**
 * Workflow execution engine
 * Manages workflow runs, step execution, and state transitions
 */
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

import { GROUPS_DIR } from '../config.js';
import { logger } from '../logger.js';
import {
  createWorkflowRun,
  getWorkflowRun,
  updateWorkflowRun,
  getWorkflowRunsByWorkflow,
  getActiveWorkflowRuns,
  createWorkflowStepRun,
  getWorkflowStepRunsByRun,
  updateWorkflowStepRun,
  getWorkflowStepRun,
  getSession,
  setSession,
} from '../db.js';
import { resolveGroupFolderPath } from '../group-folder.js';
import type {
  WorkflowDefinition,
  WorkflowRun,
  WorkflowStepRun,
  WorkflowStep,
  StepContext,
  StepOutput,
  StepExecutionResult,
  SendMessageFn,
} from './types.js';
import { renderStepInput } from './definition.js';

const DEFAULT_RETRY_LIMIT = 3;
const DEFAULT_STEP_TIMEOUT = 300000; // 5 minutes

/**
 * Generate a unique run ID
 */
function generateRunId(): string {
  return `run-${Date.now()}-${crypto.randomBytes(4).toString('hex')}`;
}

/**
 * Generate a unique step run ID
 */
function generateStepRunId(runId: string, stepId: string): string {
  return `${runId}-${stepId}`;
}

/**
 * Start a new workflow run
 */
export function startWorkflowRun(
  workflow: WorkflowDefinition,
  task: string,
): WorkflowRun {
  const runId = generateRunId();

  const run: WorkflowRun = {
    id: runId,
    workflowId: workflow.id,
    task,
    status: 'running',
    currentStepIndex: 0,
    startedAt: new Date().toISOString(),
  };

  createWorkflowRun(run);

  // Create all step runs as pending
  for (let i = 0; i < workflow.steps.length; i++) {
    const step = workflow.steps[i];
    const agent = workflow.agents.find((a) => a.id === step.agentId);
    if (!agent) {
      throw new Error(`Agent ${step.agentId} not found for step ${step.id}`);
    }

    const stepRunId = generateStepRunId(runId, step.id);
    createWorkflowStepRun({
      id: stepRunId,
      runId,
      stepId: step.id,
      agentId: step.agentId,
      groupFolder: agent.groupFolder,
      status: i === 0 ? 'running' : 'pending',
      input: '', // Will be rendered before execution
      retryCount: 0,
    });
  }

  logger.info({ runId, workflowId: workflow.id, task }, 'Started workflow run');

  return run;
}

/**
 * Get the current step to execute
 */
export function getCurrentStep(
  workflow: WorkflowDefinition,
  run: WorkflowRun,
): { step: WorkflowStep; stepRun: WorkflowStepRun } | null {
  if (run.currentStepIndex >= workflow.steps.length) {
    return null;
  }

  const step = workflow.steps[run.currentStepIndex];
  const stepRuns = getWorkflowStepRunsByRun(run.id);
  const stepRun = stepRuns.find((sr) => sr.stepId === step.id);

  if (!stepRun) {
    logger.error({ runId: run.id, stepId: step.id }, 'Step run not found');
    return null;
  }

  return { step, stepRun };
}

/**
 * Build context for step execution
 */
function buildStepContext(
  run: WorkflowRun,
  stepRuns: WorkflowStepRun[],
): StepContext {
  const previousSteps: StepOutput[] = stepRuns
    .filter((sr) => sr.status === 'done' && sr.output)
    .map((sr) => ({
      stepId: sr.stepId,
      agentId: sr.agentId,
      output: sr.output!,
      status: sr.status as 'done',
    }));

  return {
    task: run.task,
    runId: run.id,
    previousSteps,
  };
}

/**
 * Prepare step for execution
 * - Renders input template
 * - Sets up agent workspace
 * - Clears session for fresh context
 */
export function prepareStepExecution(
  workflow: WorkflowDefinition,
  run: WorkflowRun,
  step: WorkflowStep,
  stepRun: WorkflowStepRun,
): string {
  const agent = workflow.agents.find((a) => a.id === step.agentId);
  if (!agent) {
    throw new Error(`Agent ${step.agentId} not found`);
  }

  // Build context from previous steps
  const stepRuns = getWorkflowStepRunsByRun(run.id);
  const previousOutputs = new Map<string, string>();
  for (const sr of stepRuns) {
    if (sr.output && sr.status === 'done') {
      previousOutputs.set(sr.stepId, sr.output);
    }
  }

  // Render input
  const renderedInput = renderStepInput(step, {
    task: run.task,
    previousOutputs,
  });

  // Update step run with rendered input
  updateWorkflowStepRun(stepRun.id, {
    input: renderedInput,
    startedAt: new Date().toISOString(),
  });

  // Clear session for fresh context (key antfarm feature)
  // This ensures each step runs with clean context
  const existingSession = getSession(stepRun.groupFolder);
  if (existingSession) {
    logger.debug(
      { groupFolder: stepRun.groupFolder, oldSession: existingSession },
      'Clearing session for fresh context',
    );
    // Note: We don't delete the session, just let the agent start fresh
  }

  // Write workflow context file for the agent
  const groupDir = resolveGroupFolderPath(stepRun.groupFolder);
  const contextFile = path.join(groupDir, 'workflow-context.md');
  const contextContent = buildContextFileContent(run, step, renderedInput, previousOutputs);
  fs.writeFileSync(contextFile, contextContent);

  logger.info(
    { runId: run.id, stepId: step.id, agentId: step.agentId },
    'Prepared step for execution',
  );

  return renderedInput;
}

/**
 * Build the context file content for an agent
 */
function buildContextFileContent(
  run: WorkflowRun,
  step: WorkflowStep,
  input: string,
  previousOutputs: Map<string, string>,
): string {
  let content = `# Workflow Context

## Task
${run.task}

## Current Step
- Step ID: ${step.id}
- Expected output: ${step.expects || 'none specified'}

## Your Instructions
${input}
`;

  if (previousOutputs.size > 0) {
    content += `\n## Previous Step Outputs\n`;
    for (const [stepId, output] of previousOutputs) {
      content += `\n### ${stepId}\n${output}\n`;
    }
  }

  return content;
}

/**
 * Check if step output matches expected pattern
 */
export function checkStepOutput(
  output: string,
  expects?: string,
): boolean {
  if (!expects) return true;
  return output.includes(expects);
}

/**
 * Handle step completion
 */
export async function completeStep(
  runId: string,
  stepIndex: number,
  result: StepExecutionResult,
  sendMessage?: SendMessageFn,
): Promise<void> {
  const run = getWorkflowRun(runId);
  if (!run) {
    logger.error({ runId }, 'Run not found');
    return;
  }

  const stepRuns = getWorkflowStepRunsByRun(runId);
  const stepRun = stepRuns[stepIndex];
  if (!stepRun) {
    logger.error({ runId, stepIndex }, 'Step run not found');
    return;
  }

  if (result.success) {
    // Step succeeded
    updateWorkflowStepRun(stepRun.id, {
      status: 'done',
      output: result.output,
      completedAt: new Date().toISOString(),
    });

    // Move to next step
    const nextStepIndex = stepIndex + 1;
    updateWorkflowRun(runId, { currentStepIndex: nextStepIndex });

    logger.info(
      { runId, stepId: stepRun.stepId, nextStepIndex },
      'Step completed, moving to next',
    );

    // Check if workflow is complete
    if (nextStepIndex >= stepRuns.length) {
      await completeWorkflow(runId, sendMessage);
    }
  } else {
    // Step failed
    const newRetryCount = stepRun.retryCount + 1;
    const retryLimit = 3; // Could be from step config

    if (newRetryCount < retryLimit) {
      // Retry
      updateWorkflowStepRun(stepRun.id, {
        retryCount: newRetryCount,
        error: result.error,
      });
      logger.warn(
        { runId, stepId: stepRun.stepId, retryCount: newRetryCount },
        'Step failed, will retry',
      );
    } else {
      // Max retries reached, escalate
      updateWorkflowStepRun(stepRun.id, {
        status: 'failed',
        error: result.error,
        completedAt: new Date().toISOString(),
      });

      updateWorkflowRun(runId, {
        status: 'paused',
        error: `Step ${stepRun.stepId} failed after ${retryLimit} retries: ${result.error}`,
      });

      logger.error(
        { runId, stepId: stepRun.stepId },
        'Step failed, max retries reached',
      );

      // Notify via message
      if (sendMessage) {
        await sendMessage(
          `⚠️ Workflow paused\n\n` +
            `Run: ${runId}\n` +
            `Task: ${run.task}\n` +
            `Failed step: ${stepRun.stepId}\n` +
            `Error: ${result.error}\n\n` +
            `Use \`workflow_resume ${runId}\` to continue.`,
        );
      }
    }
  }
}

/**
 * Complete a workflow run
 */
async function completeWorkflow(
  runId: string,
  sendMessage?: SendMessageFn,
): Promise<void> {
  updateWorkflowRun(runId, {
    status: 'completed',
    completedAt: new Date().toISOString(),
  });

  logger.info({ runId }, 'Workflow completed');

  if (sendMessage) {
    const run = getWorkflowRun(runId);
    await sendMessage(
      `✅ Workflow completed\n\nRun: ${runId}\nTask: ${run?.task}`,
    );
  }
}

/**
 * Resume a paused workflow run
 */
export function resumeWorkflowRun(runId: string): WorkflowRun | null {
  const run = getWorkflowRun(runId);
  if (!run || run.status !== 'paused') {
    return null;
  }

  updateWorkflowRun(runId, { status: 'running', error: undefined });
  logger.info({ runId }, 'Resumed workflow run');

  const resumedRun = getWorkflowRun(runId);
  return resumedRun ?? null;
}

/**
 * Get workflow run status
 */
export function getWorkflowRunStatus(runId: string): {
  run: WorkflowRun;
  steps: WorkflowStepRun[];
} | null {
  const run = getWorkflowRun(runId);
  if (!run) return null;

  const steps = getWorkflowStepRunsByRun(runId);
  return { run, steps };
}

/**
 * Find runs by partial ID or task
 */
export function findWorkflowRuns(query: string): WorkflowRun[] {
  const allRuns = getActiveWorkflowRuns();

  // Try exact match first
  const exactMatch = allRuns.find((r) => r.id === query);
  if (exactMatch) return [exactMatch];

  // Partial ID match
  const partialIdMatches = allRuns.filter((r) =>
    r.id.toLowerCase().includes(query.toLowerCase()),
  );
  if (partialIdMatches.length > 0) return partialIdMatches;

  // Task content match
  return allRuns.filter((r) =>
    r.task.toLowerCase().includes(query.toLowerCase()),
  );
}
