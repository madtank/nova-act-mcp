
# nova-act-mcp
[![PyPI](https://img.shields.io/pypi/v/nova-act-mcp-server)](https://pypi.org/project/nova-act-mcp-server/)

**nova‑act‑mcp‑server** is a zero‑install [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that exposes [Amazon Nova Act](https://nova.amazon.com/act) browser‑automation tools.

## Quick start (uvx)

```bash
# Run the server in an isolated environment – no cloning or virtual‑env needed
uvx nova-act-mcp-server@latest --version
```

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

That’s all you need to start controlling browsers from any MCP‑compatible client such as Claude Desktop or VS Code.

## Local development (optional)

```bash
git clone https://github.com/madtank/nova-act-mcp.git
cd nova-act-mcp
uv sync
uv run nova_mcp.py
```

## License
[MIT](LICENSE)