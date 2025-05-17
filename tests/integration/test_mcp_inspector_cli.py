import pytest
import asyncio
import json
import os
import sys
import uuid  # For request IDs
import subprocess
import time

# Add project root to sys.path if necessary
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from nova_mcp_server.config import initialize_environment  # For consistency, though not strictly needed by CLI test itself

# Global variables to track server process state
_server_process = None
_server_started = False

# Define pytest markers for skipping tests and setting asyncio options
pytestmark = [
    pytest.mark.skipif(
        "NOVA_ACT_API_KEY" not in os.environ or os.environ.get("CI") == "true",
        reason="Skipping MCP direct interaction tests in CI or when API key is not available"
    ),
    pytest.mark.asyncio(loop_scope="module") # Use module-scoped event loop
]

# Helper function to run MCP Inspector CLI commands
async def run_inspector_command(inspector_method_args):
    """Run the MCP Inspector CLI with the given method arguments.
    
    This uses npx to run the @modelcontextprotocol/inspector CLI tool, which:
    1. Starts a server process (python -m nova_mcp_server)
    2. Sends the request to the server
    3. Returns the response
    4. Shuts down the server
    
    Each call is independent and doesn't share state with other calls.
    """
    api_key = os.environ.get("NOVA_ACT_API_KEY")
    if not api_key:
        pytest.skip("NOVA_ACT_API_KEY not found in environment for CLI test.")

    # Construct the command carefully
    # Base command for the inspector and passing the API key
    cmd_prefix = f"npx @modelcontextprotocol/inspector --cli -e NOVA_ACT_API_KEY='{api_key}' -e PYTHONUNBUFFERED=1"
    
    # Use a server command that will work reliably
    server_cmd = "-- python -m nova_mcp_server"
    
    # For create_subprocess_shell, we pass a single command string
    cmd_str = f"{cmd_prefix} {server_cmd} {' '.join(inspector_method_args)}"

    print(f"Executing MCP Inspector CLI: {cmd_str}")

    process = await asyncio.create_subprocess_shell(
        cmd_str,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        print(f"MCP Inspector CLI Error (stderr): {stderr.decode().strip()}")
        pytest.fail(f"MCP Inspector CLI command failed with exit code {process.returncode}. stderr: {stderr.decode().strip()}")

    stdout_str = stdout.decode().strip()
    
    # Check if the output is proper JSON
    try:
        return json.loads(stdout_str)
    except json.JSONDecodeError as e:
        print(f"MCP Inspector CLI Output (stdout): {stdout_str}")
        pytest.fail(f"Failed to decode JSON from MCP Inspector CLI output: {e}. Output was: {stdout_str}")

@pytest.mark.asyncio
async def test_mcp_cli_list_tools():
    """Test listing MCP tools via CLI tool"""
    initialize_environment()  # Ensures .env is loaded if pytest-dotenv didn't catch it
    
    method_args = ['--method', 'tools/list']
    
    response = await run_inspector_command(method_args)
    
    assert isinstance(response.get("tools"), list), "Response should have a 'tools' list"
    tool_names = [tool.get("name") for tool in response["tools"]]
    
    assert "start_session" in tool_names
    assert "execute_instruction" in tool_names
    assert "end_session" in tool_names
    assert "inspect_browser" in tool_names
    assert "list_browser_sessions" in tool_names
    print("MCP CLI tools/list verification PASSED")

@pytest.fixture(scope="module")
async def mcp_server_process(): # No event_loop parameter
    global _server_process, _server_started
    
    if _server_started and _server_process and _server_process.returncode is None:
        print("Reusing existing MCP server process for tests.")
        yield _server_process
        return

    # Get the currently running event loop (should be module-scoped due to pytestmark)
    loop = asyncio.get_running_loop()

    api_key = os.environ.get("NOVA_ACT_API_KEY")
    if not api_key:
        pytest.skip("NOVA_ACT_API_KEY not found for mcp_server_process fixture.")

    cmd = [sys.executable, "-m", "nova_mcp_server"]
    env = os.environ.copy()
    env["NOVA_ACT_API_KEY"] = api_key
    env["PYTHONUNBUFFERED"] = "1"  # Ensure Python output is unbuffered
    # env["NOVA_MCP_DEBUG"] = "1" # Uncomment for verbose server logs

    print(f"Starting MCP server for tests: {' '.join(cmd)}")
    # Explicitly use the module-scoped event loop
    _server_process = await loop.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env
    )
    _server_started = True # Mark as started attempt

    # Give server a moment to start and potentially print initial errors
    await loop.create_task(asyncio.sleep(2.0)) # Use the loop explicitly

    # Check if the process terminated very quickly (sign of immediate crash)
    if _server_process.returncode is not None:
        stderr_output = "MCP Server process exited prematurely.\n"
        if _server_process.stderr:
            try:
                # Try to read any stderr quickly
                stderr_data = await loop.create_task(asyncio.wait_for(_server_process.stderr.read(2048), timeout=0.5))
                stderr_output += f"Stderr: {stderr_data.decode(errors='ignore')}"
            except asyncio.TimeoutError:
                stderr_output += "Stderr: (timed out reading stderr)"
            except Exception as e:
                stderr_output += f"Stderr: (error reading stderr: {e})"
        _server_started = False # Mark as failed to start properly
        pytest.fail(f"MCP Server failed to stay running. Exit code: {_server_process.returncode}. {stderr_output}")
    
    print("MCP server process appears to have started.")
    yield _server_process

    # Teardown
    print("Teardown: Terminating MCP server process...")
    if _server_process and _server_process.returncode is None:
        _server_process.terminate()
        try:
            await loop.create_task(asyncio.wait_for(_server_process.wait(), timeout=5.0))
            print("MCP Server process terminated.")
        except asyncio.TimeoutError:
            print("MCP Server process did not terminate gracefully, killing.")
            _server_process.kill()
            await loop.create_task(_server_process.wait()) # Ensure kill completes
            print("MCP Server process killed.")
    elif _server_process:
        print(f"MCP Server process already exited with code {_server_process.returncode}.")
    
    _server_process = None
    _server_started = False

