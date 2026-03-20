/**
 * Stdio MCP Server for NanoClaw
 * Standalone process that agent teams subagents can inherit.
 * Reads context from environment variables, writes IPC files for the host.
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import fs from 'fs';
import path from 'path';
import { CronExpressionParser } from 'cron-parser';

const IPC_DIR = process.env.IFLOWCLAW_IPC_DIR || '/workspace/ipc';

// Context from environment variables (set by the agent runner)
const chatJid = process.env.IFLOWCLAW_CHAT_JID!;
const groupFolder = process.env.IFLOWCLAW_GROUP_FOLDER!;
const isMain = process.env.IFLOWCLAW_IS_MAIN === '1';

// IPC directories are per-group: ipc/<groupFolder>/messages and ipc/<groupFolder>/tasks
const GROUP_IPC_DIR = path.join(IPC_DIR, groupFolder);
const MESSAGES_DIR = path.join(GROUP_IPC_DIR, 'messages');
const TASKS_DIR = path.join(GROUP_IPC_DIR, 'tasks');

function writeIpcFile(dir: string, data: object): string {
  fs.mkdirSync(dir, { recursive: true });

  const filename = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}.json`;
  const filepath = path.join(dir, filename);

  // Atomic write: temp file then rename
  const tempPath = `${filepath}.tmp`;
  fs.writeFileSync(tempPath, JSON.stringify(data, null, 2));
  fs.renameSync(tempPath, filepath);

  return filename;
}

const server = new McpServer({
  name: 'iflowclaw',
  version: '1.0.0',
});

server.tool(
  'send_message',
  "Send a message to the user or group immediately while you're still running. Use this for progress updates or to send multiple messages. You can call this multiple times.",
  {
    text: z.string().describe('The message text to send'),
    sender: z.string().optional().describe('Your role/identity name (e.g. "Researcher"). When set, messages appear from a dedicated bot in Telegram.'),
  },
  async (args) => {
    const data: Record<string, string | undefined> = {
      type: 'message',
      chatJid,
      text: args.text,
      sender: args.sender || undefined,
      groupFolder,
      timestamp: new Date().toISOString(),
    };

    writeIpcFile(MESSAGES_DIR, data);

    return { content: [{ type: 'text' as const, text: 'Message sent.' }] };
  },
);

server.tool(
  'schedule_task',
  `Schedule a recurring or one-time task. The task will run as a full agent with access to all tools. Returns the task ID for future reference. To modify an existing task, use update_task instead.

CONTEXT MODE - Choose based on task type:
\u2022 "group": Task runs in the group's conversation context, with access to chat history. Use for tasks that need context about ongoing discussions, user preferences, or recent interactions.
\u2022 "isolated": Task runs in a fresh session with no conversation history. Use for independent tasks that don't need prior context. When using isolated mode, include all necessary context in the prompt itself.

If unsure which mode to use, you can ask the user. Examples:
- "Remind me about our discussion" \u2192 group (needs conversation context)
- "Check the weather every morning" \u2192 isolated (self-contained task)
- "Follow up on my request" \u2192 group (needs to know what was requested)
- "Generate a daily report" \u2192 isolated (just needs instructions in prompt)

MESSAGING BEHAVIOR - The task agent's output is sent to the user or group. It can also use send_message for immediate delivery, or wrap output in <internal> tags to suppress it. Include guidance in the prompt about whether the agent should:
\u2022 Always send a message (e.g., reminders, daily briefings)
\u2022 Only send a message when there's something to report (e.g., "notify me if...")
\u2022 Never send a message (background maintenance tasks)

SCHEDULE VALUE FORMAT (all times are LOCAL timezone):
\u2022 cron: Standard cron expression (e.g., "*/5 * * * *" for every 5 minutes, "0 9 * * *" for daily at 9am LOCAL time)
\u2022 interval: Milliseconds between runs (e.g., "300000" for 5 minutes, "3600000" for 1 hour)
\u2022 once: Local time WITHOUT "Z" suffix (e.g., "2026-02-01T15:30:00"). Do NOT use UTC/Z suffix.`,
  {
    prompt: z.string().describe('What the agent should do when the task runs. For isolated mode, include all necessary context here.'),
    schedule_type: z.enum(['cron', 'interval', 'once']).describe('cron=recurring at specific times, interval=recurring every N ms, once=run once at specific time'),
    schedule_value: z.string().describe('cron: "*/5 * * * *" | interval: milliseconds like "300000" | once: local timestamp like "2026-02-01T15:30:00" (no Z suffix!)'),
    context_mode: z.enum(['group', 'isolated']).default('group').describe('group=runs with chat history, isolated=fresh session (include context in prompt)'),
    target_group_jid: z.string().optional().describe('(Main group only) JID of the group to schedule the task for. Defaults to the current group.'),
  },
  async (args) => {
    // Validate schedule_value before writing IPC
    if (args.schedule_type === 'cron') {
      try {
        CronExpressionParser.parse(args.schedule_value);
      } catch {
        return {
          content: [{ type: 'text' as const, text: `Invalid cron: "${args.schedule_value}". Use format like "0 9 * * *" (daily 9am) or "*/5 * * * *" (every 5 min).` }],
          isError: true,
        };
      }
    } else if (args.schedule_type === 'interval') {
      const ms = parseInt(args.schedule_value, 10);
      if (isNaN(ms) || ms <= 0) {
        return {
          content: [{ type: 'text' as const, text: `Invalid interval: "${args.schedule_value}". Must be positive milliseconds (e.g., "300000" for 5 min).` }],
          isError: true,
        };
      }
    } else if (args.schedule_type === 'once') {
      if (/[Zz]$/.test(args.schedule_value) || /[+-]\d{2}:\d{2}$/.test(args.schedule_value)) {
        return {
          content: [{ type: 'text' as const, text: `Timestamp must be local time without timezone suffix. Got "${args.schedule_value}" — use format like "2026-02-01T15:30:00".` }],
          isError: true,
        };
      }
      const date = new Date(args.schedule_value);
      if (isNaN(date.getTime())) {
        return {
          content: [{ type: 'text' as const, text: `Invalid timestamp: "${args.schedule_value}". Use local time format like "2026-02-01T15:30:00".` }],
          isError: true,
        };
      }
    }

    // Non-main groups can only schedule for themselves
    const targetJid = isMain && args.target_group_jid ? args.target_group_jid : chatJid;

    const taskId = `task-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    const data = {
      type: 'schedule_task',
      taskId,
      prompt: args.prompt,
      schedule_type: args.schedule_type,
      schedule_value: args.schedule_value,
      context_mode: args.context_mode || 'group',
      targetJid,
      createdBy: groupFolder,
      timestamp: new Date().toISOString(),
    };

    writeIpcFile(TASKS_DIR, data);

    return {
      content: [{ type: 'text' as const, text: `Task ${taskId} scheduled: ${args.schedule_type} - ${args.schedule_value}` }],
    };
  },
);

