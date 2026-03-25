# iFlowClaw 架构说明

## 概览

iFlowClaw 当前是一个 Python 单进程服务。主进程负责接入消息、持久化、串行化执行、调度、IPC 和 Agent 运行编排。

系统目标：

- 少进程、少中间层、便于理解
- 按群组隔离目录与会话
- 用统一的 `AgentRunner` 屏蔽后端差异
- 用 MCP + IPC 暴露宿主能力给 Agent

## 模块分层

### 1. 入口与编排

- `src/iflowclaw/cli.py`
- `src/iflowclaw/config.py`
- `src/iflowclaw/logging.py`

职责：

- 加载配置
- 初始化数据库
- 启动飞书渠道
- 启动 IPC watcher
- 启动任务调度器
- 启动消息轮询与群组队列

### 2. 渠道层

- `src/iflowclaw/channels/registry.py`
- `src/iflowclaw/channels/feishu.py`

职责：

- 建立渠道连接
- 将原始消息转换为统一的 `NewMessage`
- 回调主进程进行落库和元数据更新

当前只有 Feishu 渠道进入代码主线。

### 3. 数据层

- `src/iflowclaw/db.py`
- `src/iflowclaw/types.py`
- `src/iflowclaw/snapshots.py`

职责：

- 存储消息、会话、任务、路由状态、注册群组
- 输出任务快照与群组快照

当前主要表：

- `chats`
- `messages`
- `scheduled_tasks`
- `task_run_logs`
- `router_state`
- `sessions`
- `registered_groups`

### 4. 消息路由与串行执行

- `src/iflowclaw/router.py`
- `src/iflowclaw/group_queue.py`
- `src/iflowclaw/sender_allowlist.py`

职责：

- 格式化历史消息为 Agent 输入
- 处理发送者白名单
- 对每个群组做串行消费
- 全局限制并发 Agent 数量

### 5. Agent 执行层

- `src/iflowclaw/agents/runner.py`
- `src/iflowclaw/agents/prompting.py`
- `src/iflowclaw/agents/backends/*.py`
- `src/iflowclaw/agents/container_entry.py`

职责：

- 构建系统提示词
- 决定后端与执行模式
- 将统一的 `AgentInput` 转换为具体 SDK 调用

当前后端矩阵：

| backend | mode | 状态 |
| --- | --- | --- |
| `iflow` | `direct` | 主路径 |
| `claude` | `direct` | 主路径 |
| `agno` | `direct` | 实验性 |
| `container` | host wrapper | 实验性 |

### 6. MCP 与 IPC

- `src/iflowclaw/mcps/ipc_mcp_stdio.py`
- `src/iflowclaw/ipc.py`

设计：

- Agent 进程只通过 stdio MCP 调用宿主工具
- MCP 工具不直接改数据库，而是写 IPC JSON 文件
- 主进程轮询 IPC 目录并执行真实动作

这样做的好处：

- 后端 SDK 只需要能跑 stdio MCP
- Agent 不直接持有主进程对象
- 容器模式和直连模式可以复用同一套工具协议

### 7. 调度

- `src/iflowclaw/task_scheduler.py`

职责：

- 定期扫描到期任务
- 将任务投递回群组队列
- 记录任务运行日志
- 计算下一次运行时间

## 主消息链路

```text
Feishu
  -> FeishuChannel
  -> store_message / store_chat_metadata
  -> message_loop
  -> GroupQueue.enqueue_message_check(chat_jid)
  -> process_group_messages(chat_jid)
  -> AgentRunner.run(...)
  -> backend SDK
  -> MCP stdio tool call
  -> IPC JSON file
  -> start_ipc_watcher()
  -> send_message / create_task / update_task / register_group
```

## 调度链路

```text
scheduled_tasks
  -> scheduler loop
  -> due task
  -> GroupQueue.enqueue_task(task)
  -> AgentRunner.run(...)
  -> output
  -> task_run_logs + next_run update
```

## 群组隔离模型

每个群组有自己的一组资源：

- 工作目录：`groups/<folder>/`
- IPC 目录：`data/ipc/<folder>/`
- 会话 ID：`sessions` 表按 `group_folder` 维护
- 可选独立 `AGENTS.md`

额外规则：

- 主群拥有管理权限
- 非主群默认只管理自己的任务和消息
- 非主群系统提示词会额外拼接 `groups/global/AGENTS.md`

## 提示词与 skills

提示词来自：

- `groups/<folder>/AGENTS.md`
- 非主群再叠加 `groups/global/AGENTS.md`

skills 来自项目级 `skills/` 目录，并在运行前同步到不同后端所需路径：

- Claude：`.claude/skills/`
- iFlow：`.iflow/skills/`
- Agno：`skills/`

文档模板变量会在同步时替换：

- `{{GROUP_DIR}}`
- `{{GLOBAL_DIR}}`
- `{{IPC_DIR}}`
- `{{PROJECT_DIR}}`

## 执行模式

### direct

主进程直接使用 Python SDK 调用对应 Agent 后端。

特点：

- 实现简单
- 调试成本低
- 更适合当前主路径

### container

宿主机启动容器，容器内再运行 `iflowclaw.agents.container_entry`。

特点：

- 便于隔离执行环境
- 方便接入浏览器、容器级依赖
- 当前仍在演进中，相关镜像构建和安全收敛未完全稳定

## 当前文档边界

本文件描述的是当前仓库中的 Python 实现。

以下内容不再准确：

- 旧版 README 中的 `bin/iflowclaw` 管理脚本
- 旧版 TypeScript / Node.js 目录示意
- “只支持两个后端、只支持直连执行”的说法
