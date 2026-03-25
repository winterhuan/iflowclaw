# Agent Browser Skill

Use the `agent-browser` CLI for browser automation tasks.

## Commands

### Navigation

- `agent-browser open <url>` — open a URL
- `agent-browser back` — go back
- `agent-browser forward` — go forward
- `agent-browser reload` — reload page
- `agent-browser close` — close browser

### Snapshots

- `agent-browser snapshot` — full accessibility tree
- `agent-browser snapshot --refs-only` — interactive elements only
- `agent-browser snapshot --selector <css>` — scoped by CSS selector

### Interactions

Use `@ref` identifiers from snapshots:

- `agent-browser click @ref`
- `agent-browser dblclick @ref`
- `agent-browser fill @ref "text"`
- `agent-browser type @ref "text"`
- `agent-browser press @ref KeyName`
- `agent-browser hover @ref`
- `agent-browser check @ref` / `agent-browser uncheck @ref`
- `agent-browser select @ref "option"`
- `agent-browser scroll @ref down 500`

### Get Information

- `agent-browser text @ref` — element text
- `agent-browser html @ref` — element HTML
- `agent-browser value @ref` — input value
- `agent-browser title` — page title
- `agent-browser url` — current URL

### Screenshots

- `agent-browser screenshot` — full page PNG
- `agent-browser screenshot --selector <css>` — element screenshot
- `agent-browser pdf` — page as PDF

### Wait

- `agent-browser wait @ref` — wait for element
- `agent-browser wait 2000` — wait milliseconds
- `agent-browser wait text "Hello"` — wait for text
- `agent-browser wait idle` — wait for network idle

### JavaScript

- `agent-browser eval "document.title"` — evaluate JS expression

## Tool Permission

Requires: `Bash(agent-browser:*)`
