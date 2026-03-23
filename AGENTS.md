# iFlowClaw 项目指南

## 项目概述

iFlowClaw 是一个轻量级个人 AI 助手，基于 Python 构建，支持飞书渠道和多 Agent SDK 后端。

当前版本采用**主机进程直连 Agent SDK**的架构，支持以下 Agent 后端：

- **iFlow CLI SDK** (`iflow-cli-sdk`)
- **Claude Agent SDK** (`claude-agent-sdk`)

核心目标是：

- 单进程、少文件、易理解
- 按群组隔离工作目录与会话
- 支持多 Agent SDK 后端切换
- 在最小复杂度下支持任务调度与 MCP 工具

## 核心特性

- **飞书渠道**：基于飞书 WebSocket 长连接接收消息
- **主群/普通群权限模型**：主群可管理全部群与任务，普通群仅管理本群
- **触发词机制**：默认 `@iFlow`（随 `ASSISTANT_NAME` 变化）
- **发送者白名单**：支持 `trigger/drop` 两种模式
- **任务调度**：支持 `cron`、`interval`、`once`
- **多 Agent 后端**：支持 iFlow 和 Claude 两种 SDK，可按群组配置
- **MCP 工具桥接**：Agent 通过本地 MCP 服务器访问发消息、任务管理、群管理能力
- **群组隔离目录**：每个群组使用独立 `groups/<folder>/` 与 `data/ipc/<folder>/`

## 技术栈

| 类别 | 技术 |
|------|------|
| 运行时 | Python 3.11+ |
| AI SDK | `iflow-cli-sdk` / `claude-agent-sdk` |
| 渠道 SDK | `lark-oapi` |
| 数据库 | SQLite (stdlib `sqlite3`) |
| 调度 | `croniter` |
| 日志 | stdlib `logging` |
| 校验 | `pydantic` |
| 测试 | `pytest` |

## 项目结构

```text
iflowclaw/
├── iflowclaw/                      # Python 包
│   ├── __init__.py
│   ├── __main__.py                 # python -m iflowclaw 入口
│   ├── cli.py                      # CLI 与服务主循环
│   ├── config.py                   # 配置加载
│   ├── env.py                      # .env 文件解析
│   ├── logging.py                  # 日志配置
│   ├── types.py                    # 数据类型定义
│   ├── db.py                       # SQLite 数据库
│   ├── router.py                   # 消息格式化与路由
│   ├── group_queue.py              # 按群串行 + 全局并发控制
│   ├── group_folder.py             # 群组目录路径解析
│   ├── task_scheduler.py           # 定时任务调度
│   ├── sender_allowlist.py         # 发送者白名单
│   ├── ipc.py                      # IPC 文件监听
│   ├── snapshots.py                # 任务/群组快照
│   ├── tools.py                    # 工具定义与执行
│   │
│   ├── agents/                     # Agent 执行核心
│   │   ├── runner.py               # Agent 运行器（后端路由）
│   │   ├── prompting.py            # 系统提示词构建
│   │   └── backends/               # Agent 后端实现
│   │       ├── base.py             # 后端协议定义
│   │       ├── iflow.py            # IFlow SDK 后端
│   │       └── claude.py           # Claude SDK 后端
│   │
│   ├── channels/                   # 消息渠道
│   │   ├── registry.py             # 渠道注册
│   │   └── feishu.py               # 飞书渠道
│   │
│   └── mcps/                       # MCP 服务器
│       └── ipc_mcp_stdio.py        # IPC MCP stdio 服务器
│
├── groups/                         # 群组目录
│   ├── global/AGENTS.md            # 全局共享上下文
│   └── <folder>/AGENTS.md          # 各群组独立配置
│
├── tests_py/                       # Python 测试
├── data/ipc/                       # 运行期 IPC 目录
├── store/messages.db               # SQLite 数据库
├── AGENTS.md                       # 项目指南
└── pyproject.toml                  # Python 项目配置
```

## 快速开始

### 系统要求

- Python 3.11+
- iFlow CLI（如使用 iFlow 后端）
- 飞书应用凭证（`FEISHU_APP_ID`、`FEISHU_APP_SECRET`）