async def send_mcp_request(process: asyncio.subprocess.Process, method: str, params: dict = None, req_id=None, timeout_seconds=20): # Increased timeout
    if req_id is None:
        req_id = str(uuid.uuid4())
    
    request_json = {
        "jsonrpc": "2.0",
        "method": method,
        "id": req_id
    }
    if params is not None:
        request_json["params"] = params

    request_str = json.dumps(request_json) + "\n"
    print(f"Sending to server stdin: {request_str.strip()}")
    
    if process.stdin.is_closing(): # Check if stdin is writable
        pytest.fail("Server stdin is closed. Cannot send request.")
        
    process.stdin.write(request_str.encode())
    await process.stdin.drain()

    start_time = time.monotonic()
    buffer = "" # For accumulating stdout lines for debugging
    processed_stderr_lines = [] # To avoid printing same stderr repeatedly

    while True:
        current_time = time.monotonic()
        if current_time - start_time > timeout_seconds:
            # Try to get recent stderr output for better diagnostics on timeout
            error_context = ""
            if process.stderr and not process.stderr.at_eof():
                try:
                    err_line_bytes = await asyncio.wait_for(process.stderr.readline(), timeout=0.1)
                    if err_line_bytes:
                        error_context = f" Last stderr line: {err_line_bytes.decode(errors='ignore').strip()}"
                except asyncio.TimeoutError:
                    pass # No immediate stderr
                except Exception as e_stderr:
                    error_context = f" (Error reading stderr: {e_stderr})"

            pytest.fail(f"Timeout ({timeout_seconds}s) waiting for response to request ID {req_id} for method {method}. "
                        f"Buffered stdout: '{buffer.strip()}'.{error_context}")

        try:
            line_bytes = await asyncio.wait_for(process.stdout.readline(), timeout=0.1)
        except asyncio.TimeoutError:
            # No data on stdout, check for stderr activity or if process exited
            if process.returncode is not None:
                 pytest.fail(f"Server process exited prematurely with code {process.returncode} while waiting for req ID {req_id}.")
            if process.stderr and not process.stderr.at_eof():
                try:
                    err_line_bytes = await asyncio.wait_for(process.stderr.readline(), timeout=0.05)
                    if err_line_bytes:
                        decoded_err_line = err_line_bytes.decode(errors='ignore').strip()
                        if decoded_err_line not in processed_stderr_lines: # Avoid spamming same error
                            print(f"Server stderr: {decoded_err_line}")
                            processed_stderr_lines.append(decoded_err_line)
                            if len(processed_stderr_lines) > 20: # Limit stored stderr lines
                                processed_stderr_lines.pop(0)
                except asyncio.TimeoutError:
                    pass # No stderr this tick
            continue # Go back to check overall timeout / read again

        if not line_bytes: 
            await asyncio.sleep(0.05) # Brief pause if pipe seems closed but process is alive
            if process.returncode is not None: # Check again if process died
                 pytest.fail(f"Server process stdout EOF and process exited (code {process.returncode}) while waiting for req ID {req_id}. Buffered: '{buffer.strip()}'")
            if time.monotonic() - start_time > timeout_seconds / 2 and not buffer: # If half timeout passed with no data
                 print(f"Warning: Half timeout passed for req ID {req_id} with no stdout data. Server might be unresponsive.")
            continue


        line_str = line_bytes.decode(errors='ignore').strip()
        if line_str: # Only process non-empty lines
            buffer += line_str + "\n" 
            print(f"Received from server stdout line: {line_str}")

            try:
                response_json = json.loads(line_str)
                if response_json.get("id") == req_id:
                    print(f"Found matching JSON-RPC response for ID {req_id}")
                    if "error" in response_json:
                        print(f"MCP Server returned an error in targeted response: {response_json['error']}")
                        # Optionally, fail test if error in response:
                        # pytest.fail(f"MCP method {method} failed with error: {response_json['error']}")
                    return response_json.get("result") 
                elif response_json.get("id") is not None: # JSON with a different ID
                    print(f"Received JSON response for a different request ID ({response_json.get('id')}), expecting {req_id}. Ignoring.")
                elif "jsonrpc" in response_json and "method" in response_json: # Is a notification
                    print(f"Received JSON-RPC Notification (not a response): {line_str}")
                else: # Other JSON
                    print(f"Received other JSON data: {line_str}")
            except json.JSONDecodeError:
                print(f"Skipping non-JSON line from server: {line_str}")
        # If line was empty, just loop again

