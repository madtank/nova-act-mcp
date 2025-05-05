# nova-act-mcp
[![PyPI](https://img.shields.io/pypi/v/nova-act-mcp-server)](https://pypi.org/project/nova-act-mcp-server/)

**nova‑act‑mcp‑server** is a zero‑install [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that exposes [Amazon Nova Act](https://nova.amazon.com/act) browser‑automation tools.

## What's New in v0.2.8
- **Enhanced Inline Screenshots**: Screenshots now appear directly in the response `content` array
- Improved compatibility with vision-capable models like Claude
- Screenshots include descriptive captions based on the executed instruction
- Each screenshot is delivered as `{ type: "image_base64", data: "..." }` in the content array

## What's New in v0.2.7
- **Automatic Inline Screenshots**: Every browser action now includes an optimized screenshot
- Improved screenshot quality and reliability for AI agents
- Added environment variables to customize screenshot quality and size limits
- Comprehensive test coverage ensuring screenshots work in all scenarios

### New Feature: Inline Screenshots

Every successful `execute` response now contains `inline_screenshot`, a base64-encoded JPEG of the current viewport:
- Quality ≈ 45, hard-capped at 250 KB (configurable via `NOVA_MCP_MAX_INLINE_IMG` env variable)
- If the raw JPEG is larger than the cap, the field is `null`
- No extra API calls needed - screenshots are included automatically
- For full-resolution images and HAR/HTML logs, use the `compress_logs` tool

## What's New in v0.2.6
- Added compatibility with NovaAct SDK 0.9+ by normalizing log directory handling
- Improved test organization with clear markers for unit, mock, smoke and e2e tests
- Moved mock HTML creation logic from production code to test helpers
- Fixed several syntax errors and incomplete code blocks
- Added SCREENSHOT_QUALITY constant for consistent compression settings

## Quick start (uvx)

Add it to your MCP client configuration:

```jsonc
{
  "mcpServers": {
    "nova-act-mcp-server": {
      "command": "uvx",
      "args": ["nova-act-mcp-server@latest"],
      "env": { "NOVA_ACT_API_KEY": "<your_api_key>" }
    }
  }
}
```

That's all you need to start controlling browsers from any MCP‑compatible client such as Claude Desktop or VS Code.

## Local development (optional)

```bash
git clone https://github.com/madtank/nova-act-mcp.git
cd nova-act-mcp
uv sync
uv run nova_mcp.py
```

## License
[MIT](LICENSE)