server.tool(
  'list_tasks',
  "List all scheduled tasks. From main: shows all tasks. From other groups: shows only that group's tasks.",
  {},
  async () => {
    const tasksFile = path.join(IPC_DIR, 'current_tasks.json');

    try {
      if (!fs.existsSync(tasksFile)) {
        return { content: [{ type: 'text' as const, text: 'No scheduled tasks found.' }] };
      }

      const allTasks = JSON.parse(fs.readFileSync(tasksFile, 'utf-8'));

      const tasks = isMain
        ? allTasks
        : allTasks.filter((t: { groupFolder: string }) => t.groupFolder === groupFolder);

      if (tasks.length === 0) {
        return { content: [{ type: 'text' as const, text: 'No scheduled tasks found.' }] };
      }

      const formatted = tasks
        .map(
          (t: { id: string; prompt: string; schedule_type: string; schedule_value: string; status: string; next_run: string }) =>
            `- [${t.id}] ${t.prompt.slice(0, 50)}... (${t.schedule_type}: ${t.schedule_value}) - ${t.status}, next: ${t.next_run || 'N/A'}`,
        )
        .join('\n');

      return { content: [{ type: 'text' as const, text: `Scheduled tasks:\n${formatted}` }] };
    } catch (err) {
      return {
        content: [{ type: 'text' as const, text: `Error reading tasks: ${err instanceof Error ? err.message : String(err)}` }],
      };
    }
  },
);

server.tool(
  'pause_task',
  'Pause a scheduled task. It will not run until resumed.',
  { task_id: z.string().describe('The task ID to pause') },
  async (args) => {
    const data = {
      type: 'pause_task',
      taskId: args.task_id,
      groupFolder,
      isMain,
      timestamp: new Date().toISOString(),
    };

    writeIpcFile(TASKS_DIR, data);

    return { content: [{ type: 'text' as const, text: `Task ${args.task_id} pause requested.` }] };
  },
);

server.tool(
  'resume_task',
  'Resume a paused task.',
  { task_id: z.string().describe('The task ID to resume') },
  async (args) => {
    const data = {
      type: 'resume_task',
      taskId: args.task_id,
      groupFolder,
      isMain,
      timestamp: new Date().toISOString(),
    };

    writeIpcFile(TASKS_DIR, data);

    return { content: [{ type: 'text' as const, text: `Task ${args.task_id} resume requested.` }] };
  },
);

