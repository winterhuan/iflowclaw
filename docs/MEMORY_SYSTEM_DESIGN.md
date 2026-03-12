# iFlowClaw 记忆功能设计文档

## 现状分析

### 当前已有但未被充分利用的组件

1. **session_stats 表** - 记录会话统计信息（消息数、重置次数等）
2. **session-history.ts** - 对话历史管理（保存/加载/格式化）
3. **summary-generator.ts** - 摘要生成（使用 iFlow CLI）

### 存在的问题

1. session-history 和 summary-generator 模块存在但未被主流程使用
2. 没有结构化的记忆存储机制
3. Agent 无法主动存取记忆
4. 跨会话上下文传递依赖 session_id 复用

## 记忆系统设计

### 核心概念

基于项目 AGENTS.md 中的上下文：

```
<internal>
这部分内容不会发送给用户，用于内部思考和记录。
</internal>
```

这个模式表明 Agent 已经有内部思考机制，我们可以利用这个来：
1. 让 Agent 自己决定什么时候保存重要信息
2. 在内部思考中记录关键决策、用户偏好等
3. 在后续对话中注入相关记忆

### 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                         iFlowClaw                               │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │   对话消息   │  │  session_stats│  │      memories        │  │
│  │   messages   │  │     表        │  │       表             │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│         │                   │                   │              │
│         ▼                   ▼                   ▼              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Memory Service (memory.ts)                  │  │
│  │  - 保存记忆 (save_memory)                                │  │
│  │  - 检索记忆 (search_memory)                              │  │
│  │  - 更新记忆 (update_memory)                              │  │
│  │  - 删除记忆 (delete_memory)                              │  │
│  │  - 获取上下文 (get_memory_context)                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              MCP Server (ipc-mcp-stdio.ts)               │  │
│  │  - save_memory 工具                                      │  │
│  │  - search_memory 工具                                    │  │
│  │  - list_memories 工具                                    │  │
│  │  - delete_memory 工具                                    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │               Agent Runner (agent-runner.ts)             │  │
│  │  - 启动时注入记忆上下文                                   │  │
│  │  - 消息处理时更新记忆                                     │  │
│  │  - Session 切换时生成摘要                                 │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 数据库表设计

#### memories 表

```sql
CREATE TABLE memories (
  id TEXT PRIMARY KEY,
  group_folder TEXT NOT NULL,
  session_id TEXT,
  category TEXT NOT NULL,      -- 'fact', 'preference', 'decision', 'task', 'summary'
  key TEXT NOT NULL,           -- 记忆的键/主题
  value TEXT NOT NULL,         -- 记忆的内容
  importance INTEGER DEFAULT 1, -- 重要性 1-5
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  expires_at TEXT,             -- 过期时间（可选）
  metadata TEXT                -- JSON 格式的额外元数据
);

CREATE INDEX idx_memories_group ON memories(group_folder);
CREATE INDEX idx_memories_category ON memories(category);
CREATE INDEX idx_memories_key ON memories(key);
CREATE INDEX idx_memories_created ON memories(created_at);
```

#### memory_categories 说明

- `fact` - 客观事实（如：用户的名字、公司信息）
- `preference` - 用户偏好（如：喜欢简洁回复、使用中文）
- `decision` - 重要决策（如：选择了某个方案）
- `task` - 待办事项（如：明天要检查的事情）
- `summary` - 会话摘要（由系统自动生成）
- `context` - 上下文信息（当前项目状态等）

### MCP 工具设计

#### save_memory

```typescript
{
  name: 'save_memory',
  description: '保存一条记忆。用于记录重要信息、用户偏好、决策结果等。记忆会在后续对话中自动提供上下文。',
  parameters: {
    key: string,        // 记忆的标识符，如 "user_name", "project_goal"
    value: string,      // 记忆的内容
    category: enum,     // 'fact' | 'preference' | 'decision' | 'task' | 'context'
    importance?: number, // 1-5，默认为 3
    expires_in_days?: number // 可选的过期天数
  }
}
```

#### search_memory

```typescript
{
  name: 'search_memory',
  description: '搜索记忆。根据关键词或类别查找之前保存的记忆。',
  parameters: {
    query?: string,     // 搜索关键词
    category?: string,  // 按类别筛选
    limit?: number      // 返回数量限制，默认 10
  }
}
```

#### list_memories

```typescript
{
  name: 'list_memories',
  description: '列出当前群组的所有记忆。',
  parameters: {
    category?: string,  // 按类别筛选
    limit?: number      // 返回数量限制，默认 20
  }
}
```

#### delete_memory

```typescript
{
  name: 'delete_memory',
  description: '删除一条记忆。',
  parameters: {
    key: string         // 记忆的键
  }
}
```

### 记忆注入机制

在 Agent 启动时，自动将相关记忆注入到 system prompt 中：

```typescript
function buildSystemPromptWithMemory(
  basePrompt: string,
  memories: Memory[],
  recentSummary?: SessionSummary
): string {
  const parts = [basePrompt];
  
  // 添加相关记忆
  if (memories.length > 0) {
    parts.push('\n\n=== 历史记忆 ===');
    memories.forEach(m => {
      parts.push(`- [${m.category}] ${m.key}: ${m.value}`);
    });
  }
  
  // 添加最近的会话摘要
  if (recentSummary) {
    parts.push('\n\n=== 上次对话摘要 ===');
    parts.push(recentSummary.summary);
  }
  
  return parts.join('\n');
}
```

### 自动摘要生成

当 session_stats 中的 messageCount 超过阈值（如 50）时：
1. 调用 summary-generator 生成摘要
2. 将摘要保存为 memory（category='summary'）
3. 可选择性地重置会话

## 实现步骤

1. **数据库层** - 添加 memories 表和相关函数
2. **服务层** - 创建 memory.ts 服务模块
3. **MCP 层** - 在 ipc-mcp-stdio.ts 中添加记忆工具
4. **集成层** - 在 agent-runner.ts 中集成记忆注入
5. **优化层** - 添加记忆检索算法、过期清理等

## 参考项目

### OpenClaw / Claude 记忆功能

参考 Claude 的记忆功能设计：
- 让 AI 主动决定什么值得记住
- 提供显式的记忆管理工具
- 在上下文中自然地注入记忆

### Mem0 / Zep

参考向量记忆数据库的设计：
- 语义搜索能力
- 记忆的重要性评分
- 自动过期和清理