### 安装

```bash
git clone <repo-url>
cd iflowclaw

# 安装全部依赖（iFlow + Claude）
pip install -e ".[all]"

# 或仅安装需要的后端
pip install -e ".[iflow]"
pip install -e ".[claude]"
```

### 启动

```bash
# 直接运行
python -m iflowclaw run
```

首次启动会提示输入飞书应用凭证，并写入 `.env`。

> **提示**：生产环境推荐使用 **systemd** 管理服务。

### 开发命令

```bash
python -m pytest tests_py/ -v    # 运行测试
python -m ruff check iflowclaw/  # 代码检查
```

## 认证方式

### iFlow 后端

推荐 OAuth 登录：

```bash
iflow login
```

SDK 会读取 `~/.iflow/settings.json` 凭证。

### Claude 后端

设置环境变量：

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

## 配置说明

### 必需配置

| 变量 | 描述 |
|------|------|
| `FEISHU_APP_ID` | 飞书应用 ID |
| `FEISHU_APP_SECRET` | 飞书应用密钥 |

### 常用可选配置

| 变量 | 默认值 | 描述 |
|------|--------|------|
| `ASSISTANT_NAME` | `iFlow` | 助手名称，影响触发词正则 |
| `AGENT_BACKEND` | `iflow` | 默认 Agent 后端 (`iflow` / `claude`) |
| `IFLOW_MODEL` | - | iFlow 后端默认模型 |
| `CLAUDE_MODEL` | - | Claude 后端默认模型 |
| `AGENT_TIMEOUT` | `300000` | 单次 Agent 超时（ms） |
| `IDLE_TIMEOUT` | `180000` | 空闲关闭输入等待时长（ms） |
| `MAX_CONCURRENT_AGENTS` | `5` | 全局并发 Agent 数上限 |
| `LOG_LEVEL` | `info` | 日志等级 |
| `TZ` | 系统时区 | 任务调度时区 |

### 发送者白名单

白名单文件路径：`~/.config/iflowclaw/sender-allowlist.json`

- `mode: "trigger"`：仅限制谁可触发
- `mode: "drop"`：拒绝者消息直接丢弃（不入库）

## Agent 后端架构

```text
AgentRunner
  ├── 根据 agent_config.backend 选择后端
  │
  ├── IFlowBackend (iflow-cli-sdk)
  │   ├── IFlowClient 连接
  │   ├── MCP 工具桥接
  │   └── 流式消息处理
  │
  └── ClaudeBackend (claude-agent-sdk)
      ├── query() 调用
      ├── SDK MCP Server
      └── 权限控制
```

### Per-Group 后端配置

每个群组可以在 `registered_groups` 表的 `agent_config` 字段中配置独立的后端：

```json
{
  "backend": "claude",
  "model": "sonnet",
  "timeout": 600000
}
```

## 运行架构

```text
飞书消息
  -> Channel(Feishu)
  -> DB(messages/chats)
  -> Message Loop + Trigger 判定
  -> GroupQueue(按群串行 + 并发上限)
  -> AgentRunner -> IFlowBackend / ClaudeBackend
  -> MCP(消息/任务/群管理 via IPC)
  -> 渠道发送回复
```

## MCP 工具（内置）

Agent 可通过 MCP 使用以下工具：

- `send_message`：立即向当前会话发送消息
- `schedule_task`：调度定时任务（cron, interval, once）
- `list_tasks`：查看当前已调度的任务列表
- `pause_task`：暂停任务
- `resume_task`：恢复任务
- `cancel_task`：取消并删除任务
- `update_task`：更新现有任务
- `register_group`：注册新群组（仅限主群）

## 任务调度说明

- `schedule_type=cron`：使用 cron 表达式
- `schedule_type=interval`：毫秒间隔
- `schedule_type=once`：一次性 ISO 时间
- `context_mode=group`：复用群组会话
- `context_mode=isolated`：独立上下文执行

## 数据库表

- `chats`
- `messages`
- `scheduled_tasks`
- `task_run_logs`
- `router_state`
- `sessions`
- `registered_groups`

## 许可证

MIT
