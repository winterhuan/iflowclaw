# /capabilities - Capability Report

Use this skill when the user sends `/capabilities`.

## Purpose

Generate a structured read-only report of what this iFlowClaw instance can do.

## Checks

### Skills

List available skills by checking the skills directory contents.

### Tools

- **Core:** Bash, Read, Write, Edit, Glob, Grep
- **Web:** WebSearch, WebFetch
- **Orchestration:** Task (subagent spawning)
- **MCP Tools:** send_message, schedule_task, list_tasks, pause_task, resume_task, cancel_task, update_task, register_group

### System

- Agent backend in use (iflow/claude/agno)
- Execution mode (direct/container)
- Container runtime availability (if container mode)

### Group Info

- Whether group memory (`AGENTS.md`) exists
- Whether global memory is accessible
- Additional mounts (if configured)

## Output

Present as a clean message with sections: Skills, Tools, System, Group Info. Use bullet points, no markdown headers in output.
