# iFlowClaw

轻量级个人 AI 助手，基于 Python 单进程实现，当前以飞书群聊为主要消息入口，支持多 Agent 后端、按群组隔离工作目录、任务调度和 MCP 工具桥接。

## 当前状态

当前仓库的真实实现以 `src/iflowclaw/` 为准。

- 运行时：Python 3.11+
- 渠道：Feishu WebSocket 长连接
- 后端：`iflow`、`claude`、`agno`、`container`
- 执行模式：`direct`、`container`
- 调度：`cron`、`interval`、`once`
- 存储：SQLite
- Agent 工具桥：stdio MCP + 本地 IPC

说明：

- `iflow`、`claude`、`agno`、`container` 均为主路径能力。
- `container` 模式支持在 Docker/Podman 中隔离运行 `claude`、`iflow`、`agno` 子后端。

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

```bash
# 安装全部后端
pip install -e ".[all]"

# 或按需安装
pip install -e ".[iflow]"      # iFlow 后端
pip install -e ".[claude]"     # Claude 后端
pip install -e ".[agno]"       # Agno 后端（仅支持 OpenAI）
pip install -e ".[dev]"        # 开发依赖
```

安装后 `iflowclaw` 命令全局可用。

## 快速开始

```bash
# 1. 初始化配置（交互式输入飞书凭证等）
iflowclaw init

# 2. 前台运行（测试）
iflowclaw run

# 3. 安装为用户服务（登录后自启）
iflowclaw install
```

## 命令一览

```bash
iflowclaw init              # 初始化配置
iflowclaw run               # 前台运行服务

iflowclaw install           # 安装为用户服务
iflowclaw start             # 启动服务
iflowclaw stop              # 停止服务
iflowclaw restart           # 重启服务
iflowclaw status            # 查看服务状态
iflowclaw logs              # 查看日志
iflowclaw logs -f           # 实时跟踪日志
```

## 配置说明

配置文件：项目根目录 `.env`

必需配置：

| 变量 | 说明 |
|------|------|
| `FEISHU_APP_ID` | 飞书应用 ID |
| `FEISHU_APP_SECRET` | 飞书应用密钥 |

常用可选配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ASSISTANT_NAME` | `iFlow` | 助手名称，影响触发词 |
| `AGENT_BACKEND` | `iflow` | 默认后端 (iflow/claude/agno/container) |
| `EXECUTION_MODE` | `direct` | 执行模式 (direct/container) |
| `OPENAI_MODEL` | - | iFlow 后端模型 |
| `CLAUDE_MODEL` | - | Claude 后端模型 |
| `AGNO_MODEL` | - | Agno 后端模型 (`gpt-4o` 或 `openai:gpt-4o`) |
| `AGENT_TIMEOUT` | `300000` | Agent 超时（毫秒） |
| `IDLE_TIMEOUT` | `180000` | 空闲关闭输入等待（毫秒） |
| `MAX_CONCURRENT_AGENTS` | `5` | 全局并发 Agent 上限 |
| `LOG_LEVEL` | `info` | 日志等级 |
| `TZ` | 系统时区 | 任务调度时区 |

后端凭证：

- **Claude**：`ANTHROPIC_API_KEY` 或 `CLAUDE_CODE_OAUTH_TOKEN`
- **iFlow**：运行 `iflow login` 后 SDK 自动读取 `~/.iflow/settings.json`
- **Agno**：设置 `OPENAI_API_KEY`，可选 `OPENAI_BASE_URL`

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
