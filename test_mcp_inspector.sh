#!/bin/bash
# Script to test the MCP server with MCP Inspector

echo "Testing Nova Act MCP Server with MCP Inspector"
echo "============================================="
echo ""
echo "This will launch the MCP Inspector UI in your browser."
echo "You can interactively test all MCP tools and see responses."
echo ""

# Check if API key is set
if [ -z "$NOVA_ACT_API_KEY" ]; then
    echo "ERROR: NOVA_ACT_API_KEY environment variable is not set"
    echo "Please set it first: export NOVA_ACT_API_KEY='your-key-here'"
    exit 1
fi

# Run MCP Inspector
echo "Starting MCP Inspector..."
npx @modelcontextprotocol/inspector \
    -e PYTHONUNBUFFERED=1 \
    -e NOVA_ACT_API_KEY="$NOVA_ACT_API_KEY" \
    -e NOVA_MCP_DEBUG=1 \
    -- python -m nova_mcp_server

# Note: The inspector will open in your default browser
# You can then:
# 1. See all available tools
# 2. Test start_session, inspect_browser, fetch_file, etc.
# 3. Verify screenshot file saving behavior