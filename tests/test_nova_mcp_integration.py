import sys
import os
import pytest
import json
import asyncio
from unittest.mock import MagicMock

# Helper to unwrap FastMCP TextContent or pass-through
def _as_dict(obj):
    """
    Unwrap any FastMCP TextContent payload (possibly nested inside a one‑element
    list) into a Python dict, or transparently return the original object when
    we cannot deserialize it.

    FastMCP call_tool() often returns:
        [TextContent(type='text', text='{"foo": 1}')]
    This helper makes the tests agnostic to that transport detail.
    """
    # Handle the common `[TextContent(...)]` wrapper
    if isinstance(obj, list) and len(obj) == 1:
        obj = obj[0]

    # Native dict – we're done
    if isinstance(obj, dict):
        return obj

    # FastMCP TextContent artifact
    if hasattr(obj, "text"):
        payload = obj.text
    elif isinstance(obj, str):
        payload = obj
    else:
        return obj  # Unknown type – give up

    # Try to parse JSON text -> dict
    try:
        return json.loads(payload)
    except Exception:
        return payload

# Add project root to path if necessary
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- Integration Test Setup ---
try:
    import nova_mcp
    print("[Integration Test Setup] Imported nova_mcp.")

    mcp_instance = nova_mcp.mcp
    NOVA_ACT_AVAILABLE = nova_mcp.NOVA_ACT_AVAILABLE

    # Restore environment variable check
    print(f"[Integration Test Setup] Checking environment variable NOVA_ACT_API_KEY...")
    API_KEY = os.environ.get("NOVA_ACT_API_KEY") # Restored check
    print(f"[Integration Test Setup] Value of API_KEY: '{API_KEY}'")
    print(f"[Integration Test Setup] Value of NOVA_ACT_AVAILABLE: {NOVA_ACT_AVAILABLE}")

    # This is no longer used by skipif, but keep for potential future use
    INTEGRATION_TEST_POSSIBLE = API_KEY and NOVA_ACT_AVAILABLE
    REASON_SKIP_INTEGRATION = ""
    if not API_KEY:
        REASON_SKIP_INTEGRATION += "NOVA_ACT_API_KEY environment variable not set. "
    if not NOVA_ACT_AVAILABLE:
        REASON_SKIP_INTEGRATION += "Nova Act SDK not available (pip install nova-act). "
    if not hasattr(mcp_instance, 'call_tool'):
         mcp_type = type(mcp_instance).__name__
         raise ImportError(f"The real mcp instance (type: {mcp_type}) does not have a 'call_tool' method.")
    print(f"[Integration Test Setup] INTEGRATION_TEST_POSSIBLE: {INTEGRATION_TEST_POSSIBLE}")
    print(f"[Integration Test Setup] REASON_SKIP_INTEGRATION: '{REASON_SKIP_INTEGRATION}'")
    print("[Integration Test Setup] Setup successful.")
except (ImportError, AttributeError, KeyError, TypeError) as e:
    print(f"Failed to import or access real nova_mcp components/tools for integration tests: {e}", file=sys.stderr)
    INTEGRATION_TEST_POSSIBLE = False
    REASON_SKIP_INTEGRATION = f"Failed to import/access nova_mcp components/tools: {e}"
    mcp_instance = MagicMock()
    async def dummy_call_tool(*args, **kwargs): return "{}"
    mcp_instance.call_tool = dummy_call_tool

