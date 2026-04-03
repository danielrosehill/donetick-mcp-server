"""Donetick MCP server implementation."""

import asyncio
import json
import logging
import urllib.parse
from typing import Any

import httpx
from mcp.server import Server
from mcp.types import TextContent, Tool

from . import __version__
from .client import DonetickClient
from .config import config
from .models import ChoreCreate, ChoreUpdate

# Configure logging
config.configure_logging()
logger = logging.getLogger(__name__)

# Initialize MCP server
app = Server("donetick-chores")

# Global client instance (initialized on startup)
client: DonetickClient | None = None


async def get_client() -> DonetickClient:
    """Get or create the global Donetick client."""
    global client
    if client is None:
        client = DonetickClient()
    return client


# ==============================================================================
# Tool Definitions
# ==============================================================================

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available MCP tools."""
    return [
        # ── Chore CRUD ──────────────────────────────────────────────
        Tool(
            name="list_chores",
            description="List all chores. Filter by active status or assigned user. Use detail_level='brief' for compact output.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filter_active": {
                        "type": "boolean",
                        "description": "true=active only, false=inactive only, omit=all",
                    },
                    "assigned_to_user_id": {
                        "type": "integer",
                        "description": "Filter by assigned user ID",
                    },
                    "detail_level": {
                        "type": "string",
                        "enum": ["brief", "full"],
                        "description": "'brief' (id, name, status, assignee, dueDate) or 'full' (all fields). Default: full",
                    },
                },
            },
        ),
        Tool(
            name="get_chore",
            description="Get full details of a specific chore by ID, including subtasks and labels.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Chore ID"},
                },
                "required": ["chore_id"],
            },
        ),
        Tool(
            name="create_chore",
            description=(
                "Create a new chore. Use simple inputs like usernames and day names.\n\n"
                "EXAMPLES:\n"
                "- Simple: {name: 'Take out trash', days_of_week: ['Mon','Thu'], time_of_day: '19:00', usernames: ['Alice']}\n"
                "- One-time: {name: 'Fix faucet', due_date: '2025-11-10', priority: 3}\n"
                "- With subtasks: {name: 'Weekly review', subtask_names: ['Check email','Update notes']}\n\n"
                "If no usernames provided, chore is assigned to ANYONE in the circle (round-robin)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Chore name (required, 1-200 chars)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Chore description",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "Due date: YYYY-MM-DD or RFC3339",
                    },
                    "frequency_type": {
                        "type": "string",
                        "enum": ["once", "daily", "weekly", "monthly", "yearly",
                                 "days_of_the_week", "day_of_the_month",
                                 "interval_based", "adaptive", "no_repeat"],
                        "description": "How often it repeats (default: once). Use 'days_of_the_week' with days_of_week param for specific days.",
                    },
                    "frequency": {
                        "type": "integer",
                        "description": "Multiplier (e.g., 2=biweekly). Default: 1",
                        "minimum": 1,
                    },
                    "is_rolling": {
                        "type": "boolean",
                        "description": "Next due based on completion (true) vs fixed schedule (false). Default: false",
                    },
                    "days_of_week": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Days as short names: ['Mon','Wed','Fri']. Auto-sets frequency_type to days_of_the_week.",
                    },
                    "time_of_day": {
                        "type": "string",
                        "description": "Time in HH:MM format (e.g., '16:00')",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone (default: America/New_York)",
                    },
                    "usernames": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Assign by username/display name. First becomes primary assignee. If omitted, assigned to anyone.",
                    },
                    "assign_strategy": {
                        "type": "string",
                        "enum": ["least_completed", "least_assigned", "round_robin",
                                 "random", "keep_last_assigned", "random_except_last_assigned"],
                        "description": "How to rotate assignment. Default: round_robin (when anyone) or least_completed (when specific users)",
                    },
                    "label_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Labels by name (e.g., ['cleaning','urgent']). Must exist first — use create_label.",
                    },
                    "priority": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 4,
                        "description": "0=unset, 1=lowest, 2=low, 3=medium, 4=highest",
                    },
                    "points": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Points awarded on completion",
                    },
                    "is_private": {
                        "type": "boolean",
                        "description": "Visible only to creator. Default: false",
                    },
                    "subtask_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Checklist items: ['Step 1','Step 2']",
                    },
                    "remind_minutes_before": {
                        "type": "integer",
                        "description": "Remind X minutes before due time",
                    },
                    "remind_at_due_time": {
                        "type": "boolean",
                        "description": "Remind exactly at due time. Default: false",
                    },
                    "enable_nagging": {
                        "type": "boolean",
                        "description": "Repeated reminders until completed. Default: false",
                    },
                    "require_approval": {
                        "type": "boolean",
                        "description": "Require approval to mark complete. Default: false",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="update_chore",
            description=(
                "Update any chore fields. Only provide fields you want to change.\n\n"
                "Supports: name, description, schedule/frequency, assignees, priority, "
                "labels (add/remove/set by name), notifications, and more."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Chore ID to update"},
                    "name": {"type": "string", "description": "New name"},
                    "description": {"type": "string", "description": "New description"},
                    "nextDueDate": {"type": "string", "description": "New due date (ISO 8601)"},
                    "priority": {
                        "type": "integer", "minimum": 0, "maximum": 4,
                        "description": "Priority: 0=unset, 1=lowest, 4=highest",
                    },
                    "points": {"type": "integer", "description": "Points for completion"},
                    "isActive": {"type": "boolean", "description": "Enable/disable chore"},
                    "isPrivate": {"type": "boolean", "description": "Hide from circle"},
                    "requireApproval": {"type": "boolean", "description": "Require approval"},
                    # Schedule
                    "frequencyType": {
                        "type": "string",
                        "description": "Frequency: once, daily, weekly, days_of_the_week, monthly, yearly, etc.",
                    },
                    "frequency": {"type": "integer", "description": "Frequency multiplier"},
                    "frequencyMetadata": {"type": "object", "description": "Frequency config (days, time, timezone)"},
                    "isRolling": {"type": "boolean", "description": "Rolling vs fixed schedule"},
                    # Assignment
                    "assignee_usernames": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Reassign by username(s). First becomes primary assignee.",
                    },
                    "assignStrategy": {
                        "type": "string",
                        "enum": ["least_completed", "least_assigned", "round_robin",
                                 "random", "keep_last_assigned", "random_except_last_assigned"],
                        "description": "Assignment rotation strategy",
                    },
                    # Label management
                    "add_label_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Add labels by name (keeps existing)",
                    },
                    "remove_label_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Remove labels by name",
                    },
                    "set_label_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Replace ALL labels with these (by name)",
                    },
                    # Notifications
                    "notification": {"type": "boolean", "description": "Enable notifications"},
                    "notificationMetadata": {"type": "object", "description": "Notification settings"},
                },
                "required": ["chore_id"],
            },
        ),
        Tool(
            name="delete_chore",
            description="Delete a chore permanently. Only the creator can delete.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Chore ID to delete"},
                },
                "required": ["chore_id"],
            },
        ),
        Tool(
            name="list_archived_chores",
            description="List all archived (hidden) chores.",
            inputSchema={"type": "object", "properties": {}},
        ),

        # ── Chore Actions ───────────────────────────────────────────
        Tool(
            name="complete_chore",
            description="Mark a chore as complete.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Chore ID"},
                    "completed_by": {"type": "integer", "description": "User ID who completed it (optional)"},
                },
                "required": ["chore_id"],
            },
        ),
        Tool(
            name="skip_chore",
            description="Skip a chore without completing. For recurring chores, schedules the next occurrence.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Chore ID"},
                },
                "required": ["chore_id"],
            },
        ),
        Tool(
            name="archive_chore",
            description="Archive a chore (soft-delete / hide). Can be unarchived later.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Chore ID"},
                },
                "required": ["chore_id"],
            },
        ),
        Tool(
            name="unarchive_chore",
            description="Restore a previously archived chore.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Chore ID"},
                },
                "required": ["chore_id"],
            },
        ),
        Tool(
            name="approve_chore",
            description="Approve a chore completion that requires approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Chore ID"},
                },
                "required": ["chore_id"],
            },
        ),
        Tool(
            name="reject_chore",
            description="Reject a chore completion that requires approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Chore ID"},
                },
                "required": ["chore_id"],
            },
        ),
        Tool(
            name="update_due_date",
            description="Quickly reschedule a chore's due date without a full update.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Chore ID"},
                    "due_date": {"type": "string", "description": "New due date (YYYY-MM-DD or RFC3339)"},
                },
                "required": ["chore_id", "due_date"],
            },
        ),

        # ── Timer ────────────────────────────────────────────────────
        Tool(
            name="start_chore_timer",
            description="Start the time tracker for a chore.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Chore ID"},
                },
                "required": ["chore_id"],
            },
        ),
        Tool(
            name="pause_chore_timer",
            description="Pause the time tracker for a chore.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Chore ID"},
                },
                "required": ["chore_id"],
            },
        ),

        # ── Subtasks ────────────────────────────────────────────────
        Tool(
            name="update_subtask_completion",
            description="Mark a subtask complete or incomplete.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Parent chore ID"},
                    "subtask_id": {"type": "integer", "description": "Subtask ID"},
                    "completed": {"type": "boolean", "description": "true=complete, false=incomplete"},
                },
                "required": ["chore_id", "subtask_id", "completed"],
            },
        ),
        Tool(
            name="create_subtask",
            description="Add a new subtask/checklist item to an existing chore.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Parent chore ID"},
                    "name": {"type": "string", "description": "Subtask name"},
                },
                "required": ["chore_id", "name"],
            },
        ),
        Tool(
            name="delete_subtask",
            description="Remove a subtask from a chore.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Parent chore ID"},
                    "subtask_id": {"type": "integer", "description": "Subtask ID to remove"},
                },
                "required": ["chore_id", "subtask_id"],
            },
        ),
        Tool(
            name="convert_chore_to_subtask",
            description="Convert a standalone chore into a subtask of another chore. Deletes the original chore and creates a subtask with its name on the target.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_chore_id": {"type": "integer", "description": "Chore to convert (will be deleted)"},
                    "target_chore_id": {"type": "integer", "description": "Chore to add the subtask to"},
                },
                "required": ["source_chore_id", "target_chore_id"],
            },
        ),

        # ── Labels ───────────────────────────────────────────────────
        Tool(
            name="list_labels",
            description="List all labels in the circle.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="create_label",
            description="Create a new label for categorizing chores.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Label name"},
                    "color": {"type": "string", "description": "Hex color (e.g., '#FF5733')"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="update_label",
            description="Rename a label or change its color.",
            inputSchema={
                "type": "object",
                "properties": {
                    "label_id": {"type": "integer", "description": "Label ID"},
                    "name": {"type": "string", "description": "New name"},
                    "color": {"type": "string", "description": "New hex color"},
                },
                "required": ["label_id", "name"],
            },
        ),
        Tool(
            name="delete_label",
            description="Delete a label. Removes it from all chores.",
            inputSchema={
                "type": "object",
                "properties": {
                    "label_id": {"type": "integer", "description": "Label ID"},
                },
                "required": ["label_id"],
            },
        ),

        # ── Users & Circle ──────────────────────────────────────────
        Tool(
            name="list_circle_members",
            description="List all members in the circle with IDs, usernames, roles, and points. Use this to find user IDs for assignment.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_user_profile",
            description="Get the current user's profile (points, storage, notification config).",
            inputSchema={"type": "object", "properties": {}},
        ),

        # ── History & Analytics ──────────────────────────────────────
        Tool(
            name="get_chore_history",
            description="Get completion history. If chore_id provided, returns history for that chore. Otherwise returns all chores history with pagination.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Specific chore ID (optional — omit for all chores)"},
                    "limit": {"type": "integer", "description": "Max entries (default: 50, max: 200)", "minimum": 1, "maximum": 200},
                    "offset": {"type": "integer", "description": "Skip entries for pagination (default: 0)", "minimum": 0},
                },
            },
        ),
        Tool(
            name="get_chore_details",
            description="Get chore with completion statistics: total count, last completion, average duration, recent history.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chore_id": {"type": "integer", "description": "Chore ID"},
                },
                "required": ["chore_id"],
            },
        ),
    ]


# ==============================================================================
# Tool Handlers
# ==============================================================================

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool execution."""
    try:
        c = await get_client()

        # ── Chore CRUD ──────────────────────────────────────────
        if name == "list_chores":
            chores = await c.list_chores(
                filter_active=arguments.get("filter_active"),
                assigned_to_user_id=arguments.get("assigned_to_user_id"),
            )
            if not chores:
                return [TextContent(type="text", text="No chores found.")]

            detail_level = arguments.get("detail_level", "full")
            if detail_level == "brief":
                result = {
                    "count": len(chores),
                    "chores": [
                        {"id": ch.id, "name": ch.name, "isActive": ch.isActive,
                         "assignedTo": ch.assignedTo, "nextDueDate": ch.nextDueDate}
                        for ch in chores
                    ],
                }
            else:
                result = {"count": len(chores), "chores": [ch.model_dump() for ch in chores]}
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_chore":
            chore = await c.get_chore(arguments["chore_id"])
            if not chore:
                return [TextContent(type="text", text=f"Chore {arguments['chore_id']} not found.")]
            return [TextContent(type="text", text=json.dumps(chore.model_dump(), indent=2))]

        elif name == "create_chore":
            return await _handle_create_chore(c, arguments)

        elif name == "update_chore":
            return await _handle_update_chore(c, arguments)

        elif name == "delete_chore":
            await c.delete_chore(arguments["chore_id"])
            return [TextContent(type="text", text=f"Deleted chore {arguments['chore_id']}.")]

        elif name == "list_archived_chores":
            chores = await c.list_archived_chores()
            if not chores:
                return [TextContent(type="text", text="No archived chores.")]
            result = {"count": len(chores), "chores": [ch.model_dump() for ch in chores]}
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        # ── Chore Actions ───────────────────────────────────────
        elif name == "complete_chore":
            chore = await c.complete_chore(arguments["chore_id"], completed_by=arguments.get("completed_by"))
            return [TextContent(type="text", text=f"Completed '{chore.name}' (ID: {chore.id}).\n\n{json.dumps(chore.model_dump(), indent=2)}")]

        elif name == "skip_chore":
            chore = await c.skip_chore(arguments["chore_id"])
            return [TextContent(type="text", text=f"Skipped '{chore.name}'. Next due: {chore.nextDueDate}")]

        elif name == "archive_chore":
            await c.archive_chore(arguments["chore_id"])
            return [TextContent(type="text", text=f"Archived chore {arguments['chore_id']}.")]

        elif name == "unarchive_chore":
            await c.unarchive_chore(arguments["chore_id"])
            return [TextContent(type="text", text=f"Unarchived chore {arguments['chore_id']}.")]

        elif name == "approve_chore":
            await c.approve_chore(arguments["chore_id"])
            return [TextContent(type="text", text=f"Approved chore {arguments['chore_id']}.")]

        elif name == "reject_chore":
            await c.reject_chore(arguments["chore_id"])
            return [TextContent(type="text", text=f"Rejected chore {arguments['chore_id']}.")]

        elif name == "update_due_date":
            await c.update_due_date(arguments["chore_id"], arguments["due_date"])
            return [TextContent(type="text", text=f"Updated due date for chore {arguments['chore_id']} to {arguments['due_date']}.")]

        # ── Timer ────────────────────────────────────────────────
        elif name == "start_chore_timer":
            await c.start_chore(arguments["chore_id"])
            return [TextContent(type="text", text=f"Started timer for chore {arguments['chore_id']}.")]

        elif name == "pause_chore_timer":
            await c.pause_chore(arguments["chore_id"])
            return [TextContent(type="text", text=f"Paused timer for chore {arguments['chore_id']}.")]

        # ── Subtasks ─────────────────────────────────────────────
        elif name == "update_subtask_completion":
            chore = await c.update_subtask_completion(
                arguments["chore_id"], arguments["subtask_id"], arguments["completed"]
            )
            total = len(chore.subTasks)
            done = sum(1 for st in chore.subTasks if st.get('completedAt'))
            pct = (done / total * 100) if total > 0 else 0
            lines = [f"  {'[x]' if st.get('completedAt') else '[ ]'} {st.get('name', '?')} (ID: {st.get('id')})" for st in chore.subTasks]
            return [TextContent(type="text", text=f"Updated subtask. Progress: {done}/{total} ({pct:.0f}%)\n\n" + "\n".join(lines))]

        elif name == "create_subtask":
            chore = await c.get_chore(arguments["chore_id"])
            if not chore:
                return [TextContent(type="text", text=f"Chore {arguments['chore_id']} not found.")]
            # Add new subtask with negative ID (API converts to positive)
            existing = list(chore.subTasks)
            new_order = max((st.get('orderId', 0) for st in existing), default=-1) + 1
            new_id = -(new_order + 1)  # Negative IDs for new subtasks
            existing.append({
                "id": new_id, "orderId": new_order, "name": arguments["name"],
                "completedAt": None, "completedBy": 0, "parentId": None,
            })
            update = ChoreUpdate(subTasks=existing)
            updated = await c.update_chore(arguments["chore_id"], update)
            return [TextContent(type="text", text=f"Added subtask '{arguments['name']}' to chore '{updated.name}'.\n\nSubtasks: {len(updated.subTasks)}")]

        elif name == "delete_subtask":
            chore = await c.get_chore(arguments["chore_id"])
            if not chore:
                return [TextContent(type="text", text=f"Chore {arguments['chore_id']} not found.")]
            filtered = [st for st in chore.subTasks if st.get('id') != arguments["subtask_id"]]
            if len(filtered) == len(chore.subTasks):
                return [TextContent(type="text", text=f"Subtask {arguments['subtask_id']} not found in chore {arguments['chore_id']}.")]
            update = ChoreUpdate(subTasks=filtered)
            updated = await c.update_chore(arguments["chore_id"], update)
            return [TextContent(type="text", text=f"Removed subtask {arguments['subtask_id']} from chore '{updated.name}'. Remaining: {len(updated.subTasks)}")]

        elif name == "convert_chore_to_subtask":
            source = await c.get_chore(arguments["source_chore_id"])
            if not source:
                return [TextContent(type="text", text=f"Source chore {arguments['source_chore_id']} not found.")]
            target = await c.get_chore(arguments["target_chore_id"])
            if not target:
                return [TextContent(type="text", text=f"Target chore {arguments['target_chore_id']} not found.")]
            # Add source chore name as subtask on target
            existing = list(target.subTasks)
            new_order = max((st.get('orderId', 0) for st in existing), default=-1) + 1
            existing.append({
                "id": -(new_order + 1), "orderId": new_order, "name": source.name,
                "completedAt": None, "completedBy": 0, "parentId": None,
            })
            update = ChoreUpdate(subTasks=existing)
            await c.update_chore(arguments["target_chore_id"], update)
            # Delete the source chore
            await c.delete_chore(arguments["source_chore_id"])
            return [TextContent(type="text", text=f"Converted '{source.name}' (ID: {source.id}) into subtask of '{target.name}' (ID: {target.id}), and deleted the original chore.")]

        # ── Labels ───────────────────────────────────────────────
        elif name == "list_labels":
            labels = await c.get_labels()
            if not labels:
                return [TextContent(type="text", text="No labels found.")]
            lines = [f"- ID {lb.id}: {lb.name}" + (f" ({lb.color})" if lb.color else "") for lb in labels]
            return [TextContent(type="text", text="Labels:\n" + "\n".join(lines))]

        elif name == "create_label":
            label = await c.create_label(name=arguments["name"], color=arguments.get("color"))
            return [TextContent(type="text", text=f"Created label '{label.name}' (ID: {label.id}).")]

        elif name == "update_label":
            label = await c.update_label(label_id=arguments["label_id"], name=arguments["name"], color=arguments.get("color"))
            return [TextContent(type="text", text=f"Updated label {label.id} to '{label.name}'.")]

        elif name == "delete_label":
            await c.delete_label(arguments["label_id"])
            return [TextContent(type="text", text=f"Deleted label {arguments['label_id']}.")]

        # ── Users ────────────────────────────────────────────────
        elif name == "list_circle_members":
            members = await c.get_circle_members()
            lines = []
            for m in members:
                role_tag = " (admin)" if m.role == "admin" else ""
                display = m.displayName or m.username
                lines.append(f"- {display}{role_tag} — ID: {m.userId}, points: {m.points}")
            return [TextContent(type="text", text=f"{len(members)} member(s):\n" + "\n".join(lines))]

        elif name == "get_user_profile":
            profile = await c.get_user_profile()
            return [TextContent(type="text", text=json.dumps(profile.model_dump(), indent=2))]

        # ── History ──────────────────────────────────────────────
        elif name == "get_chore_history":
            chore_id = arguments.get("chore_id")
            if chore_id:
                history = await c.get_chore_history(chore_id)
            else:
                limit = arguments.get("limit", 50)
                offset = arguments.get("offset", 0)
                history = await c.get_all_chores_history(limit=limit, offset=offset)
            if not history:
                return [TextContent(type="text", text="No history found.")]
            entries = [h.model_dump() for h in history]
            return [TextContent(type="text", text=json.dumps({"count": len(entries), "history": entries}, indent=2))]

        elif name == "get_chore_details":
            details = await c.get_chore_details(arguments["chore_id"])
            return [TextContent(type="text", text=json.dumps(details.model_dump(), indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except httpx.HTTPStatusError as e:
        return _handle_http_error(name, e)
    except httpx.TimeoutException:
        return [TextContent(type="text", text="Error: Request timed out. Try again.")]
    except ValueError as e:
        return [TextContent(type="text", text=f"Validation error: {e}")]
    except Exception as e:
        logger.error(f"Error in tool {name}: {e}", exc_info=True)
        return [TextContent(type="text", text="Error: An unexpected error occurred. Check server logs.")]


# ==============================================================================
# Handler Helpers
# ==============================================================================

async def _handle_create_chore(c: DonetickClient, args: dict) -> list[TextContent]:
    """Handle create_chore with username lookups, anyone-default, and transformations."""
    # ── Assignment ──
    assigned_to = None
    assignees = []
    usernames = args.get("usernames", [])
    assign_strategy = args.get("assign_strategy")

    if usernames:
        # Specific users requested
        username_map = await c.lookup_user_ids(usernames)
        missing = [u for u in usernames if u not in (username_map or {})]
        if missing:
            return [TextContent(type="text", text=f"Error: User(s) not found: {', '.join(missing)}. Use list_circle_members to see available users.")]
        assigned_to = username_map[usernames[0]]
        assignees = [{"userId": uid} for uid in username_map.values()]
        if not assign_strategy:
            assign_strategy = "least_completed"
    else:
        # Default: assign to ANYONE in the circle (all members, round-robin)
        members = await c.get_circle_members()
        if members:
            assignees = [{"userId": m.userId} for m in members if m.isActive]
            if assignees:
                assigned_to = assignees[0]["userId"]
            if not assign_strategy:
                assign_strategy = "round_robin"

    if not assign_strategy:
        assign_strategy = "least_completed"

    # ── Labels ──
    labels_v2 = []
    label_names = args.get("label_names", [])
    if label_names:
        label_map = await c.lookup_label_ids(label_names)
        missing = [n for n in label_names if n not in (label_map or {})]
        if missing:
            return [TextContent(type="text", text=f"Error: Label(s) not found: {', '.join(missing)}. Use list_labels to see available, or create_label to make new ones.")]
        labels_v2 = [{"id": lid} for lid in label_map.values()]

    # ── Frequency ──
    frequency_type = args.get("frequency_type", "once")
    frequency_metadata = {}
    days_of_week = args.get("days_of_week", [])
    time_of_day = args.get("time_of_day")
    timezone = args.get("timezone", "America/New_York")

    if days_of_week and frequency_type == "once":
        frequency_type = "days_of_the_week"

    if frequency_type == "days_of_the_week" and not days_of_week:
        return [TextContent(type="text", text="Error: days_of_week is required for frequency_type='days_of_the_week'. Example: ['Mon','Wed','Fri']")]

    if days_of_week or time_of_day:
        frequency_metadata = c.transform_frequency_metadata(
            frequency_type=frequency_type, days_of_week=days_of_week,
            time=time_of_day, timezone=timezone,
        )

    # ── Notifications ──
    notification_metadata = {}
    remind_minutes = args.get("remind_minutes_before")
    remind_at_due = args.get("remind_at_due_time", False)
    nagging = args.get("enable_nagging", False)

    if remind_minutes is not None or remind_at_due or nagging:
        offset = -abs(remind_minutes) if remind_minutes else None
        notification_metadata = c.transform_notification_metadata(
            offset_minutes=offset, remind_at_due_time=remind_at_due, nagging=nagging,
        )

    # ── Subtasks ──
    sub_tasks = []
    subtask_names = args.get("subtask_names", [])
    if subtask_names:
        sub_tasks = c.transform_subtasks(subtask_names)

    # ── Due date ──
    due_date = args.get("due_date")
    if not due_date and frequency_type != "once":
        due_date = c.calculate_due_date(frequency_type, frequency_metadata, timezone)

    # ── Build and create ──
    chore_create = ChoreCreate(
        name=args["name"],
        description=args.get("description"),
        dueDate=due_date,
        frequencyType=frequency_type,
        frequency=args.get("frequency", 1),
        frequencyMetadata=frequency_metadata,
        isRolling=args.get("is_rolling", False),
        assignedTo=assigned_to,
        assignees=assignees,
        assignStrategy=assign_strategy,
        notification=bool(notification_metadata) or False,
        notificationMetadata=notification_metadata or None,
        priority=args.get("priority"),
        labelsV2=labels_v2,
        isActive=True,
        isPrivate=args.get("is_private", False),
        points=args.get("points"),
        subTasks=sub_tasks,
        requireApproval=args.get("require_approval", False),
    )

    chore = await c.create_chore(chore_create)
    return [TextContent(type="text", text=f"Created '{chore.name}' (ID: {chore.id})\n\n{json.dumps(chore.model_dump(), indent=2)}")]


async def _handle_update_chore(c: DonetickClient, args: dict) -> list[TextContent]:
    """Handle update_chore with label management and assignee lookups."""
    chore_id = args.pop("chore_id")

    # ── Label management ──
    add_labels = args.pop("add_label_names", None)
    remove_labels = args.pop("remove_label_names", None)
    set_labels = args.pop("set_label_names", None)
    labels_v2 = None

    if add_labels or remove_labels or set_labels:
        # Fetch current chore to get existing labels
        current = await c.get_chore(chore_id)
        if not current:
            return [TextContent(type="text", text=f"Chore {chore_id} not found.")]

        existing_labels = {lb.id: lb.name for lb in current.labelsV2}

        if set_labels is not None:
            # Replace all labels
            label_map = await c.lookup_label_ids(set_labels)
            missing = [n for n in set_labels if n not in (label_map or {})]
            if missing:
                return [TextContent(type="text", text=f"Error: Label(s) not found: {', '.join(missing)}")]
            labels_v2 = [{"id": lid} for lid in label_map.values()]
        else:
            current_ids = set(existing_labels.keys())

            if add_labels:
                label_map = await c.lookup_label_ids(add_labels)
                missing = [n for n in add_labels if n not in (label_map or {})]
                if missing:
                    return [TextContent(type="text", text=f"Error: Label(s) not found: {', '.join(missing)}")]
                current_ids |= set(label_map.values())

            if remove_labels:
                label_map = await c.lookup_label_ids(remove_labels)
                # Don't error on missing names during removal — just skip
                current_ids -= set(label_map.values())

            labels_v2 = [{"id": lid} for lid in current_ids]

    # ── Assignee lookup ──
    assignee_usernames = args.pop("assignee_usernames", None)
    if assignee_usernames:
        username_map = await c.lookup_user_ids(assignee_usernames)
        missing = [u for u in assignee_usernames if u not in (username_map or {})]
        if missing:
            return [TextContent(type="text", text=f"Error: User(s) not found: {', '.join(missing)}")]
        # Set assignedTo to first user, assignees to all
        user_ids = list(username_map.values())
        args["assignedTo"] = user_ids[0]
        args["assignees"] = [{"userId": uid} for uid in user_ids]

    # Build update from remaining args
    update_data = {k: v for k, v in args.items() if v is not None}
    if labels_v2 is not None:
        update_data["labelsV2"] = labels_v2

    try:
        update = ChoreUpdate(**update_data)
        chore = await c.update_chore(chore_id, update)
        return [TextContent(type="text", text=f"Updated '{chore.name}' (ID: {chore.id})\n\n{json.dumps(chore.model_dump(), indent=2)}")]
    except ValueError as e:
        return [TextContent(type="text", text=f"Validation error: {e}")]


def _handle_http_error(tool_name: str, e: httpx.HTTPStatusError) -> list[TextContent]:
    """Format HTTP errors with helpful hints."""
    logger.error(f"HTTP error in {tool_name}: {e.response.status_code} - {e.response.text}", exc_info=True)

    api_error = None
    try:
        error_data = e.response.json()
        api_error = error_data.get("error") or error_data.get("message")
    except Exception:
        try:
            api_error = e.response.text[:200] if e.response.text else None
        except Exception:
            pass

    code = e.response.status_code
    if code == 401:
        msg = "Authentication failed. Check DONETICK_USERNAME and DONETICK_PASSWORD."
    elif code == 403:
        msg = "Permission denied. You may not have access to this resource."
    elif code == 404:
        msg = "Not found. Use list_chores or list_labels to see available IDs."
    elif code == 422:
        msg = f"Validation error: {api_error or 'Check input format.'}"
    elif code == 429:
        msg = "Rate limit exceeded. Wait a moment and retry."
    elif 400 <= code < 500:
        msg = f"API error ({code}): {api_error or 'Check input parameters.'}"
    else:
        msg = f"Server error ({code}): {api_error or 'Try again later.'}"

    return [TextContent(type="text", text=f"Error: {msg}")]


# ==============================================================================
# Server Lifecycle
# ==============================================================================

async def cleanup():
    """Cleanup resources on shutdown."""
    global client
    if client:
        try:
            await client.close()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}", exc_info=True)
        finally:
            client = None


def sanitize_url(url: str) -> str:
    """Sanitize URL for logging by removing sensitive parts."""
    try:
        parsed = urllib.parse.urlparse(url)
        return f"{parsed.scheme}://[SERVER]{parsed.path}"
    except Exception:
        return "[URL]"


async def main_async_stdio():
    """Run the MCP server with stdio transport."""
    import sys

    from mcp.server.stdio import stdio_server

    print(f"Donetick MCP Server v{__version__} starting (stdio)...", file=sys.stderr)

    logger.info("Initializing stdio transport...")
    async with stdio_server() as (read_stream, write_stream):
        logger.info("Server running and ready to accept requests")
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


def run_http():
    """Run the MCP server with streamable HTTP transport."""
    import contextlib
    from collections.abc import AsyncIterator

    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.routing import Mount

    session_manager = StreamableHTTPSessionManager(
        app=app,
        json_response=False,
        stateless=False,
        session_idle_timeout=1800,
    )

    @contextlib.asynccontextmanager
    async def lifespan(starlette_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            logger.info(f"Streamable HTTP server ready on {config.host}:{config.port}")
            yield
        await cleanup()

    starlette_app = Starlette(
        debug=False,
        routes=[
            Mount("/mcp", app=session_manager.handle_request),
        ],
        lifespan=lifespan,
    )

    logger.info(f"Starting HTTP transport on {config.host}:{config.port}")
    uvicorn.run(
        starlette_app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )


def main():
    """Main entry point for the MCP server."""
    import sys
    import traceback

    logger.info(f"Starting Donetick MCP Server v{__version__}")
    logger.info(f"Connecting to: {sanitize_url(config.donetick_base_url)}")
    logger.info(f"Username: {config.donetick_username}")
    logger.info(f"Transport: {config.transport}")

    try:
        if config.transport == "http":
            run_http()
        else:
            asyncio.run(main_async_stdio())

    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as e:
        error_msg = f"Server error: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)
        print(error_msg, file=sys.stderr)
        sys.exit(1)
    finally:
        if config.transport != "http":
            try:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(cleanup())
                    elif not loop.is_closed():
                        loop.run_until_complete(cleanup())
                    else:
                        asyncio.run(cleanup())
                except RuntimeError:
                    asyncio.run(cleanup())
            except Exception as e:
                cleanup_error = f"Cleanup error: {e}\n{traceback.format_exc()}"
                logger.error(cleanup_error)
                print(cleanup_error, file=sys.stderr)


if __name__ == "__main__":
    import sys
    import traceback

    try:
        main()
    except Exception as e:
        error_msg = f"Failed to start server: {e}\n{traceback.format_exc()}"
        print(error_msg, file=sys.stderr)
        sys.exit(1)
