# Donetick MCP Server

[![PyPI](https://img.shields.io/pypi/v/donetick-mcp)](https://pypi.org/project/donetick-mcp/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An MCP server for [Donetick](https://donetick.com) chores management. Gives Claude and other MCP-compatible AI assistants full control over your Donetick instance — 27 tools covering chores, subtasks, labels, timers, and more.

## Quick Start

```bash
uvx donetick-mcp
```

### Claude Desktop / Claude Code

Add to your MCP config (`.mcp.json`, `claude_desktop_config.json`, etc.):

```json
{
  "mcpServers": {
    "donetick": {
      "command": "uvx",
      "args": ["donetick-mcp"],
      "env": {
        "DONETICK_BASE_URL": "https://your-instance.com",
        "DONETICK_USERNAME": "your_username",
        "DONETICK_PASSWORD": "your_password"
      }
    }
  }
}
```

> **Note:** `DONETICK_BASE_URL` can be HTTP for local/private network instances.

## Tools (27)

### Chore Management

| Tool | Description |
|------|-------------|
| `list_chores` | List chores with optional filters (active, assigned user, brief/full detail) |
| `get_chore` | Get full chore details including subtasks and labels |
| `create_chore` | Create a chore — supports usernames, day names, reminders, subtasks. Defaults to assigning to **anyone** in the circle (round-robin) |
| `update_chore` | Update any fields: name, description, schedule, assignees (by username), labels (add/remove/set by name), priority, notifications |
| `delete_chore` | Delete a chore (creator only) |
| `list_archived_chores` | List archived/hidden chores |

### Chore Actions

| Tool | Description |
|------|-------------|
| `complete_chore` | Mark a chore as done |
| `skip_chore` | Skip without completing — schedules next occurrence for recurring chores |
| `archive_chore` | Soft-delete / hide a chore |
| `unarchive_chore` | Restore an archived chore |
| `approve_chore` | Approve a completion that requires approval |
| `reject_chore` | Reject a completion that requires approval |
| `update_due_date` | Quick reschedule without a full update |

### Timer

| Tool | Description |
|------|-------------|
| `start_chore_timer` | Start time tracking |
| `pause_chore_timer` | Pause time tracking |

### Subtasks

| Tool | Description |
|------|-------------|
| `create_subtask` | Add a checklist item to a chore |
| `delete_subtask` | Remove a subtask |
| `update_subtask_completion` | Mark a subtask complete/incomplete |
| `convert_chore_to_subtask` | Convert a standalone chore into a subtask of another (deletes the original) |

### Labels

| Tool | Description |
|------|-------------|
| `list_labels` | List all labels in the circle |
| `create_label` | Create a new label (name + optional hex color) |
| `update_label` | Rename or recolor a label |
| `delete_label` | Delete a label (removes from all chores) |

> Labels can also be managed directly on chores via `update_chore` using `add_label_names`, `remove_label_names`, or `set_label_names`.

### Users & History

| Tool | Description |
|------|-------------|
| `list_circle_members` | List all members with IDs, roles, and points |
| `get_user_profile` | Current user's profile, points, and settings |
| `get_chore_history` | Completion history — for one chore or all (with pagination) |
| `get_chore_details` | Chore stats: total completions, average duration, recent history |

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DONETICK_BASE_URL` | Yes | — | Donetick instance URL |
| `DONETICK_USERNAME` | Yes | — | Donetick username |
| `DONETICK_PASSWORD` | Yes | — | Donetick password |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `RATE_LIMIT_PER_SECOND` | No | `10.0` | API rate limit |
| `RATE_LIMIT_BURST` | No | `10` | Burst capacity |

## Create Chore Examples

Simple one-time chore:
```json
{"name": "Fix leaky faucet", "due_date": "2025-11-10", "priority": 3}
```

Recurring chore on specific days:
```json
{"name": "Take out trash", "days_of_week": ["Mon", "Thu"], "time_of_day": "19:00", "usernames": ["Alice"]}
```

With subtasks and reminders:
```json
{"name": "Weekly review", "frequency_type": "weekly", "subtask_names": ["Check email", "Update notes"], "remind_minutes_before": 15}
```

If no `usernames` provided, the chore is assigned to **everyone** in the circle with round-robin rotation.

## Alternative Installation

### Docker

```bash
git clone https://github.com/danielrosehill/donetick-mcp.git
cd donetick-mcp
cp .env.example .env  # edit with your credentials
docker-compose up -d
```

### pip

```bash
pip install donetick-mcp
donetick-mcp  # requires env vars set
```

## Development

```bash
git clone https://github.com/danielrosehill/donetick-mcp.git
cd donetick-mcp
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
pytest  # 200 tests, requires DONETICK_* env vars
```

## License

MIT

## Links

- [Donetick](https://donetick.com) — Open source chores management
- [PyPI Package](https://pypi.org/project/donetick-mcp/)
- [MCP Protocol](https://modelcontextprotocol.io)