server.tool(
  'cancel_task',
  'Cancel and delete a scheduled task.',
  { task_id: z.string().describe('The task ID to cancel') },
  async (args) => {
    const data = {
      type: 'cancel_task',
      taskId: args.task_id,
      groupFolder,
      isMain,
      timestamp: new Date().toISOString(),
    };

    writeIpcFile(TASKS_DIR, data);

    return { content: [{ type: 'text' as const, text: `Task ${args.task_id} cancellation requested.` }] };
  },
);

server.tool(
  'update_task',
  'Update an existing scheduled task. Only provided fields are changed; omitted fields stay the same.',
  {
    task_id: z.string().describe('The task ID to update'),
    prompt: z.string().optional().describe('New prompt for the task'),
    schedule_type: z.enum(['cron', 'interval', 'once']).optional().describe('New schedule type'),
    schedule_value: z.string().optional().describe('New schedule value (see schedule_task for format)'),
  },
  async (args) => {
    // Validate schedule_value if provided
    if (args.schedule_type === 'cron' || (!args.schedule_type && args.schedule_value)) {
      if (args.schedule_value) {
        try {
          CronExpressionParser.parse(args.schedule_value);
        } catch {
          return {
            content: [{ type: 'text' as const, text: `Invalid cron: "${args.schedule_value}".` }],
            isError: true,
          };
        }
      }
    }
    if (args.schedule_type === 'interval' && args.schedule_value) {
      const ms = parseInt(args.schedule_value, 10);
      if (isNaN(ms) || ms <= 0) {
        return {
          content: [{ type: 'text' as const, text: `Invalid interval: "${args.schedule_value}".` }],
          isError: true,
        };
      }
    }

    const data: Record<string, string | undefined> = {
      type: 'update_task',
      taskId: args.task_id,
      groupFolder,
      isMain: String(isMain),
      timestamp: new Date().toISOString(),
    };
    if (args.prompt !== undefined) data.prompt = args.prompt;
    if (args.schedule_type !== undefined) data.schedule_type = args.schedule_type;
    if (args.schedule_value !== undefined) data.schedule_value = args.schedule_value;

    writeIpcFile(TASKS_DIR, data);

    return { content: [{ type: 'text' as const, text: `Task ${args.task_id} update requested.` }] };
  },
);

// Note: Memory tools removed - using Claude-Mem instead
// Claude-Mem provides memory functionality via Hooks and Skills

server.tool(
  'register_group',
  `Register a new chat/group so the agent can respond to messages there. Main group only.

Use available_groups.json to find the JID for a group. The folder name should be a simple identifier (e.g., "content-team", "video-team", "dev-group"). Use lowercase with hyphens.`,
  {
    jid: z.string().describe('The chat JID (e.g., "120363336345536173@g.us", "tg:-1001234567890", "dc:1234567890123456")'),
    name: z.string().describe('Display name for the group'),
    folder: z.string().describe('Channel-prefixed folder name (e.g., "whatsapp_family-chat", "telegram_dev-team")'),
    trigger: z.string().describe('Trigger word (e.g., "@Andy")'),
  },
  async (args) => {
    if (!isMain) {
      return {
        content: [{ type: 'text' as const, text: 'Only the main group can register new groups.' }],
        isError: true,
      };
    }

    const data = {
      type: 'register_group',
      jid: args.jid,
      name: args.name,
      folder: args.folder,
      trigger: args.trigger,
      timestamp: new Date().toISOString(),
    };

    writeIpcFile(TASKS_DIR, data);

    return {
      content: [{ type: 'text' as const, text: `Group "${args.name}" registered. It will start receiving messages immediately.` }],
    };
  },
);

// --- Workflow tools (Multi-Agent System) ---

server.tool(
  'workflow_list',
  'List all available workflows that can be run.',
  {},
  async () => {
    const workflowsFile = path.join(IPC_DIR, 'workflows.json');

    try {
      if (!fs.existsSync(workflowsFile)) {
        return { content: [{ type: 'text' as const, text: 'No workflows installed. Run `workflow_install` to load built-in workflows.' }] };
      }

      const workflows = JSON.parse(fs.readFileSync(workflowsFile, 'utf-8'));

      if (workflows.length === 0) {
        return { content: [{ type: 'text' as const, text: 'No workflows installed.' }] };
      }

      const formatted = workflows
        .map(
          (w: { id: string; name: string; description?: string; agents?: { length: number } }) =>
            `- ${w.id}: ${w.name}${w.description ? ` - ${w.description}` : ''} (${w.agents?.length || 0} agents)`,
        )
        .join('\n');

      return { content: [{ type: 'text' as const, text: `Available workflows:\n${formatted}` }] };
    } catch (err) {
      return {
        content: [{ type: 'text' as const, text: `Error reading workflows: ${err instanceof Error ? err.message : String(err)}` }],
      };
    }
  },
);

