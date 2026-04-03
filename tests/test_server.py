"""Integration tests for MCP server tools."""

import json

import pytest
from pytest_httpx import HTTPXMock

from donetick_mcp.server import call_tool, list_tools

BASE = "https://donetick.jason1365.duckdns.org"


@pytest.fixture
def sample_chore_data():
    """Sample chore data for testing."""
    return {
        "id": 1,
        "name": "Test Chore",
        "description": "Test description",
        "frequencyType": "once",
        "frequency": 1,
        "frequencyMetadata": {},
        "nextDueDate": "2025-11-10T00:00:00Z",
        "isRolling": False,
        "assignedTo": 1,
        "assignees": [{"userId": 1}],
        "assignStrategy": "least_completed",
        "isActive": True,
        "notification": False,
        "notificationMetadata": {"nagging": False, "predue": False},
        "labels": None,
        "labelsV2": [],
        "circleId": 1,
        "createdAt": "2025-11-03T00:00:00Z",
        "updatedAt": "2025-11-03T00:00:00Z",
        "createdBy": 1,
        "updatedBy": 1,
        "status": "active",
        "priority": 2,
        "isPrivate": False,
        "points": None,
        "subTasks": [],
        "thingChore": None,
    }


@pytest.fixture
def sample_members():
    """Sample circle members data."""
    return [
        {
            "id": 1, "userId": 1, "circleId": 1, "role": "admin",
            "isActive": True, "username": "alice", "displayName": "Alice",
            "points": 100, "pointsRedeemed": 25,
        },
        {
            "id": 2, "userId": 2, "circleId": 1, "role": "member",
            "isActive": True, "username": "bob", "displayName": "Bob",
            "points": 80, "pointsRedeemed": 10,
        },
    ]


class TestToolListing:
    """Test tool registration."""

    @pytest.mark.asyncio
    async def test_list_tools_count_and_names(self):
        tools = await list_tools()
        names = [t.name for t in tools]

        # 27 tools total
        assert len(tools) == 27

        # Chore CRUD
        for n in ["list_chores", "get_chore", "create_chore", "update_chore",
                   "delete_chore", "list_archived_chores"]:
            assert n in names

        # Chore actions
        for n in ["complete_chore", "skip_chore", "archive_chore", "unarchive_chore",
                   "approve_chore", "reject_chore", "update_due_date"]:
            assert n in names

        # Timer
        assert "start_chore_timer" in names
        assert "pause_chore_timer" in names

        # Subtasks
        for n in ["update_subtask_completion", "create_subtask", "delete_subtask",
                   "convert_chore_to_subtask"]:
            assert n in names

        # Labels
        for n in ["list_labels", "create_label", "update_label", "delete_label"]:
            assert n in names

        # Users
        assert "list_circle_members" in names
        assert "get_user_profile" in names

        # History
        assert "get_chore_history" in names
        assert "get_chore_details" in names

        # Removed tools should NOT be present
        for n in ["update_chore_priority", "update_chore_assignee",
                   "list_circle_users", "get_all_chores_history",
                   "get_circle_members"]:
            assert n not in names


