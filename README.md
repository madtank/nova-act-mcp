# nova-act-mcp-server
[![PyPI](https://img.shields.io/pypi/v/nova-act-mcp-server)](https://pypi.org/project/nova-act-mcp-server/)

**nova‑act‑mcp‑server** is a zero‑install [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that exposes [Amazon Nova Act](https://nova.amazon.com/act) browser‑automation tools for AI agents.

## What's New in v3.2.0

- **File-Based Screenshots**: Screenshots now save to files instead of inline base64, eliminating MCP message size limits
- **Optimized Image Quality**: Reduced screenshot quality (60/30) for smaller file sizes (~50KB vs 500KB+)  
- **Enhanced Error Handling**: Improved exception handling for browser operations
- **Better Testing**: Comprehensive test coverage for screenshot functionality
- **MCP Inspector Integration**: New testing script for easy validation

## Quick Start (uvx)

### Step 1: Get a Nova Act API Key
Obtain your API key from [Nova Act](https://nova.amazon.com/act).

### Step 2: Add to MCP Client Configuration

```jsonc
{
  "mcpServers": {
    "nova_act_browser_tools": {
      "command": "uvx",
      "args": ["nova-act-mcp-server"],
      "env": { "NOVA_ACT_API_KEY": "YOUR_NOVA_ACT_API_KEY_HERE" }
    }
  }
}
```

### Step 3: Start Using Browser Tools
AI agents can now call tools like `start_session`, `execute_instruction`, etc. through any MCP-compatible client such as Claude Desktop or VS Code.

## Core Tools Overview

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `start_session` | Starts a new browser session | `url`, `headless=True` |
| `execute_instruction` | Runs a natural language instruction in the browser | `session_id`, `instruction` |
| `inspect_browser` | Gets a screenshot and state of the current browser | `session_id`, `include_screenshot=True` |
| `end_session` | Closes a browser session and cleans up resources | `session_id` |
| `list_browser_sessions` | Lists all active browser sessions | None |

## Local Development & Testing

### Setup

```bash
# Clone the repository
git clone https://github.com/madtank/nova-act-mcp.git
cd nova-act-mcp

# Create and activate virtual environment
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install with development dependencies
uv pip install -e .[dev]
```

### Running Tests

```bash
# Run all tests (integration tests require NOVA_ACT_API_KEY)
pytest

# Run only unit tests (no API key required)
pytest tests/unit

# Run integration tests (requires API key)
NOVA_ACT_API_KEY="your_key_here" pytest tests/integration
```

### Running Locally with MCP Inspector UI

```bash
# Start the server with the MCP Inspector
npx @modelcontextprotocol/inspector -e PYTHONUNBUFFERED=1 -e NOVA_ACT_API_KEY="YOUR_KEY" -- python -m nova_mcp_server
```

Then visit `http://localhost:6274` in your browser. For optimal experience, set the Inspector UI timeout to 60 seconds for `start_session` operations.

## Advanced Tools

| Tool | Description |
|------|-------------|
| `fetch_file` | Downloads a file from the current page |
| `view_html_log` | Gets the HTML content of the current page |
| `compress_logs` | Creates and returns a ZIP of session logs and screenshots |

## License
[MIT](LICENSE)
