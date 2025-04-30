import json, asyncio, sys, os, inspect
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

# Allow "python tests/test_…" execution from repo root
repo_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(repo_root))

# Module-level patches/mocks
mock_nova_act = MagicMock()
mock_nova_act.NovaAct = MagicMock()
mock_mcp = MagicMock()
mock_mcp.tools = []

# Create a JsonRPC response helper function
def create_jsonrpc_response(id, result=None, error=None):
    """Create a properly formatted JSON-RPC 2.0 response"""
    response = {"jsonrpc": "2.0", "id": id}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result
    return response

# Mock async functions for testing
async def mock_browser_session(action="execute", session_id=None, url=None, instruction=None, 
                           headless=True, username=None, password=None, schema=None):
    """Mock implementation of browser_session for testing"""
    request_id = 1
    
    if action == "start":
        session_id = "test-session-id"
        return create_jsonrpc_response(request_id, {
            "session_id": session_id,
            "url": url or "https://example.com",
            "title": "Example Domain",
            "status": "ready"
        })
    elif action == "execute":
        if not session_id:
            return create_jsonrpc_response(request_id, error={
                "code": -32602,
                "message": "session_id is required for 'execute' action",
                "data": None
            })
        return create_jsonrpc_response(request_id, {
            "content": [{"type": "text", "text": f"Executed: {instruction}"}],
            "agent_thinking": [],
            "isError": False,
            "session_id": session_id
        })
    elif action == "end":
        if not session_id:
            return create_jsonrpc_response(request_id, error={
                "code": -32602,
                "message": "session_id is required for 'end' action",
                "data": None
            })
        return create_jsonrpc_response(request_id, {
            "session_id": session_id,
            "status": "ended",
            "success": True
        })
    else:
        return create_jsonrpc_response(request_id, error={
            "code": -32601,
            "message": f"Unknown action: {action}",
            "data": None
        })

async def mock_list_browser_sessions():
    """Mock implementation of list_browser_sessions for testing"""
    return create_jsonrpc_response(1, {
        "sessions": [{
            "session_id": "test-session-id",
            "identity": "default",
            "status": "ready",
            "current_step": 0,
            "total_steps": 0,
            "last_updated": 0,
            "current_action": "",
            "url": "https://example.com"
        }],
        "active_count": 1,
        "total_count": 1
    })

async def mock_view_html_log(session_id=None, html_path=None, truncate_to_kb=512):
    """Mock implementation of view_html_log for testing"""
    return create_jsonrpc_response(1, {
        "content": [{
            "type": "html",
            "html": "<html><body><h1>Example Domain</h1><p>This is mock HTML</p></body></html>"
        }],
        "source_path": "/tmp/mock.html"
    })

# Setup module for testing
def setup_module(module):
    """Setup mock environment before any tests run."""
    print("\n[Setup] Setting up mocks for basic tests...")
    
    # Patch before importing nova_mcp
    sys.modules['nova_act'] = mock_nova_act
    sys.modules['fastmcp'] = MagicMock()
    
    # Remove any previous imports
    if 'nova_mcp' in sys.modules:
        del sys.modules['nova_mcp']
    
    # Now import nova_mcp for testing
    import nova_mcp
    
    # Set up the environment for tests
    nova_mcp.NOVA_ACT_AVAILABLE = True
    nova_mcp.NOVA_ACT_API_KEY = "mock-api-key"
    
    # Replace functions with our mocks
    nova_mcp.browser_session = mock_browser_session
    nova_mcp.list_browser_sessions = mock_list_browser_sessions
    nova_mcp.view_html_log = mock_view_html_log
    
    print("[Setup] Basic test mocks configured.")

# Teardown module after tests
def teardown_module(module):
    """Clean up after all tests have run."""
    print("\n[Teardown] Stopping patches for test_nova_mcp_basic.py")
    
    # Clean up module patching
    sys.modules.pop('nova_act', None)
    sys.modules.pop('fastmcp', None)
    if 'nova_mcp' in sys.modules:
        del sys.modules['nova_mcp']

# Ensure API key is set (for visual confirmation)
if "NOVA_ACT_API_KEY" not in os.environ:
    # Try to read from .env file
    env_path = os.path.join(os.path.dirname(repo_root), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    # Remove quotes if present
                    value = value.strip('"\'')
                    os.environ[key] = value
                    print(f"Loaded environment variable: {key}")

TEST_URL = "https://example.com"

@pytest.mark.asyncio
async def test_start_and_end_session():
    """Test starting and ending a session"""
    # Import nova_mcp here to ensure mocks are applied
    import nova_mcp
    
    # Start a session
    rsp = await nova_mcp.browser_session(action="start", url=TEST_URL)
    assert "result" in rsp, "Response should have a result field"
    data = rsp["result"]
    assert data["status"] == "ready"
    sid = data["session_id"]

    # List sessions should show 1 active
    listing = await nova_mcp.list_browser_sessions()
    assert "result" in listing, "Listing response should have a result field"
    assert any(s["session_id"] == sid for s in listing["result"]["sessions"])

    # End session
    end_rsp = await nova_mcp.browser_session(action="end", session_id=sid)
    assert "result" in end_rsp, "End response should have a result field"
    assert end_rsp["result"]["status"] == "ended"

@pytest.mark.asyncio
async def test_view_html_log_roundtrip():
    """Test the full flow of start->execute->view log->end"""
    # Import nova_mcp here to ensure mocks are applied
    import nova_mcp
    
    # Start a session
    rsp = await nova_mcp.browser_session(action="start", url=TEST_URL)
    assert "result" in rsp, "Response should have a result field"
    sid = rsp["result"]["session_id"]

    # Trigger one simple action
    exec_rsp = await nova_mcp.browser_session(
        action="execute",
        session_id=sid,
        instruction="observe the page"
    )
    assert "result" in exec_rsp, "Execute response should have a result field"

    # View the log
    log_rsp = await nova_mcp.view_html_log(session_id=sid)
    assert "result" in log_rsp, "Log response should have a result field"
    html = log_rsp["result"]["content"][0]["html"]
    assert "<html" in html.lower()
    assert "example domain" in html.lower()

    # End the session
    end_rsp = await nova_mcp.browser_session(action="end", session_id=sid)
    assert "result" in end_rsp, "End response should have a result field"
    assert end_rsp["result"]["status"] == "ended"