# --- Integration Test ---
@pytest.mark.asyncio
async def test_nova_act_workflow():

    # Ensure runtime check is present at the beginning of the test function
    api_key_runtime = os.environ.get("NOVA_ACT_API_KEY")
    if not api_key_runtime or not NOVA_ACT_AVAILABLE:
        reason = ""
        if not api_key_runtime:
            reason += "NOVA_ACT_API_KEY environment variable not set at runtime. "
        if not NOVA_ACT_AVAILABLE:
            reason += "Nova Act SDK not available. "
        pytest.skip(reason.strip())

    # --- Original test code starts here ---
    session_id = None
    print("\n[Integration Test] Starting Nova Act workflow test...")
    final_json = {
        "sessionVerified": False,
        "htmlLogEmbedded": False,
        "errors": [],
        "agentThinkingExtracted": []
    }
    try:
        print("[Test Step 1] Listing initial sessions...")
        list_result_raw = await mcp_instance.call_tool("list_browser_sessions", {})
        list_result = _as_dict(list_result_raw)
        # print(f"Initial sessions: {json.dumps(_as_dict(list_result_raw), indent=2)}")
        print(f"Initial sessions dict: {list_result}")
        assert isinstance(list_result, dict) and "sessions" in list_result, \
            "list_browser_sessions should return a dict with 'sessions' key"
        print("[Test Step 2] Starting browser session to https://example.com...")
        start_params = {"action": "start", "url": "https://example.com", "headless": True}
        start_result_raw = await mcp_instance.call_tool("control_browser", start_params)
        start_result = _as_dict(start_result_raw)
        # print(f"Start result: {json.dumps(_as_dict(start_result_raw), indent=2)}")
        print(f"Start result dict: {start_result}")
        assert "session_id" in start_result, "Start action should return a session_id"
        session_id = start_result["session_id"]
        assert session_id, "session_id should not be empty"
        assert start_result.get("success") is True, f"Start action failed: {start_result.get('error')}"
        print(f"Session started successfully: {session_id}")
        await asyncio.sleep(3)
        print(f"[Test Step 3] Executing instruction on session {session_id}...")
        instruction = "click the element 'a[href^=\"https://www.iana.org/domains/example\"]'"
        execute_params = {
            "action": "execute",
            "session_id": session_id,
            "instruction": instruction
        }
        execute_result_raw = await mcp_instance.call_tool("control_browser", execute_params)
        execute_result = _as_dict(execute_result_raw)
        # Ensure execute_result is a dict
        if not isinstance(execute_result, dict):
            execute_result = {}
        # print(f"Execute result: {json.dumps(_as_dict(execute_result_raw), indent=2)}")
        print(f"Execute result dict: {execute_result}")
        assert execute_result.get("session_id") == session_id, "Execute result session_id mismatch"
        final_json["sessionVerified"] = execute_result.get("success", False)
        if not final_json["sessionVerified"]:
            error_message = execute_result.get('error', 'Unknown execution error')
            final_json["errors"].append(error_message)
            pytest.fail(f"Execute action failed: {error_message}")
        agent_thinking = execute_result.get("agent_thinking", [])
        final_json["agentThinkingExtracted"] = agent_thinking
        print(f"Agent thinking extracted: {json.dumps(agent_thinking, indent=2)}")
        assert isinstance(agent_thinking, list), "Agent thinking should be a list"
        print("Execute action successful.")
        print(f"[Test Step 4] Viewing HTML log for session {session_id}...")
        log_params = {"session_id": session_id}
        log_result_raw = await mcp_instance.call_tool("view_html_log", log_params)
        log_result = _as_dict(log_result_raw)
        html_str = log_result["content"][0]["html"]
        print(f"HTML Log result (first 500 chars): {html_str[:500]}...")
        assert html_str, "view_html_log should return content"
        assert isinstance(html_str, str)
        is_html = "<!DOCTYPE html>" in html_str or "<html" in html_str.lower()
        has_title = "Nova-Act Log" in html_str
        has_action = "Action: execute" in html_str
        has_instruction = "click the element" in html_str
        final_json["htmlLogEmbedded"] = is_html and has_title and has_action and has_instruction
        assert final_json["htmlLogEmbedded"], "HTML log content is missing expected elements (DOCTYPE/html, Title, Action, Instruction)"
        print("HTML log retrieved and verified.")
    except Exception as e:
        error_info = f"Unexpected error during test: {type(e).__name__}: {e}"
        print(error_info, file=sys.stderr)
        final_json["errors"].append(error_info)
        pytest.fail(error_info)
    finally:
        if session_id:
            print(f"[Test Step 5] Ending session {session_id}...")
            end_params = {"action": "end", "session_id": session_id}
            try:
                end_result_raw = await mcp_instance.call_tool("control_browser", end_params)
                end_result = _as_dict(end_result_raw)
                # print(f"End result: {json.dumps(_as_dict(end_result_raw), indent=2)}")
                print(f"End result dict: {end_result}")
                assert end_result.get("session_id") == session_id, "End result session_id mismatch"
                assert end_result.get("success") is True, f"End action failed: {end_result.get('error')}"
                print(f"Session {session_id} ended successfully.")
            except Exception as e:
                error_info = f"Error during session end cleanup: {type(e).__name__}: {e}"
                print(error_info, file=sys.stderr)
                if not final_json["errors"]:
                    final_json["errors"].append(error_info)
        print("\n[Integration Test] Final JSON structure:")
        print(json.dumps(final_json, indent=2))
        assert final_json["sessionVerified"] is True, "Session verification failed (execute step)"
        assert final_json["htmlLogEmbedded"] is True, "HTML log verification failed"
        assert len(final_json["errors"]) == 0, f"Test completed with errors: {final_json['errors']}"

if __name__ == "__main__":
    pytest.main(["-v", "-s", __file__])
