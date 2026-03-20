export interface RegisteredGroup {
  name: string;
  folder: string;
  trigger: string;
  added_at: string;
  requiresTrigger?: boolean; // Default: true for groups, false for solo chats
  isMain?: boolean; // True for the main control group (no trigger, elevated privileges)
  agentConfig?: AgentConfig; // Optional config for agent timeout
}

export interface NewMessage {
  id: string;
  chat_jid: string;
  sender: string;
  sender_name: string;
  content: string;
  timestamp: string;
  is_from_me?: boolean;
  is_bot_message?: boolean;
}

export interface ScheduledTask {
  id: string;
  group_folder: string;
  chat_jid: string;
  prompt: string;
  schedule_type: 'cron' | 'interval' | 'once';
  schedule_value: string;
  context_mode: 'group' | 'isolated';
  next_run: string | null;
  last_run: string | null;
  last_result: string | null;
  status: 'active' | 'paused' | 'completed';
  created_at: string;
}

export interface TaskRunLog {
  task_id: string;
  run_at: string;
  duration_ms: number;
  status: 'success' | 'error';
  result: string | null;
  error: string | null;
}

// --- Channel abstraction ---

export interface Channel {
  name: string;
  connect(): Promise<void>;
  sendMessage(jid: string, text: string): Promise<void>;
  isConnected(): boolean;
  ownsJid(jid: string): boolean;
  disconnect(): Promise<void>;
  // Optional: typing indicator. Channels that support it implement it.
  setTyping?(jid: string, isTyping: boolean): Promise<void>;
  // Optional: sync group/chat names from the platform.
  syncGroups?(force: boolean): Promise<void>;
}

// Callback type that channels use to deliver inbound messages
export type OnInboundMessage = (chatJid: string, message: NewMessage) => void;

// Callback for chat metadata discovery.
// name is optional — channels that deliver names inline (Telegram) pass it here;
// channels that sync names separately (via syncGroups) omit it.
export type OnChatMetadata = (
  chatJid: string,
  timestamp: string,
  name?: string,
  channel?: string,
  isGroup?: boolean,
) => void;

export interface AvailableGroup {
  jid: string;
  name: string;
  lastActivity: string;
  isRegistered: boolean;
}

// Process interface for agent execution
export interface AgentProcess {
  kill(signal?: string | number): boolean | void;
  killed?: boolean;
  stdin?: {
    write(data: string): void;
    end(): void;
  } | null;
}

// Container configuration for sandboxed execution
export interface ContainerConfig {
  image?: string;
  readOnlyRoot?: boolean;
  networkMode?: 'none' | 'host' | 'bridge';
  extraMounts?: Array<{
    source: string;
    target: string;
    readOnly?: boolean;
  }>;
  additionalMounts?: AdditionalMount[]; // Validated mounts from allowlist
  resources?: {
    memory?: string;
    cpus?: string;
  };
  env?: Record<string, string>;
  timeout?: number;
}

// Additional mount for container (validated against allowlist)
export interface AdditionalMount {
  hostPath: string;
  containerPath?: string; // Defaults to basename of hostPath
  readonly?: boolean; // Default: true
}

// Allowed root for mount validation
export interface AllowedRoot {
  path: string;
  allowReadWrite?: boolean; // Default: false
  description?: string;
}

// Mount allowlist configuration
export interface MountAllowlist {
  allowedRoots: AllowedRoot[];
  blockedPatterns: string[];
  nonMainReadOnly: boolean; // Force non-main groups to read-only
}

// Agent config for timeout and execution mode
export interface AgentConfig {
  timeout?: number;
  executionMode?: 'direct' | 'container' | 'auto';
  containerConfig?: ContainerConfig;
}

// --- Workflow types (Multi-Agent System) ---

export interface WorkflowAgent {
  id: string;
  name: string;
  groupFolder: string; // Maps to iFlowClaw group
  workspaceFiles?: Record<string, string>; // filename -> content or path
}

export interface WorkflowStep {
  id: string;
  agentId: string;
  input: string; // Template with {{task}}, {{previousSteps}}
  expects?: string; // Expected output pattern (e.g., "STATUS: done")
  retryLimit?: number; // Default: 3
  timeout?: number; // Step-specific timeout in ms
}

export interface WorkflowDefinition {
  id: string;
  name: string;
  description?: string;
  agents: WorkflowAgent[];
  steps: WorkflowStep[];
  version?: string;
}

export interface WorkflowRun {
  id: string;
  workflowId: string;
  task: string; // User's original task description
  status: 'running' | 'completed' | 'failed' | 'paused';
  currentStepIndex: number;
  startedAt: string;
  completedAt?: string;
  error?: string;
}

export interface WorkflowStepRun {
  id: string;
  runId: string;
  stepId: string;
  agentId: string;
  groupFolder: string;
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped';
  input: string; // Rendered input
  output?: string;
  retryCount: number;
  startedAt?: string;
  completedAt?: string;
  error?: string;
}

// Note: Memory types removed - using Claude-Mem instead