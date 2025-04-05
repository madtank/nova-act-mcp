# nova-act-mcp

An MCP server providing tools to control web browsers using the Amazon Nova Act SDK. Enables multi-step browser automation workflows via MCP agents.

![Nova Act MCP Example](assets/search_news.png)

## What is nova-act-mcp?

Nova Act MCP is a bridge between Amazon's Nova Act browser automation SDK and the Model Context Protocol (MCP). It allows AI assistants like Claude to control web browsers to perform complex tasks through natural language instructions.

This project exposes Nova Act's powerful browser automation capabilities through an MCP server interface, making it easy to:

1. Control web browsers directly from AI assistants
2. Execute multi-step browser workflows
3. Maintain browser sessions between interactions
4. Automate repetitive web tasks with AI guidance

## Prerequisites

Before getting started, you'll need:

- Python 3.10 or higher
- An Amazon Nova Act API key (get one from [https://nova.amazon.com/act](https://nova.amazon.com/act))
- Claude Desktop application (for using with Claude)

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/nova-act-mcp.git
   cd nova-act-mcp
   ```

## Getting Started

This guide focuses on setting up the server with the Claude Desktop application, but `nova-act-mcp` is designed to work with any Model Context Protocol (MCP) compatible client, such as Visual Studio Code or others. Consult your specific client's documentation for instructions on integrating MCP servers.

![Nova Act MCP Claude Example](assets/search_news_claude_desktop.png)

### 1. Obtain a Nova Act API Key

1. Go to [https://nova.amazon.com/act](https://nova.amazon.com/act)
2. Generate a new API key
3. Save it for the next step

### 2. Configure Your MCP Client (Example: Claude Desktop)

The following steps show how to configure the Claude Desktop application. If you are using a different MCP client, adapt these instructions accordingly.

1. Install Claude Desktop from [https://claude.ai/desktop](https://claude.ai/desktop) (if using Claude).
2. Open your Claude for Desktop App configuration:

   ```bash
   # MacOS
   code ~/Library/Application\ Support/Claude/claude_desktop_config.json

   # Windows
   code %USERPROFILE%\AppData\Roaming\Claude\claude_desktop_config.json
   ```

3. Add the nova-act-mcp server configuration:

   ```json
   {
     "mcpServers": {
       "nova-browser": {
         "command": "uv",
         "args": [
           "--directory",
           "/full/path/to/nova-act-mcp",
           "run",
           "nova_mcp.py"
         ],
         "transport": "stdio",
         "env": {
           "NOVA_ACT_API_KEY": "your_api_key_here"
         }
       }
     }
   }
   ```

   Replace:
   - `/full/path/to/nova-act-mcp` with the absolute path to where you cloned this repository
   - `your_api_key_here` with your actual Nova Act API key

4. Save the file and restart Claude Desktop

### 3. Using with Your MCP Client (Example: Claude)

Once configured, you can use the browser automation tool with your MCP client. For Claude Desktop, look for the hammer icon (🔨), which indicates available MCP tools.

Try a simple example like this:

```
Can you help me find a teapot on Amazon? Use the nova-browser tool to:
1. Go to amazon.com
2. Search for "tea pots"
3. Select the first result
4. Add it to the cart
```

## Tips for Effective Browser Automation

### Be Specific and Concise

When prompting for browser actions:

✅ **DO**:
- Use specific, concrete instructions
- Break complex tasks into smaller steps
- Be explicit about what to click or interact with

❌ **DON'T**:
- Use vague or open-ended instructions
- Request multi-page workflows in a single step
- Ask the agent to "browse" or "explore" without specific goals

### Example of Good Instructions

```
Please use nova-browser to:
1. Go to amazon.com
2. Search for "bluetooth headphones"
3. Filter by 4+ stars
4. Sort by price low to high
5. Add the first item that costs more than $30 to the cart
```

### Example of Problematic Instructions

```
Please use nova-browser to find me some good deals on headphones and buy the best one.
```

## Advanced Features

### Persistent Browser Sessions

The nova-act-mcp server maintains browser profiles in the `profiles/` directory, allowing you to:

- Maintain login sessions between uses
- Keep cookies and local storage data
- Resume workflows where you left off

Each profile is isolated, so you can maintain different identities or login states.

## Testing

Running the server with the MCP Inspector is a great way to get started and verify that your setup is working correctly, independent of any specific AI assistant or client application.

You can test the nova-act-mcp server using the MCP Inspector tool:

```bash
# Install MCP Inspector if you haven't already
npm install -g @modelcontextprotocol/inspector

# Run the server with the MCP Inspector
NOVA_ACT_API_KEY="your_api_key_here" npx @modelcontextprotocol/inspector uv --directory /path/to/nova-act-mcp run nova_mcp.py
```

Then use the following input format to test a simple Amazon shopping workflow:

```json
{
  "starting_url": "https://www.amazon.com",
  "steps": [
    "search for tea pots",
    "select the first result",
    "add to cart"
  ]
}
```

This will:
1. Open a browser window to Amazon.com
2. Search for "tea pots"
3. Click on the first search result
4. Add the item to the cart

This simple test demonstrates the core functionality and confirms your setup is working correctly.

## Troubleshooting

### Nova Act API Key Issues

If you see an error about the Nova Act API key:

1. Verify your API key is valid at [https://nova.amazon.com/act](https://nova.amazon.com/act)
2. Check that the key is correctly set in your Claude Desktop configuration
3. Try setting it as an environment variable: `export NOVA_ACT_API_KEY="your_key_here"`

### Browser Automation Problems

If the browser is not behaving as expected:

1. Check that your prompts are specific and actionable
2. Break down complex tasks into smaller steps
3. For tasks involving forms or logins, be explicit about field names

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgements

- [Amazon Nova Act](https://labs.amazon.science/blog/nova-act) for providing the browser automation SDK
- [Model Context Protocol (MCP)](https://github.com/anthropics/anthropic-cookbook/tree/main/mcp) for the AI agent communication standard

## Best Practices

### Writing Effective Browser Instructions

For the best results when using nova-act-mcp:

1. **Be specific and direct**: Tell the browser exactly what to do in each step
   ```
   "Click the 'Add to Cart' button"
   ```
   Not: "Maybe we should add this to our cart"

2. **Keep instructions short**: Each step should be a single, clear action
   ```
   "Search for 'wireless headphones'"
   ```
   Not: "Let's look for some wireless headphones that have good battery life and are affordable"

3. **Use common web terminology**: Use terms like "click", "search", "select", "scroll", etc.
   ```
   "Click on the 'Sign In' link"
   ```

4. **Sequential steps work best**: Break complex tasks into a series of simple steps

### Limitations

- **No file uploads**: The browser automation can't upload files from your local system
- **Limited to web interactions**: Can only interact with elements visible on the webpage
- **Some sites may block automation**: Sites with strong anti-bot measures may present challenges
- **Session timeouts**: Long-running sessions may be terminated by websites
