# /status - Quick Health Check

Use this skill when the user sends `/status`.

## Response Format

Generate a concise status report with these sections:

### Session

- Current timestamp (ISO format)
- Working directory
- Group folder name

### Workspace

List visible workspace directories:

- `{{GROUP_DIR}}/` — group memory and files
- `{{GLOBAL_DIR}}/` — shared memory (if accessible)
- `{{IPC_DIR}}/` — IPC communication directory
- `{{PROJECT_DIR}}/` — project root (main group only)

### Tools

Check tool availability:

- **Core:** Bash, Read, Write, Edit, Glob, Grep
- **Web:** WebSearch, WebFetch
- **MCP:** IPC tools (send_message, schedule_task, list_tasks, etc.)

### Tasks

Use `list_tasks` MCP tool to show scheduled tasks count and next upcoming task.

### Output

Present as a clean, concise message. No markdown headers in the output — just bold labels and bullet points.
