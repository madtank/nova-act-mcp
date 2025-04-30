import pytest
import os
import sys
import json
import asyncio

# Add project root to sys.path to allow importing nova_mcp
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

# Attempt to import the real nova_mcp components
try:
    # Import the specific tool functions directly
    from nova_mcp import (
        list_browser_sessions,
        browser_session,
        view_html_log,
        mcp as mcp_instance, # Keep the instance for potential future use or context
        initialize_environment, # Import initialize_environment
        NOVA_ACT_AVAILABLE, # Check availability
        get_nova_act_api_key # Check API key
    )
    REAL_MCP_LOADED = True
except ImportError as e:
    print(f"Failed to import real nova_mcp components for integration tests: {e}")
    REAL_MCP_LOADED = False
    # Define dummy functions/variables if import fails to allow collection
    async def list_browser_sessions(): return {}
    async def browser_session(**kwargs): return {}
    async def view_html_log(**kwargs): return {}
    class MockMCP:
        pass
    mcp_instance = MockMCP()
    def initialize_environment(): pass
    NOVA_ACT_AVAILABLE = False
    def get_nova_act_api_key(): return None

# Helper to convert result to dict (handles JSON strings or dicts)
def _as_dict(result):
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            pytest.fail(f"Expected JSON string result, but got: {result}")
    elif isinstance(result, dict):
        return result # Already a dict
    else:
        pytest.fail(f"Unexpected result type: {type(result)}. Expected dict or JSON string.")

# Integration tests (require NOVA_ACT_API_KEY and nova-act installed)
# Use environment variable for API Key
API_KEY = os.environ.get("NOVA_ACT_API_KEY")

# Skip condition
skip_reason = "NOVA_ACT_API_KEY environment variable not set or nova-act not installed or MCP components failed to load"
skip_integration_tests = not API_KEY or not NOVA_ACT_AVAILABLE or not REAL_MCP_LOADED

@pytest.mark.skipif(skip_integration_tests, reason=skip_reason)
@pytest.mark.asyncio
async def test_nova_act_workflow():
    """Tests a basic workflow: start, execute instruction, view log, end."""
    # Ensure environment is initialized before running tests
    # This might be redundant if tools call it, but safe to ensure
    initialize_environment()

    # 1. List sessions (should be empty initially)
    print("\nTesting: list_browser_sessions (initial)")
    list_result_dict = _as_dict(await list_browser_sessions())
    assert "sessions" in list_result_dict, f"'sessions' key missing in list result: {list_result_dict}"
    initial_count = list_result_dict.get("total_count", 0)
    print(f"Initial session count: {initial_count}")

    # 2. Start a new session
    print("\nTesting: control_browser (start)")
    start_params = {"action": "start", "url": "https://example.com", "headless": True}
    start_result_dict = _as_dict(await browser_session(**start_params))
    assert "session_id" in start_result_dict, f"'session_id' missing in start result: {start_result_dict}"
    assert start_result_dict.get("status") == "ready", f"Unexpected status in start result: {start_result_dict}"
    assert start_result_dict.get("success") is True, f"Start action did not report success: {start_result_dict}"
    session_id = start_result_dict["session_id"]
    print(f"Started session: {session_id}")

    # Give browser time to fully load if needed (though start should handle basic load)
    await asyncio.sleep(2)

    # 3. Execute an instruction
    print("\nTesting: control_browser (execute)")
    execute_params = {
        "action": "execute",
        "session_id": session_id,
        "instruction": "Click the link 'More information...'",
    }
    execute_result_dict = _as_dict(await browser_session(**execute_params))
    assert execute_result_dict.get("session_id") == session_id, f"Session ID mismatch in execute result: {execute_result_dict}"
    assert execute_result_dict.get("success") is True, f"Execute action did not report success: {execute_result_dict}"
    assert "content" in execute_result_dict, f"'content' missing in execute result: {execute_result_dict}"
    # Check if agent thinking was extracted (optional, might be empty)
    assert "agent_thinking" in execute_result_dict, f"'agent_thinking' missing in execute result: {execute_result_dict}"
    print(f"Execution result content snippet: {str(execute_result_dict.get('content'))[:100]}...")
    print(f"Agent thinking extracted: {len(execute_result_dict.get('agent_thinking', []))} items")

    # Wait for potential navigation/action to complete
    await asyncio.sleep(3)

    # 4. View the HTML log for the session
    print("\nTesting: view_html_log")
    view_params = {"session_id": session_id}
    # view_html_log returns a dict with 'content' or 'error'
    log_result = await view_html_log(**view_params)
    assert "error" not in log_result, f"view_html_log returned an error: {log_result.get('error')}"
    assert "content" in log_result, f"'content' missing in view_html_log result: {log_result}"
    assert isinstance(log_result["content"], list), f"Expected list content in view_html_log result: {log_result}"
    assert len(log_result["content"]) > 0, "view_html_log content list is empty"
    assert log_result["content"][0].get("type") == "html", f"Expected html type in view_html_log content: {log_result}"
    assert len(log_result["content"][0].get("html", "")) > 100, "HTML log content seems too short"
    print(f"HTML log retrieved successfully (length: {len(log_result['content'][0].get('html', ''))})")

    # 5. End the session
    print("\nTesting: control_browser (end)")
    end_params = {"action": "end", "session_id": session_id}
    end_result_dict = _as_dict(await browser_session(**end_params))
    assert end_result_dict.get("session_id") == session_id, f"Session ID mismatch in end result: {end_result_dict}"
    assert end_result_dict.get("status") == "ended", f"End action did not report ended status: {end_result_dict}"
    assert end_result_dict.get("success") is True, f"End action did not report success: {end_result_dict}"
    print(f"Session ended: {session_id}")

    # 6. List sessions again (should potentially show the ended session or be cleaned up)
    print("\nTesting: list_browser_sessions (final)")
    final_list_result_dict = _as_dict(await list_browser_sessions())
    assert "sessions" in final_list_result_dict, f"'sessions' key missing in final list result: {final_list_result_dict}"
    # The ended session might still be listed briefly or cleaned up, so check count >= initial
    final_count = final_list_result_dict.get("total_count", 0)
    assert final_count >= initial_count, f"Final session count ({final_count}) decreased unexpectedly from initial ({initial_count})"
    print(f"Final session count: {final_count}")

    # Optional: Check if the specific session is marked as ended or removed
    session_found_after_end = any(s['session_id'] == session_id for s in final_list_result_dict.get("sessions", []))
    if session_found_after_end:
        ended_session_status = next((s['status'] for s in final_list_result_dict["sessions"] if s['session_id'] == session_id), None)
        assert ended_session_status in ["ended", "complete"], f"Session {session_id} found after end, but status is not 'ended' or 'complete': {ended_session_status}"
        print(f"Session {session_id} found with status: {ended_session_status}")
    else:
        print(f"Session {session_id} was cleaned up after ending.")
