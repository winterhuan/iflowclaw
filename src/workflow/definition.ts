/**
 * Workflow definition parsing and validation
 */
import fs from 'fs';
import path from 'path';
import yaml from 'yaml';

import { GROUPS_DIR } from '../config.js';
import { logger } from '../logger.js';
import {
  saveWorkflowDefinition,
  getWorkflowDefinition,
  getAllWorkflowDefinitions,
  deleteWorkflowDefinition,
} from '../db.js';
import type { WorkflowDefinition, WorkflowAgent, WorkflowStep } from './types.js';

/**
 * Parse workflow definition from YAML string
 */
export function parseWorkflowYaml(yamlContent: string): WorkflowDefinition {
  const parsed = yaml.parse(yamlContent);

  if (!parsed.id || typeof parsed.id !== 'string') {
    throw new Error('Workflow must have an "id" field');
  }
  if (!parsed.name || typeof parsed.name !== 'string') {
    throw new Error('Workflow must have a "name" field');
  }
  if (!Array.isArray(parsed.agents) || parsed.agents.length === 0) {
    throw new Error('Workflow must have at least one agent');
  }
  if (!Array.isArray(parsed.steps) || parsed.steps.length === 0) {
    throw new Error('Workflow must have at least one step');
  }

  // Validate agents
  for (const agent of parsed.agents as WorkflowAgent[]) {
    if (!agent.id) {
      throw new Error('Each agent must have an "id"');
    }
    if (!agent.groupFolder) {
      throw new Error(`Agent "${agent.id}" must have a "groupFolder"`);
    }
  }

  // Validate steps
  const agentIds = new Set(parsed.agents.map((a: WorkflowAgent) => a.id));
  for (const step of parsed.steps as WorkflowStep[]) {
    if (!step.id) {
      throw new Error('Each step must have an "id"');
    }
    if (!step.agentId) {
      throw new Error(`Step "${step.id}" must have an "agentId"`);
    }
    if (!agentIds.has(step.agentId)) {
      throw new Error(
        `Step "${step.id}" references unknown agent "${step.agentId}"`,
      );
    }
  }

  return parsed as WorkflowDefinition;
}

/**
 * Load workflow from a directory containing workflow.yaml
 */
export function loadWorkflowFromDir(dirPath: string): WorkflowDefinition | null {
  const yamlPath = path.join(dirPath, 'workflow.yaml');
  if (!fs.existsSync(yamlPath)) {
    return null;
  }

  const content = fs.readFileSync(yamlPath, 'utf-8');
  return parseWorkflowYaml(content);
}

/**
 * Load all workflows from the workflows directory
 */
export function loadAllWorkflows(workflowsDir: string): WorkflowDefinition[] {
  const workflows: WorkflowDefinition[] = [];

  if (!fs.existsSync(workflowsDir)) {
    return workflows;
  }

  const entries = fs.readdirSync(workflowsDir, { withFileTypes: true });
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;

    const workflowDir = path.join(workflowsDir, entry.name);
    const workflow = loadWorkflowFromDir(workflowDir);
    if (workflow) {
      workflows.push(workflow);
      logger.info({ workflowId: workflow.id, name: workflow.name }, 'Loaded workflow');
    }
  }

  return workflows;
}

/**
 * Install a workflow into the database
 */
export function installWorkflow(workflow: WorkflowDefinition): void {
  saveWorkflowDefinition(workflow);
  logger.info({ workflowId: workflow.id }, 'Installed workflow');
}

/**
 * Uninstall a workflow from the database
 */
export function uninstallWorkflow(workflowId: string): void {
  deleteWorkflowDefinition(workflowId);
  logger.info({ workflowId }, 'Uninstalled workflow');
}

/**
 * Get a workflow definition by ID
 */
export function getWorkflow(id: string): WorkflowDefinition | undefined {
  return getWorkflowDefinition(id);
}

/**
 * List all installed workflows
 */
export function listWorkflows(): WorkflowDefinition[] {
  return getAllWorkflowDefinitions();
}

/**
 * Render step input template with context
 */
export function renderStepInput(
  step: WorkflowStep,
  context: { task: string; previousOutputs: Map<string, string> },
): string {
  let input = step.input;

  // Replace {{task}}
  input = input.replace(/\{\{task\}\}/g, context.task);

  // Replace {{previousSteps}}
  if (input.includes('{{previousSteps}}')) {
    const previousStepsText = Array.from(context.previousOutputs.entries())
      .map(([stepId, output]) => `## Step: ${stepId}\n${output}`)
      .join('\n\n');
    input = input.replace(/\{\{previousSteps\}\}/g, previousStepsText);
  }

  // Replace {{step:<stepId>}}
  const stepRefRegex = /\{\{step:([^}]+)\}\}/g;
  input = input.replace(stepRefRegex, (_, stepId) => {
    const output = context.previousOutputs.get(stepId);
    if (!output) {
      logger.warn({ stepId }, 'Referenced step output not found');
      return `[Step ${stepId} output not available]`;
    }
    return output;
  });

  return input;
}