@pytest.mark.skip(reason="Persistent ScopeMismatch with module-scoped async fixture, investigating separately")
@pytest.mark.asyncio
async def test_mcp_direct_list_tools(mcp_server_process):
    """Test listing tools by communicating directly with the MCP server."""
    initialize_environment() 
    
    result = await send_mcp_request(mcp_server_process, "tools/list")
    
    assert isinstance(result, list), "tools/list result should be a list"
    tool_names = [tool.get("name") for tool in result]
    
    assert "browser_session" in tool_names
    assert "inspect_browser" in tool_names
    assert "list_browser_sessions" in tool_names
    print("MCP direct tools/list verification PASSED")

@pytest.mark.skip(reason="Persistent ScopeMismatch with module-scoped async fixture, investigating separately")
@pytest.mark.asyncio
async def test_mcp_direct_session_lifecycle(mcp_server_process):
    """Test the browser session lifecycle (start → inspect → end) through direct MCP server communication."""
    initialize_environment()
    session_id = None

    try:
        # 1. Start session
        print("--- MCP direct: Starting session ---")
        start_params = {
            "tool_name": "browser_session", 
            "tool_args": {
                "action": "start",
                "url": "https://example.com",
                "headless": True,
                "kwargs": {}  # Empty kwargs needed for validation
            }
        }
        start_result = await send_mcp_request(mcp_server_process, "tools/call", start_params)
        
        assert start_result is not None, "Start session did not return a result"
        assert "error" not in start_result, f"Start session returned error: {start_result.get('error')}"
        session_id = start_result.get("session_id")
        assert session_id, f"session_id missing from start response: {start_result}"
        assert start_result.get("status") == "ready", f"Start status not ready: {start_result}"
        print(f"MCP direct browser_session start OK, session_id: {session_id}")

        # Add a small delay to ensure the browser session is fully initialized
        await asyncio.sleep(2)

        # 2. Inspect session
        print(f"--- MCP direct: Inspecting session {session_id} ---")
        inspect_params = {
            "tool_name": "inspect_browser", 
            "tool_args": {
                "session_id": session_id
            }
        }
        inspect_result = await send_mcp_request(mcp_server_process, "tools/call", inspect_params)

        assert inspect_result is not None, "Inspect session did not return a result"
        assert inspect_result.get("success") is True, f"Inspect success not True: {inspect_result}"
        assert inspect_result.get("current_url") == "https://example.com/", f"Inspect URL mismatch: {inspect_result}"
        assert "Example Domain" in inspect_result.get("page_title", ""), f"Inspect title mismatch: {inspect_result}"
        
        content = inspect_result.get("content", [])
        img_content = next((c for c in content if c.get("type") == "image_base64"), None)
        assert img_content is not None, "image_base64 missing from inspect_browser result"
        print("MCP direct inspect_browser OK")

    finally:
        if session_id:
            # 3. End session
            print(f"--- MCP direct: Ending session {session_id} ---")
            end_params = {
                "tool_name": "browser_session",
                "tool_args": {
                    "action": "end",
                    "session_id": session_id,
                    "kwargs": {}  # Empty kwargs needed for validation
                }
            }
            end_result = await send_mcp_request(mcp_server_process, "tools/call", end_params)
            assert end_result is not None, "End session did not return a result"
            assert end_result.get("success") is True, f"End session not successful: {end_result}"
            print("MCP direct browser_session end OK")