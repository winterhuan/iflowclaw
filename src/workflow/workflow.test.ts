import { describe, it, expect, beforeEach } from 'vitest';

import { _initTestDatabase, saveWorkflowDefinition } from '../db.js';
import { parseWorkflowYaml, renderStepInput } from './definition.js';
import { startWorkflowRun, getCurrentStep, checkStepOutput } from './runner.js';
import type { WorkflowDefinition, WorkflowStep } from '../types.js';

describe('Workflow Module', () => {
  beforeEach(() => {
    _initTestDatabase();
  });

  describe('parseWorkflowYaml', () => {
    it('should parse a valid workflow YAML', () => {
      const yaml = `
id: test-workflow
name: Test Workflow
description: A test workflow
agents:
  - id: planner
    name: Planner
    groupFolder: wf-planner
  - id: developer
    name: Developer
    groupFolder: wf-developer
steps:
  - id: plan
    agentId: planner
    input: "Plan the task: {{task}}"
  - id: implement
    agentId: developer
    input: "Implement based on: {{step:plan}}"
`;
      const workflow = parseWorkflowYaml(yaml);

      expect(workflow.id).toBe('test-workflow');
      expect(workflow.name).toBe('Test Workflow');
      expect(workflow.agents).toHaveLength(2);
      expect(workflow.steps).toHaveLength(2);
    });

    it('should throw on missing required fields', () => {
      const yaml = `
name: Test Workflow
`;
      expect(() => parseWorkflowYaml(yaml)).toThrow('must have an "id"');
    });

    it('should throw on missing agents', () => {
      const yaml = `
id: test-workflow
name: Test Workflow
steps:
  - id: step1
    agentId: missing
    input: "test"
`;
      expect(() => parseWorkflowYaml(yaml)).toThrow('at least one agent');
    });

    it('should throw on invalid agent reference', () => {
      const yaml = `
id: test-workflow
name: Test Workflow
agents:
  - id: planner
    name: Planner
    groupFolder: wf-planner
steps:
  - id: step1
    agentId: missing-agent
    input: "test"
`;
      expect(() => parseWorkflowYaml(yaml)).toThrow('unknown agent');
    });
  });

  describe('renderStepInput', () => {
    const step: WorkflowStep = {
      id: 'test-step',
      agentId: 'test-agent',
      input: 'Task: {{task}}\nPrevious: {{step:plan}}',
    };

    it('should replace {{task}} placeholder', () => {
      const result = renderStepInput(step, {
        task: 'Build a feature',
        previousOutputs: new Map(),
      });

      expect(result).toContain('Task: Build a feature');
    });

    it('should replace {{step:xxx}} placeholder', () => {
      const previousOutputs = new Map<string, string>();
      previousOutputs.set('plan', 'Story 1: Implement login');

      const result = renderStepInput(step, {
        task: 'Build a feature',
        previousOutputs,
      });

      expect(result).toContain('Previous: Story 1: Implement login');
    });

    it('should handle missing step output gracefully', () => {
      const result = renderStepInput(step, {
        task: 'Build a feature',
        previousOutputs: new Map(),
      });

      expect(result).toContain('[Step plan output not available]');
    });
  });

  describe('startWorkflowRun', () => {
    it('should create a workflow run with step runs', () => {
      const workflow: WorkflowDefinition = {
        id: 'test-workflow',
        name: 'Test',
        agents: [
          { id: 'planner', name: 'Planner', groupFolder: 'wf-planner' },
        ],
        steps: [
          { id: 'plan', agentId: 'planner', input: 'Plan {{task}}' },
        ],
      };

      // Save workflow definition first (FK constraint)
      saveWorkflowDefinition(workflow);

      const run = startWorkflowRun(workflow, 'Build a feature');

      expect(run.id).toMatch(/^run-/);
      expect(run.workflowId).toBe('test-workflow');
      expect(run.status).toBe('running');
      expect(run.currentStepIndex).toBe(0);
    });
  });

  describe('checkStepOutput', () => {
    it('should return true when expects pattern matches', () => {
      const result = checkStepOutput('STATUS: done\nImplementation complete', 'STATUS: done');
      expect(result).toBe(true);
    });

    it('should return false when expects pattern does not match', () => {
      const result = checkStepOutput('STATUS: failed\nError occurred', 'STATUS: done');
      expect(result).toBe(false);
    });

    it('should return true when no expects specified', () => {
      const result = checkStepOutput('Any output', undefined);
      expect(result).toBe(true);
    });
  });
});
