# Nova Act MCP Testing

This directory contains testing resources and tools for the Nova Act MCP server.

## Directory Structure

- `headless_mode/`: Tests for the headless browser mode functionality
  - `NOVA_ACT_MCP_TESTING.md`: Testing guide for headless mode
  - `headless_form_test.html`: Sample form for testing headless browser mode
  - `headless_toggle_test.html`: Multi-step form for testing headless toggle
  - `test_headless_toggle.sh`: Shell script for testing headless toggle

- `proxy_agent/`: Proxy agent tools for automated testing
  - `mcp_client.py`: Python client for interacting with the MCP server
  - `run_tests.sh`: Shell script for running proxy-based tests

- `legacy/`: Older test materials (archived)

## Running Tests

### Manual Testing

For manual testing of the headless mode functionality:

1. Start the MCP server with the appropriate API key:
   ```
   NOVA_ACT_API_KEY="your_key" uv run nova_mcp.py
   ```

2. Follow the testing guide in `headless_mode/NOVA_ACT_MCP_TESTING.md`

### Automated Testing with Proxy Agent

For automated testing using the proxy agent:

1. Start the MCP server as above
2. Run the Python client:
   ```
   python testing/proxy_agent/mcp_client.py
   ```

3. Or use the shell script:
   ```
   ./testing/proxy_agent/run_tests.sh
   ```

## Key Features Tested

1. **Headless Mode by Default**: Browsers start invisible for efficiency
2. **Toggle Headless**: Change between headless and visible modes
3. **Session State Tracking**: Properly track browser session state
4. **Performance**: Operate without visible UI disruption