class TestChoreCRUD:
    """Test chore CRUD tools."""

    @pytest.mark.asyncio
    async def test_list_chores(self, sample_chore_data, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/", json=[sample_chore_data])
        result = await call_tool("list_chores", {})
        data = json.loads(result[0].text)
        assert data["count"] == 1
        assert data["chores"][0]["name"] == "Test Chore"

    @pytest.mark.asyncio
    async def test_list_chores_brief(self, sample_chore_data, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/", json=[sample_chore_data])
        result = await call_tool("list_chores", {"detail_level": "brief"})
        data = json.loads(result[0].text)
        assert set(data["chores"][0].keys()) == {"id", "name", "isActive", "assignedTo", "nextDueDate"}

    @pytest.mark.asyncio
    async def test_list_chores_empty(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/", json=[])
        result = await call_tool("list_chores", {})
        assert "No chores found" in result[0].text

    @pytest.mark.asyncio
    async def test_get_chore(self, sample_chore_data, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=sample_chore_data)
        result = await call_tool("get_chore", {"chore_id": 1})
        data = json.loads(result[0].text)
        assert data["id"] == 1
        assert data["name"] == "Test Chore"

    @pytest.mark.asyncio
    async def test_get_chore_not_found(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/999", status_code=404)
        result = await call_tool("get_chore", {"chore_id": 999})
        assert "not found" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_create_chore_with_anyone_default(self, sample_chore_data, sample_members, httpx_mock: HTTPXMock, mock_login):
        """Create chore with no usernames — should assign to all circle members."""
        # Mock circle members lookup (for "anyone" default)
        httpx_mock.add_response(url=f"{BASE}/api/v1/circles/members/", json=sample_members)
        # Mock POST create
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/", json={"res": 1}, method="POST")
        # Mock GET fetch of created chore
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=sample_chore_data, method="GET")

        result = await call_tool("create_chore", {"name": "Test Chore"})
        assert "Created" in result[0].text
        assert "Test Chore" in result[0].text

    @pytest.mark.asyncio
    async def test_create_chore_with_usernames(self, sample_chore_data, sample_members, httpx_mock: HTTPXMock, mock_login):
        """Create chore assigned to specific users."""
        # Mock circle members lookup
        httpx_mock.add_response(url=f"{BASE}/api/v1/circles/members/", json=sample_members)
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/", json={"res": 1}, method="POST")
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=sample_chore_data, method="GET")

        result = await call_tool("create_chore", {"name": "Test", "usernames": ["alice"]})
        assert "Created" in result[0].text

    @pytest.mark.asyncio
    async def test_create_chore_username_not_found(self, sample_members, httpx_mock: HTTPXMock, mock_login):
        """Create chore with nonexistent username fails gracefully."""
        httpx_mock.add_response(url=f"{BASE}/api/v1/circles/members/", json=sample_members)
        result = await call_tool("create_chore", {"name": "Test", "usernames": ["nobody"]})
        assert "not found" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_delete_chore(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json={}, method="DELETE")
        result = await call_tool("delete_chore", {"chore_id": 1})
        assert "Deleted" in result[0].text

    @pytest.mark.asyncio
    async def test_update_chore_basic(self, sample_chore_data, httpx_mock: HTTPXMock, mock_login):
        """Update chore name and description."""
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=sample_chore_data, method="GET")
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/", json={"message": "ok"}, method="PUT")
        updated = {**sample_chore_data, "name": "Updated Name"}
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=updated, method="GET")

        result = await call_tool("update_chore", {"chore_id": 1, "name": "Updated Name"})
        assert "Updated" in result[0].text

    @pytest.mark.asyncio
    async def test_update_chore_with_label_add(self, sample_chore_data, httpx_mock: HTTPXMock, mock_login):
        """Update chore by adding labels."""
        # 1st GET: _handle_update_chore fetches chore for existing labels
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=sample_chore_data, method="GET")
        # Label lookup
        httpx_mock.add_response(url=f"{BASE}/api/v1/labels", json=[{"id": 10, "name": "cleaning", "color": "#fff"}])
        # 2nd GET: client.update_chore() fetches chore (fetch-modify-send)
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=sample_chore_data, method="GET")
        # PUT: send update
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/", json={"message": "ok"}, method="PUT")
        # 3rd GET: client.update_chore() fetches updated chore to return
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=sample_chore_data, method="GET")

        result = await call_tool("update_chore", {"chore_id": 1, "add_label_names": ["cleaning"]})
        assert "Updated" in result[0].text

    @pytest.mark.asyncio
    async def test_update_chore_with_assignee_usernames(self, sample_chore_data, sample_members, httpx_mock: HTTPXMock, mock_login):
        """Update chore assignees by username."""
        httpx_mock.add_response(url=f"{BASE}/api/v1/circles/members/", json=sample_members)
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=sample_chore_data, method="GET")
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/", json={"message": "ok"}, method="PUT")
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=sample_chore_data, method="GET")

        result = await call_tool("update_chore", {"chore_id": 1, "assignee_usernames": ["bob"]})
        assert "Updated" in result[0].text

    @pytest.mark.asyncio
    async def test_list_archived_chores(self, sample_chore_data, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/archived", json=[sample_chore_data])
        result = await call_tool("list_archived_chores", {})
        data = json.loads(result[0].text)
        assert data["count"] == 1


class TestChoreActions:
    """Test chore action tools."""

    @pytest.mark.asyncio
    async def test_complete_chore(self, sample_chore_data, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1/do", json=sample_chore_data, method="POST")
        result = await call_tool("complete_chore", {"chore_id": 1})
        assert "Completed" in result[0].text

    @pytest.mark.asyncio
    async def test_skip_chore(self, sample_chore_data, httpx_mock: HTTPXMock, mock_login):
        chore = {**sample_chore_data, "nextDueDate": "2025-11-17"}
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1/skip", json=chore, method="POST")
        result = await call_tool("skip_chore", {"chore_id": 1})
        assert "Skipped" in result[0].text

    @pytest.mark.asyncio
    async def test_archive_chore(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1/archive", json={}, method="PUT")
        result = await call_tool("archive_chore", {"chore_id": 1})
        assert "Archived" in result[0].text

    @pytest.mark.asyncio
    async def test_unarchive_chore(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1/unarchive", json={}, method="PUT")
        result = await call_tool("unarchive_chore", {"chore_id": 1})
        assert "Unarchived" in result[0].text

    @pytest.mark.asyncio
    async def test_approve_chore(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1/approve", json={}, method="POST")
        result = await call_tool("approve_chore", {"chore_id": 1})
        assert "Approved" in result[0].text

    @pytest.mark.asyncio
    async def test_reject_chore(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1/reject", json={}, method="POST")
        result = await call_tool("reject_chore", {"chore_id": 1})
        assert "Rejected" in result[0].text

    @pytest.mark.asyncio
    async def test_update_due_date(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1/dueDate", json={}, method="PUT")
        result = await call_tool("update_due_date", {"chore_id": 1, "due_date": "2025-12-01"})
        assert "Updated due date" in result[0].text

    @pytest.mark.asyncio
    async def test_start_timer(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1/start", json={}, method="PUT")
        result = await call_tool("start_chore_timer", {"chore_id": 1})
        assert "Started timer" in result[0].text

    @pytest.mark.asyncio
    async def test_pause_timer(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1/pause", json={}, method="PUT")
        result = await call_tool("pause_chore_timer", {"chore_id": 1})
        assert "Paused timer" in result[0].text


class TestSubtasks:
    """Test subtask tools."""

    @pytest.mark.asyncio
    async def test_create_subtask(self, sample_chore_data, httpx_mock: HTTPXMock, mock_login):
        # 1st GET: server handler fetches chore
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=sample_chore_data, method="GET")
        # 2nd GET: client.update_chore() fetch-modify-send
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=sample_chore_data, method="GET")
        # PUT update
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/", json={"message": "ok"}, method="PUT")
        # 3rd GET: client.update_chore() fetches result
        updated = {**sample_chore_data, "subTasks": [{"id": 1, "name": "New task", "orderId": 0}]}
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=updated, method="GET")

        result = await call_tool("create_subtask", {"chore_id": 1, "name": "New task"})
        assert "Added subtask" in result[0].text

    @pytest.mark.asyncio
    async def test_delete_subtask(self, sample_chore_data, httpx_mock: HTTPXMock, mock_login):
        chore_with_subtask = {**sample_chore_data, "subTasks": [{"id": 5, "name": "Old task", "orderId": 0}]}
        # 1st GET: server handler fetches chore
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=chore_with_subtask, method="GET")
        # 2nd GET: client.update_chore() fetch-modify-send
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=chore_with_subtask, method="GET")
        # PUT update
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/", json={"message": "ok"}, method="PUT")
        # 3rd GET: client.update_chore() fetches result
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=sample_chore_data, method="GET")

        result = await call_tool("delete_subtask", {"chore_id": 1, "subtask_id": 5})
        assert "Removed subtask" in result[0].text

    @pytest.mark.asyncio
    async def test_delete_subtask_not_found(self, sample_chore_data, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1", json=sample_chore_data, method="GET")
        result = await call_tool("delete_subtask", {"chore_id": 1, "subtask_id": 999})
        assert "not found" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_convert_chore_to_subtask(self, sample_chore_data, httpx_mock: HTTPXMock, mock_login):
        source = {**sample_chore_data, "id": 10, "name": "Source Chore"}
        target = {**sample_chore_data, "id": 20, "name": "Target Chore"}

        # 1st GET: server handler fetches source chore
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/10", json=source, method="GET")
        # 2nd GET: server handler fetches target chore
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/20", json=target, method="GET")
        # 3rd GET: client.update_chore() fetch-modify-send for target
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/20", json=target, method="GET")
        # PUT update target with subtask
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/", json={"message": "ok"}, method="PUT")
        # 4th GET: client.update_chore() fetches updated target
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/20", json=target, method="GET")
        # DELETE source
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/10", json={}, method="DELETE")

        result = await call_tool("convert_chore_to_subtask", {"source_chore_id": 10, "target_chore_id": 20})
        assert "Converted" in result[0].text
        assert "Source Chore" in result[0].text


class TestLabels:
    """Test label tools."""

    @pytest.mark.asyncio
    async def test_list_labels(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/labels", json=[
            {"id": 1, "name": "cleaning", "color": "#80d8ff"},
            {"id": 2, "name": "urgent", "color": None},
        ])
        result = await call_tool("list_labels", {})
        assert "cleaning" in result[0].text
        assert "urgent" in result[0].text

    @pytest.mark.asyncio
    async def test_list_labels_empty(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/labels", json=[])
        result = await call_tool("list_labels", {})
        assert "No labels" in result[0].text

    @pytest.mark.asyncio
    async def test_create_label(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/labels", json={"id": 1, "name": "outdoor", "color": "#4caf50"}, method="POST")
        result = await call_tool("create_label", {"name": "outdoor", "color": "#4caf50"})
        assert "Created label" in result[0].text

    @pytest.mark.asyncio
    async def test_update_label(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/labels", json={"res": {"id": 1, "name": "deep-clean", "color": "#00bcd4"}}, method="PUT")
        result = await call_tool("update_label", {"label_id": 1, "name": "deep-clean"})
        assert "Updated label" in result[0].text

    @pytest.mark.asyncio
    async def test_delete_label(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/labels/1", json={}, method="DELETE")
        result = await call_tool("delete_label", {"label_id": 1})
        assert "Deleted label" in result[0].text


class TestUsers:
    """Test user/member tools."""

    @pytest.mark.asyncio
    async def test_list_circle_members(self, sample_members, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/circles/members/", json=sample_members)
        result = await call_tool("list_circle_members", {})
        assert "2 member(s)" in result[0].text
        assert "alice" in result[0].text.lower() or "Alice" in result[0].text

    @pytest.mark.asyncio
    async def test_get_user_profile(self, httpx_mock: HTTPXMock, mock_login):
        profile = {
            "id": 1, "username": "alice", "displayName": "Alice",
            "email": "alice@test.com", "circleId": 1, "points": 100,
            "pointsRedeemed": 25, "isActive": True,
        }
        httpx_mock.add_response(url=f"{BASE}/api/v1/users/profile", json=profile)
        result = await call_tool("get_user_profile", {})
        data = json.loads(result[0].text)
        assert data["username"] == "alice"


class TestHistory:
    """Test history tools."""

    @pytest.mark.asyncio
    async def test_get_chore_history_specific(self, httpx_mock: HTTPXMock, mock_login):
        history = [
            {"id": 1, "choreId": 1, "performedAt": "2025-11-05T10:00:00Z",
             "completedBy": 1, "status": "completed"},
        ]
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1/history", json=history)
        result = await call_tool("get_chore_history", {"chore_id": 1})
        data = json.loads(result[0].text)
        assert data["count"] == 1

    @pytest.mark.asyncio
    async def test_get_chore_history_all(self, httpx_mock: HTTPXMock, mock_login):
        history = [
            {"id": 1, "choreId": 1, "performedAt": "2025-11-05T10:00:00Z",
             "completedBy": 1, "status": "completed"},
            {"id": 2, "choreId": 2, "performedAt": "2025-11-06T10:00:00Z",
             "completedBy": 2, "status": "completed"},
        ]
        httpx_mock.add_response(
            url=f"{BASE}/api/v1/chores/history?limit=50&offset=0", json=history,
        )
        result = await call_tool("get_chore_history", {})
        data = json.loads(result[0].text)
        assert data["count"] == 2

    @pytest.mark.asyncio
    async def test_get_chore_history_empty(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1/history", json=[])
        result = await call_tool("get_chore_history", {"chore_id": 1})
        assert "No history" in result[0].text

    @pytest.mark.asyncio
    async def test_get_chore_details(self, sample_chore_data, httpx_mock: HTTPXMock, mock_login):
        details = {**sample_chore_data, "totalCompletedCount": 5, "averageDuration": 120.5}
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/1/details", json=details)
        result = await call_tool("get_chore_details", {"chore_id": 1})
        data = json.loads(result[0].text)
        assert data["totalCompletedCount"] == 5


class TestErrorHandling:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        result = await call_tool("unknown_tool", {})
        assert "Unknown tool" in result[0].text

    @pytest.mark.asyncio
    async def test_http_500_error(self, httpx_mock: HTTPXMock, mock_login):
        for _ in range(3):
            httpx_mock.add_response(url=f"{BASE}/api/v1/chores/", status_code=500, json={"error": "Internal error"})
        result = await call_tool("list_chores", {})
        assert "Error" in result[0].text

    @pytest.mark.asyncio
    async def test_http_404_error(self, httpx_mock: HTTPXMock, mock_login):
        httpx_mock.add_response(url=f"{BASE}/api/v1/chores/999", status_code=404)
        result = await call_tool("get_chore", {"chore_id": 999})
        assert "not found" in result[0].text.lower()
