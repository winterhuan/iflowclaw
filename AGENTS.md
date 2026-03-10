# iFlowClaw 项目指南

## 项目概述

iFlowClaw 是一个轻量级个人 AI 助手，基于 iFlow SDK 与飞书渠道构建。

当前版本采用**主机进程直连 iFlow SDK**的架构，不使用 Docker 容器层。核心目标是：

- 单进程、少文件、易理解
- 按群组隔离工作目录与会话
- 在最小复杂度下支持任务调度与 MCP 工具

## 核心特性

- **飞书渠道**：基于飞书 WebSocket 长连接接收消息
- **主群/普通群权限模型**：主群可管理全部群与任务，普通群仅管理本群
- **触发词机制**：默认 `@iFlow`（随 `ASSISTANT_NAME` 变化）
- **发送者白名单**：支持 `trigger/drop` 两种模式
- **任务调度**：支持 `cron`、`interval`、`once`
- **图片理解扩展**：`image-vision` 扩展把图片引用注入 Agent 输入
- **MCP 工具桥接**：Agent 通过本地 MCP 服务器访问发消息、任务管理、群管理能力
- **群组隔离目录**：每个群组使用独立 `groups/<folder>/` 与 `data/ipc/<folder>/`

## 技术栈

| 类别 | 技术 |
|------|------|
| 运行时 | Node.js 20+ (ES Modules) |
| 语言 | TypeScript（严格模式） |
| AI SDK | `@iflow-ai/iflow-cli-sdk` |
| 渠道 SDK | `@larksuiteoapi/node-sdk` |
| 数据库 | SQLite (`better-sqlite3`) |
| 调度 | `cron-parser` |
| 日志 | `pino` |
| 校验 | `zod` |
| 测试 | `vitest` |

## 项目结构

```text
iflowclaw/
├── src/
│   ├── index.ts                  # 主入口（启动渠道、调度、IPC、消息循环）
│   ├── agent-runner.ts           # iFlow SDK 直连执行与会话复用
│   ├── agent-utils.ts            # Agent 运行封装、快照写入
│   ├── mcp-server.ts             # MCP stdio server（供 Agent 调用）
│   ├── ipc.ts                    # IPC watcher（消息/任务文件处理与鉴权）
│   ├── group-queue.ts            # 按群串行 + 全局并发控制
│   ├── task-scheduler.ts         # 定时任务调度执行
│   ├── db.ts                     # SQLite schema 与数据访问
│   ├── router.ts                 # 消息格式化与输出路由
│   ├── sender-allowlist.ts       # 发送者白名单
│   ├── group-folder.ts           # 群组目录安全校验与路径解析
│   ├── config.ts / env.ts        # 配置读取
│   ├── channels/
│   │   ├── feishu.ts             # 飞书渠道实现
│   │   ├── index.ts              # 渠道模块加载
│   │   └── registry.ts           # 渠道注册表
│   ├── extensions/
│   │   ├── index.ts              # 扩展注册入口（显式注册）
│   │   ├── types.ts              # 扩展类型
│   │   └── image-vision/         # 图片理解扩展
│   └── *.test.ts                 # 单元测试
├── groups/
│   ├── global/                   # 全局共享上下文（如 global/AGENTS.md）
│   └── main/                     # 主群目录（示例）
├── data/ipc/                     # 运行期 IPC 目录
├── store/messages.db             # SQLite 数据库文件
├── start.sh                      # 启动脚本（安装依赖、读取配置、构建并启动）
├── .env.example
└── package.json
```

## 快速开始

### 系统要求

- Node.js 20+
- iFlow CLI（用于 OAuth）
- 飞书应用凭证（`FEISHU_APP_ID`、`FEISHU_APP_SECRET`）

### 启动

```bash
git clone https://github.com/qwibitai/iflowclaw.git
cd iflowclaw
npm start
```

首次启动会提示输入飞书应用凭证，并写入 `.env`。

### 开发命令

