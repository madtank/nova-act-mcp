import pytest
import asyncio
import sys
import os

# Add project root to sys.path if necessary
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from nova_mcp_server.tools import start_session, execute_instruction, end_session, list_browser_sessions, inspect_browser
from nova_mcp_server.config import initialize_environment

pytestmark = pytest.mark.skipif(
    "NOVA_ACT_API_KEY" not in os.environ or os.environ.get("CI") == "true",
    reason="Skipping session management tests in CI or when API key is not available"
)

@pytest.mark.asyncio
async def test_start_and_end_single_session():
    initialize_environment()
    start_res = await start_session(url="https://example.com", headless=True)
    assert "error" not in start_res, f"Session start error: {start_res.get('error')}"
    assert "session_id" in start_res
    session_id = start_res["session_id"]
    assert start_res.get("status") == "ready"

    end_res = await end_session(session_id=session_id)
    assert "error" not in end_res, f"Session end error: {end_res.get('error')}"
    assert end_res.get("success") is True # Or check for a specific "ended" status if returned

@pytest.mark.asyncio
async def test_list_sessions_reflects_activity():
    initialize_environment()
    list_before = await list_browser_sessions()
    initial_count = len(list_before.get("sessions", []))

    start_res = await start_session(url="https://example.com", headless=True)
    assert "error" not in start_res, f"Session start failed: {start_res.get('error')}"
    session_id = start_res["session_id"]

    list_during = await list_browser_sessions()
    active_sessions_during = list_during.get("sessions", [])
    assert len(active_sessions_during) == initial_count + 1
    assert any(s["session_id"] == session_id for s in active_sessions_during)

    await end_session(session_id=session_id)

    # Allow a moment for session cleanup if it's asynchronous
    await asyncio.sleep(0.5) 
    list_after = await list_browser_sessions()
    active_sessions_after = list_after.get("sessions", [])
    # Check if session is removed or marked inactive based on actual behavior
    session_after_end = next((s for s in active_sessions_after if s["session_id"] == session_id), None)
    if session_after_end:
        assert session_after_end.get("status") != "ready" # Or specific ended status
    else:
        assert len(active_sessions_after) == initial_count

@pytest.mark.asyncio
async def test_operations_on_invalid_session():
    initialize_environment()
    invalid_sid = "invalid-session-id"
    
    exec_res = await execute_instruction(session_id=invalid_sid, task="test")
    assert "error" in exec_res
    assert exec_res.get("error_code") in ["SESSION_NOT_FOUND", "SESSION_EXECUTOR_NOT_FOUND"]

    inspect_res = await inspect_browser(session_id=invalid_sid)
    assert "error" in inspect_res
    assert inspect_res.get("error_code") in ["SESSION_NOT_FOUND", "SESSION_EXECUTOR_NOT_FOUND"]

    end_res = await end_session(session_id=invalid_sid)
    # Ending a non-existent session might return success (idempotent) or an error
    # For now, let's assume it might error or indicate no action taken.
    # If it returns success, that's fine too as long as it doesn't crash.
    assert isinstance(end_res, dict) # Just ensure it returns something without crashing
