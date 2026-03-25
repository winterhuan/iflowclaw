# iFlowClaw

轻量级个人 AI 助手，基于 Python 单进程实现，当前以飞书群聊为主要消息入口，支持多 Agent 后端、按群组隔离工作目录、任务调度和 MCP 工具桥接。

## 当前状态

当前仓库的真实实现以 `src/iflowclaw/` 为准。

- 运行时：Python 3.11+
- 渠道：Feishu WebSocket 长连接
- 后端：`iflow`、`claude`、`agno`
- 执行模式：`direct`、`container`
- 调度：`cron`、`interval`、`once`
- 存储：SQLite
- Agent 工具桥：stdio MCP + 本地 IPC

说明：

- `iflow` 和 `claude` 是主路径能力。
- `agno` 和 `container` 已进入代码主线，但目前更适合视为实验性能力。
- 根目录旧文档里曾描述过更早的“两后端直连”架构，现已不再准确。

## 核心能力

- 飞书消息接入与群聊触发词路由
- 主群 / 普通群权限模型
- 每群独立目录、独立会话、独立 IPC 空间
- 多 Agent 后端切换
- Agent 在运行时调用 MCP 工具发送消息、创建任务、管理任务、注册群组
- 基于 `AGENTS.md` 和 `skills/` 的上下文与能力注入

## 项目结构

```text
iflowclaw/
├── src/iflowclaw/
│   ├── cli.py                    # 服务入口与主循环
│   ├── config.py                 # 配置加载
│   ├── db.py                     # SQLite 持久化
│   ├── router.py                 # 消息格式化与输出清洗
│   ├── group_queue.py            # 按群串行执行
│   ├── task_scheduler.py         # 调度扫描与运行记录
│   ├── ipc.py                    # IPC 文件监听与分发
│   ├── skills.py                 # skills 同步
│   ├── agents/
│   │   ├── runner.py             # 后端选择与统一运行入口
│   │   ├── prompting.py          # AGENTS.md 系统提示词拼装
│   │   ├── container_entry.py    # 容器内 Agent 入口
│   │   └── backends/
│   │       ├── iflow.py
│   │       ├── claude.py
│   │       ├── agno.py
│   │       └── container.py
│   ├── channels/
│   │   ├── registry.py
│   │   └── feishu.py
│   └── mcps/
│       └── ipc_mcp_stdio.py
├── groups/
│   ├── global/AGENTS.md
│   ├── main/AGENTS.md
│   └── <group>/AGENTS.md
├── skills/                       # 项目级 skills 源目录
├── docs/
├── tests/                        # 默认 pytest 覆盖的单元测试
├── tests_integration/            # 额外集成测试
└── container/                    # 容器相关构建物
```

## 运行流程

```text
Feishu message
  -> channel handler
  -> SQLite(messages/chats)
  -> message loop
  -> GroupQueue(按群串行 + 全局并发限制)
  -> AgentRunner
     -> direct backend / container backend
  -> MCP stdio server
  -> IPC files
  -> host IPC watcher
  -> send message / schedule task / register group
```

## 安装

按需安装依赖：

```bash
pip install -e .[iflow]
pip install -e .[claude]
pip install -e .[agno]
pip install -e .[all]
pip install -e .[dev]
```

## 启动

当前 CLI 入口只有 `run`：

```bash
python -m iflowclaw run
```

或者：

```bash
iflowclaw run
```

## 必需配置

最少需要：

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`

常用配置：

- `ASSISTANT_NAME`
- `AGENT_BACKEND`
- `DEFAULT_EXECUTION_MODE`
- `IFLOW_MODEL`
- `CLAUDE_MODEL`
- `AGNO_MODEL`
- `AGENT_TIMEOUT`
- `IDLE_TIMEOUT`
- `MAX_CONCURRENT_AGENTS`
- `TZ`

后端相关凭证：

- Claude：`ANTHROPIC_API_KEY` 或 `CLAUDE_CODE_OAUTH_TOKEN`
- iFlow / Agno：`OPENAI_API_KEY` 与可选 `OPENAI_BASE_URL`

## 群组与上下文

- 每个注册群组对应一个 `groups/<folder>/`
- 非主群会在系统提示词里自动拼接 `groups/global/AGENTS.md`
- 主群可通过 MCP 工具注册新群组、查看可见群组、跨群调度任务
- 项目级 `skills/` 会在运行前同步到不同后端的标准目录

## 内置 MCP 工具

当前内置工具：

- `send_message`
- `schedule_task`
- `list_tasks`
- `pause_task`
- `resume_task`
- `cancel_task`
- `update_task`
- `register_group`

## 测试

默认单元测试：

```bash
pytest
```

说明：

- `pyproject.toml` 当前只把 `tests/` 设为默认测试目录。
- `tests_integration/` 需要显式指定。
- 容器和真实后端测试依赖额外环境与凭证。

## 文档索引

- [架构说明](docs/ARCHITECTURE.md)
- [设计原则与范围](docs/REQUIREMENTS.md)
- [安全模型](docs/SECURITY.md)
- [记忆系统现状与规划](docs/MEMORY_SYSTEM_DESIGN.md)

## 已知边界

- 文档已按当前代码结构更新，但部分实验性能力仍在收敛中。
- 容器运行链路、挂载安全策略和部分集成测试仍需要继续打磨。
- 如果你要评估真实行为，请优先看 `src/iflowclaw/` 下实现，而不是旧提交中的说明。
