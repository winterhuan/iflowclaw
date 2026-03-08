# iFlowClaw

A lightweight, secure personal AI assistant using the iFlow platform with container isolation.

## Features

- **Container Isolation**: Agents run in Docker containers for security
- **Multi-Channel Support**: WhatsApp, Telegram, Discord, Slack, Feishu (extensible)
- **Task Scheduling**: Cron, interval, and one-time scheduled tasks
- **Group Memory**: Per-group CLAUDE.md files for context persistence
- **iFlow Platform**: Uses iFlow AI services (free models available!)
- **OAuth Login**: Use `iflow login` for easy authentication

## Requirements

- Node.js 20+
- Docker
- iFlow CLI (for OAuth login)

## Quick Start

### 1. Install iFlow CLI and Login (Recommended)

```bash
# Install iFlow CLI
npm install -g @iflow-ai/iflow-cli

# Login with iFlow (opens browser for OAuth)
iflow login
```

This stores your credentials in `~/.iflow/settings.json`. iFlowClaw will automatically use them!

### 2. Clone and Setup

```bash
git clone https://github.com/your-org/iflowclaw.git
cd iflowclaw
npm install
cd container/agent-runner && npm install && cd ../..
```

### 3. Build the Container

```bash
cd container && ./build.sh
```

### 4. Run

```bash
npm run build
npm start
```

## Authentication

iFlowClaw supports two authentication methods:

### Method 1: OAuth Login (Recommended)

```bash
# Login once with iFlow CLI
iflow login
```

The container will automatically mount `~/.iflow/` and use your OAuth credentials. No configuration needed!

### Method 2: API Key (Headless/Servers)

For servers without browser access:

```bash
# Get your API key from https://platform.iflow.cn
export IFLOW_API_KEY=your-api-key-here
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    HOST (Main Process)                   │
│  ┌─────────────┐   ┌─────────────┐   ┌──────────────┐  │
│  │  Channels   │   │  Scheduler  │   │ IPC Watcher  │  │
│  └──────┬──────┘   └──────┬──────┘   └──────────────┘  │
│         └────────────────┬┘                             │
│                          ▼                              │
├─────────────────────────────────────────────────────────┤
│              CONTAINER (Isolated Sandbox)                │
│  ┌─────────────────────────────────────────────────┐   │
│  │  iFlow Agent Runner - iFlow SDK + Tools + MCP   │   │
│  │  Auth: ~/.iflow/ (OAuth) or API Key             │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

## Configuration

| Variable | Description | Required |
|----------|-------------|----------|
| `IFLOW_API_KEY` | API key (only for headless) | No* |
| `IFLOW_BASE_URL` | Custom API endpoint | No |
| `IFLOW_MODEL_NAME` | Model selection | No |
| `ASSISTANT_NAME` | Bot mention name | No (default: iFlow) |
| `CONTAINER_IMAGE` | Docker image name | No |
| `MAX_CONCURRENT_CONTAINERS` | Parallel limit | No (default: 5) |

\* Not required if you've logged in with `iflow login`

## Key Differences from NanoClaw

| Feature | NanoClaw | iFlowClaw |
|---------|----------|-----------|
| AI Backend | Anthropic Claude | iFlow Platform |
| SDK | `@anthropic-ai/claude-agent-sdk` | `@iflow-ai/iflow-cli-sdk` |
| Auth | OAuth Token | OAuth Login / API Key |
| Cost | Paid subscription | Free tier available |

## License

MIT