```bash
npm run dev
npm run build
npm run typecheck
npm test
```

## 认证方式

推荐 OAuth 登录：

```bash
iflow login
```

SDK 会读取 `~/.iflow/settings.json` 凭证。

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
| `AGENT_TIMEOUT` | `60000` | 单次 Agent 超时（ms） |
| `IDLE_TIMEOUT` | `60000` | 空闲关闭输入等待时长（ms） |
| `MAX_CONCURRENT_AGENTS` | `5` | 全局并发 Agent 数上限 |
| `LOG_LEVEL` | `info` | 日志等级 |
| `TZ` | 系统时区 | 任务调度时区 |
| `IFLOW_BASE_URL` | `https://apis.iflow.cn/v1` | iFlow API 地址 |

### 发送者白名单

白名单文件路径：`~/.config/iflowclaw/sender-allowlist.json`

- `mode: "trigger"`：仅限制谁可触发
- `mode: "drop"`：拒绝者消息直接丢弃（不入库）

## 运行架构

```text
飞书消息
  -> Channel(Feishu)
  -> DB(messages/chats)
  -> Message Loop + Trigger 判定
  -> GroupQueue(按群串行 + 并发上限)
  -> Agent Runner(iFlow SDK)
  -> MCP(消息/任务/群管理 via IPC)
  -> 渠道发送回复
```

关键点：

- 每个群组维护独立 session（`sessions` 表）
- 主群可查看/管理所有群和任务，普通群仅可操作本群资源
- IPC 按目录身份鉴权（`data/ipc/<group>/`）
- 扩展在 `src/extensions/index.ts` 显式注册，无自动发现

## MCP 工具（内置）

`src/mcp-server.ts` 暴露的主要工具：

- `send_message`
- `schedule_task`
- `pause_task`
- `resume_task`
- `cancel_task`
- `update_task`
- `list_tasks`
- `list_groups`
- `register_group`（仅主群）
- `refresh_groups`（仅主群）

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
- `session_stats`

## 扩展开发

1. 新建 `src/extensions/my-feature/index.ts`
2. 导出 `AgentInputExtension` 或 `MessageHandlerExtension`
3. 在 `src/extensions/index.ts` 显式注册

示例：

```typescript
import type { AgentInputExtension } from '../types.js';

export const myExtension: AgentInputExtension = {
  name: 'my-feature',
  version: '1.0.0',
  enhanceAgentInput: (_context, draft) => {
    draft.containerInput.myFlag = true;
  },
};
```

## 关键文件

| 文件 | 作用 |
|------|------|
| `src/index.ts` | 系统编排入口 |
| `src/agent-runner.ts` | iFlow SDK 客户端生命周期与会话复用 |
| `src/mcp-server.ts` | Agent 与主进程交互工具面 |
| `src/ipc.ts` | IPC 消息/任务消费与鉴权 |
| `src/group-queue.ts` | 并发和串行策略 |
| `src/task-scheduler.ts` | 到期任务执行 |
| `src/db.ts` | 数据模型与迁移 |
| `src/channels/feishu.ts` | 飞书通道 |
| `src/extensions/image-vision/` | 图片理解扩展 |

## 故障排查

### 启动后提示没有可用渠道

- 检查 `.env` 中 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`
- 使用 `npm run dev` 查看实时日志

### iFlow 调用失败或未登录

- 运行 `iflow login`
- 检查 `~/.iflow/settings.json` 是否存在

### 任务不执行

- 检查任务是否 `status=active`
- 检查 `next_run` 是否已到期、`TZ` 是否正确
- 查看 `task_run_logs` 与应用日志

### 群注册或任务操作被拒绝

- 确认是否在主群执行（主群有跨群管理权限）
- 检查群组 `folder` 是否符合安全命名规则

## 鸣谢

- [NanoClaw](https://github.com/qwibitai/nanoclaw)
- [iFlow CLI](https://www.npmjs.com/package/@iflow-ai/iflow-cli)

## 许可证

MIT
