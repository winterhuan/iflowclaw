# iFlowClaw

> 一个你能真正理解的 AI 助手

iFlowClaw 是一个**轻量级的个人 AI 助手**，直接调用 iFlow SDK，没有复杂的容器层。

## 特性

- **直连 iFlow SDK** - 无需 Docker，单进程运行
- **飞书渠道** - WebSocket 长连接，无需公网地址
- **图片理解** - 支持图片消息识别
- **任务调度** - 支持 cron、interval、once 三种调度方式
- **群组管理** - 主群可管理所有群组，普通群独立运行
- **OAuth 登录** - `iflow login` 一键认证

## 安装

```bash
git clone https://github.com/winterhuan/iflowclaw.git
cd iflowclaw
npm install
```

## 快速开始

### 1. 创建飞书应用

访问 https://open.feishu.cn/app → 创建企业自建应用

### 2. 获取凭证并配置权限

在「凭证与基础信息」复制 App ID 和 App Secret。

在「权限管理」→「批量添加」，粘贴：

```json
{
  "scopes": {
    "tenant": [
      "im:message",
      "im:message.group_at_msg:readonly",
      "im:message.p2p_msg:readonly",
      "im:message:readonly",
      "im:message:send_as_bot",
      "im:resource"
    ],
    "user": []
  }
}
```

### 3. 启用机器人

在「应用能力」→「机器人」中启用机器人能力。

### 4. 配置本项目

```bash
npm run setup   # 输入 App ID 和 Secret
iflow login     # iFlow OAuth 认证
```

### 5. 启动服务

```bash
npm start
```

### 6. 配置事件订阅

**重要：必须先启动服务再配置此步骤**

在飞书开放平台「事件订阅」中：
- 选择「使用长连接接收事件」
- 添加事件：`im.message.receive_v1`

### 7. 发布应用

在「版本管理与发布」中创建版本并发布，等待审批后即可使用。

## 启动方式

| 命令 | 说明 |
|------|------|
| `npm start` | 后台运行（推荐生产使用） |
| `npm run run` | 前台运行（直接查看日志） |
| `npm run dev` | 开发模式（tsx 运行源码） |
| `npm run dev:watch` | 开发热重载 |

## 全局命令

安装后可执行以下命令将 `iflowclaw` 链接到全局，之后可在任意目录使用：

```bash
npm link
iflowclaw setup    # 配置飞书凭证
iflowclaw start    # 启动服务
iflowclaw stop     # 停止服务
iflowclaw status   # 查看状态
iflowclaw logs     # 查看日志
```

## 管理命令

在项目目录下也可以通过 npm scripts 运行：

```bash
npm run setup    # 配置飞书凭证
npm start        # 启动服务
npm run stop     # 停止服务
npm run restart  # 重启服务
npm run status   # 查看状态
npm run logs     # 查看日志
```

或直接运行脚本：

```bash
./bin/iflowclaw setup
./bin/iflowclaw start
./bin/iflowclaw stop
./bin/iflowclaw status
./bin/iflowclaw logs
```

## 配置

### 必需环境变量

| 变量 | 说明 |
|------|------|
| `FEISHU_APP_ID` | 飞书 App ID |
| `FEISHU_APP_SECRET` | 飞书 App Secret |

### 可选配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ASSISTANT_NAME` | `iFlow` | 助手名称（影响触发词） |
| `AGENT_TIMEOUT` | `60000` | Agent 超时时间（ms） |
| `MAX_CONCURRENT_AGENTS` | `5` | 最大并发 Agent 数 |
| `LOG_LEVEL` | `info` | 日志等级 |
| `TZ` | 系统时区 | 任务调度时区 |

## 项目结构

```
iflowclaw/
├── bin/iflowclaw      # CLI 管理工具
├── src/               # 源代码
├── groups/            # 群组目录
│   ├── global/        # 全局共享上下文
│   └── main/          # 主群目录
├── data/              # 运行时数据
├── logs/              # 日志文件
└── store/             # SQLite 数据库
```

## 开发

```bash
npm run build      # 构建
npm run typecheck  # 类型检查
npm test           # 运行测试
```

## 鸣谢

- [NanoClaw](https://github.com/qwibitai/nanoclaw) - 架构灵感
- [iFlow CLI](https://www.npmjs.com/package/@iflow-ai/iflow-cli) - SDK 和 OAuth 认证

## 许可证

MIT