server.tool(
  'workflow_run',
  `Start a multi-agent workflow. A team of specialized agents will work together to complete your task.

Each workflow has multiple steps, and each step is handled by a different agent. Agents verify each other's work and retry automatically on failure.

Example: "Add OAuth login" with feature-dev workflow will:
1. Planner breaks down the task into stories
2. Developer implements each story
3. Verifier checks each implementation
4. Tester writes tests
5. Reviewer does final code review

The workflow runs in the background. Use workflow_status to check progress.`,
  {
    workflow_id: z.string().describe('The workflow ID (e.g., "feature-dev", "bug-fix", "security-audit")'),
    task: z.string().describe('The task description. Be specific about what you want to achieve.'),
  },
  async (args) => {
    const data = {
      type: 'workflow_run',
      workflowId: args.workflow_id,
      task: args.task,
      chatJid,
      groupFolder,
      timestamp: new Date().toISOString(),
    };

    writeIpcFile(TASKS_DIR, data);

    return {
      content: [{ type: 'text' as const, text: `Workflow "${args.workflow_id}" started.\n\nTask: ${args.task}\n\nUse \`workflow_status\` to check progress. You can continue working while the workflow runs in the background.` }],
    };
  },
);

server.tool(
  'workflow_status',
  'Check the status of a workflow run. Provide a run ID or search by task description.',
  {
    query: z.string().optional().describe('Run ID or task description to search for. If omitted, shows all active runs.'),
  },
  async (args) => {
    const runsFile = path.join(IPC_DIR, 'workflow_runs.json');

    try {
      if (!fs.existsSync(runsFile)) {
        return { content: [{ type: 'text' as const, text: 'No workflow runs found.' }] };
      }

      const allRuns = JSON.parse(fs.readFileSync(runsFile, 'utf-8'));

      let runs = allRuns;
      if (args.query) {
        runs = allRuns.filter(
          (r: { id: string; task: string }) =>
            r.id.includes(args.query!) || r.task.toLowerCase().includes(args.query!.toLowerCase()),
        );
      }

      // Filter to active runs if no query
      if (!args.query) {
        runs = runs.filter((r: { status: string }) => ['running', 'paused'].includes(r.status));
      }

      if (runs.length === 0) {
        return { content: [{ type: 'text' as const, text: args.query ? 'No matching workflow runs found.' : 'No active workflow runs.' }] };
      }

      const formatted = runs
        .map(
          (r: {
            id: string;
            workflowId: string;
            task: string;
            status: string;
            currentStepIndex: number;
            totalSteps: number;
            currentStepName?: string;
          }) => {
            const progress = r.totalSteps ? `${r.currentStepIndex + 1}/${r.totalSteps}` : '';
            const stepInfo = r.currentStepName ? ` (${r.currentStepName})` : '';
            return `- [${r.id}] ${r.workflowId}: "${r.task.slice(0, 50)}..."\n  Status: ${r.status}${stepInfo} ${progress}`;
          },
        )
        .join('\n\n');

      return { content: [{ type: 'text' as const, text: `Workflow runs:\n${formatted}` }] };
    } catch (err) {
      return {
        content: [{ type: 'text' as const, text: `Error reading workflow runs: ${err instanceof Error ? err.message : String(err)}` }],
      };
    }
  },
);

server.tool(
  'workflow_resume',
  'Resume a paused workflow run. Use this when a workflow has paused due to failures and you want to retry.',
  {
    run_id: z.string().describe('The run ID to resume'),
  },
  async (args) => {
    const data = {
      type: 'workflow_resume',
      runId: args.run_id,
      groupFolder,
      timestamp: new Date().toISOString(),
    };

    writeIpcFile(TASKS_DIR, data);

    return { content: [{ type: 'text' as const, text: `Resume requested for run ${args.run_id}.` }] };
  },
);

server.tool(
  'workflow_install',
  'Install built-in workflows from the workflows directory. Main group only.',
  {},
  async () => {
    if (!isMain) {
      return {
        content: [{ type: 'text' as const, text: 'Only the main group can install workflows.' }],
        isError: true,
      };
    }

    const data = {
      type: 'workflow_install',
      groupFolder,
      timestamp: new Date().toISOString(),
    };

    writeIpcFile(TASKS_DIR, data);

    return { content: [{ type: 'text' as const, text: 'Workflow installation requested. Built-in workflows will be loaded.' }] };
  },
);

// Start the stdio transport
const transport = new StdioServerTransport();
await server.connect(transport);
