# nova-act-mcp

An MCP server providing tools to control web browsers using the Amazon Nova Act SDK. Enables interactive browser automation with transparent agent reasoning via MCP.

![Nova Act MCP Example](assets/search_news.png)

## Table of Contents
- [What is nova-act-mcp?](#what-is-nova-act-mcp)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Getting Started](#getting-started)
- [Understanding Agent Thinking](#understanding-agent-thinking)
- [Tips for Effective Browser Automation](#tips-for-effective-browser-automation)
- [Advanced Features](#advanced-features)
- [Example Use Cases](#example-use-cases)
- [Performance Considerations](#performance-considerations)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgements](#acknowledgements)
- [Feedback for Amazon Nova Act](#feedback-for-amazon-nova-act)
- [Limitations](#limitations)
- [Development](#development)
- [Future Enhancements](#future-enhancements)

## What is nova-act-mcp?

Nova Act MCP is a bridge between Amazon's Nova Act browser automation SDK and the Model Context Protocol (MCP). It allows AI assistants like Claude to control web browsers to perform tasks through natural language instructions, while providing visibility into the agent's reasoning process.

This project exposes Nova Act's powerful browser automation capabilities through an MCP server interface, making it easy to:

1. Control web browsers directly from AI assistants
2. Execute interactive browser automation tasks
3. Persist cookies and local storage between interactions (profile data is reused), noting that each `execute` spawns a fresh browser context so in-page state or filled forms will not carry over unless combined into a single instruction
4. See the agent's step-by-step reasoning process

## Prerequisites

Before getting started, you'll need:

- Python 3.10 or higher
- An Amazon Nova Act API key (get one from [https://nova.amazon.com/act](https://nova.amazon.com/act))
- Claude Desktop application (for using with Claude)

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/madtank/nova-act-mcp.git
   cd nova-act-mcp
   ```

2. Install dependencies:
   ```bash
   # Update dependencies after changing pyproject.toml or cloning
   uv sync

   # For development only - if you need to add a new dependency
   # uv add package_name
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
           "~/path/to/nova-act-mcp", // Replace with the absolute path to the cloned repo
           "run",
           "nova_mcp.py"
         ],
         "transport": "stdio",
         "env": {
           "NOVA_ACT_API_KEY": "your_api_key_here" // Replace with your Nova Act API key
         }
       }
     }
   }
   ```

   Replace:
   - `~/path/to/nova-act-mcp` with the absolute path to where you cloned this repository
   - `your_api_key_here` with your actual Nova Act API key

4. Save the file and restart Claude Desktop

### 3. Using with Your MCP Client (Example: Claude)

Once configured, you can use the browser automation tool with your MCP client. For Claude Desktop, look for the hammer icon (🔨), which indicates available MCP tools.

Try a simple example like this:

```
Can you help me search for news on Google? Use the nova-browser tool to:
1. Start a session on google.com
2. Execute the instruction "search for news"
3. Tell me what you see and your reasoning process
```

## Understanding Agent Thinking

One of the key features of nova-act-mcp is the ability to see the agent's reasoning process. When the agent performs actions in the browser, you'll see detailed explanations of:

1. How it's interpreting your instructions
2. What elements it sees on the page
3. Why it's choosing specific actions
4. How it confirms successful completion

This transparency helps you understand how the agent is approaching tasks and makes debugging easier when something doesn't work as expected.

## Tips for Effective Browser Automation

### Be Specific and Concise

When prompting for browser actions:

✅ **DO**:
- Provide clear, actionable instructions
- Focus on one task at a time
- Be specific about what elements to interact with

❌ **DON'T**:
- Use vague or ambiguous language
- Request complex multi-step actions in a single instruction
- Ask for subjective evaluations without clear criteria

### Example of Good Instructions

Instead of trying to do everything at once, break it down into interactive steps:

```
1. Start a session on amazon.com
2. Execute "search for bluetooth headphones"
3. Execute "filter by 4+ stars"
4. Execute "sort by price low to high"
5. Execute "find the price of the first item"
```

## Advanced Features

### Persistent Browser Profiles

The nova-act-mcp server maintains a separate profile directory for each session under `profiles/{session_id}`, reusing that profile on every `execute`. This ensures:
- Cookies, login tokens, and local storage persist between calls
- Profile isolation per session ID

**Note:** Each `execute` command launches a new browser context on the same profile to pick up cookies/storage. In-page state (e.g. form fields, DOM changes) will not persist across separate `execute` calls. To preserve multi-step page state, combine your steps into a single `execute` instruction.

### Browser Session Management and Persistence

The following actions are available for browser session management:

1. **start** - Starts a new browser session with a specified URL
2. **execute** - Executes a natural language instruction in the current session
3. **end** - Ends the current browser session and cleans up resources

Example flow:
```
# Start a session
start: https://www.google.com

# Execute instructions
execute: search for news
execute: click on the first result

# End the session
end
```

#### Important: Browser Persistence

The browser launched during a `start` action remains open throughout the session lifecycle:

- The same browser instance is reused for all `execute` commands within a session
- Each browser runs in its own dedicated thread to ensure thread safety
- The browser continues running in the background between commands, maintaining its state
- **Browser windows are only closed when:**
  - You explicitly call the `end` action for a session
  - The nova-act-mcp server process exits (using a cleanup mechanism)
  - Sessions are automatically cleaned up after 10 minutes of inactivity

**Warning:** If you don't properly end sessions with the `end` action, browser instances may continue running in the background, consuming system resources. Always make sure to end your sessions when you're done using them.

To check for and close any lingering sessions, you can use the `list_browser_sessions` tool to identify active sessions, then call `end` on any sessions you no longer need.

## Example Use Cases

Here are some practical developer-focused tasks you can accomplish using nova-act-mcp:

### On-Call Response Automation

This example shows how an AI system could automatically respond to alerts by investigating your internal systems:

```
1. Start a session on our-monitoring-dashboard.company.com
2. Execute "authenticate using system credentials"
3. Execute "check the status of the payment processing service"
4. Execute "take a screenshot of the error metrics graph"
5. Execute "navigate to the database connection panel"
6. Execute "verify if connection timeout errors have increased"
7. Execute "check service health endpoints status"
```

### Web Application Testing

```
1. Start a session on localhost:3000
2. Execute "fill the registration form with test data, but use an invalid email format"
3. Execute "verify that validation errors appear for the email field"
4. Execute "correct the email and submit the form"
5. Execute "check if the confirmation page loads with the correct user information"
6. Execute "verify the welcome email appears in the test inbox"
```

### Cross-Browser Verification

```
1. Start a session on localhost:3000/new-feature
2. Execute "check if the dropdown menu works on mobile viewport"
3. Execute "resize to desktop dimensions"
4. Execute "verify that responsive layout elements adjust correctly"
5. Execute "take a screenshot of the component in both mobile and desktop views"
6. Execute "test keyboard navigation through the form elements"
```

### Local Development Loop

```
1. Start a session on localhost:3000
2. Execute "inspect the CSS for the header element"
3. Execute "verify the padding matches the design spec of 16px"
4. Execute "refresh the page and check if the media query triggers at 768px width"
5. Execute "test if dark mode toggle correctly updates the color scheme"
```

### API Endpoint Verification

```
1. Start a session on our-api-dashboard.company.com
2. Execute "navigate to the /users endpoint documentation"
3. Execute "send a test request with parameter limit=10"
4. Execute "verify the response includes the new 'last_login' field"
5. Execute "test the same endpoint with an invalid authentication token"
6. Execute "confirm that the proper error response is returned"
```

## Performance Considerations

When working with browser automation at scale, keep these performance considerations in mind:

### Resource Management

- **Concurrent Sessions**: Each browser session consumes significant memory. For large-scale automation, consider implementing session pooling and limiting concurrent sessions.
- **Memory Usage**: Chrome instances can use 300MB-1GB of RAM each. Monitor memory usage when running multiple sessions.
- **CPU Utilization**: Browser automation is CPU-intensive, especially when parsing complex pages. Schedule tasks to avoid CPU saturation.

### Optimization Strategies

- **Headless Mode**: For production environments, consider running browsers in headless mode for better resource efficiency.
- **Request Throttling**: Implement rate limiting to avoid triggering anti-bot measures on websites.
- **Caching**: Cache responses when appropriate to reduce redundant requests.
- **Efficient Selectors**: Use precise selectors rather than broad instructions to improve performance.

### Best Practices for Large-Scale Automation

- **Session Reuse**: Where appropriate, reuse browser sessions instead of creating new ones.
- **Cleanup**: Always end sessions properly when done to free up system resources.
- **Explicit Session Ending**: Always call the `end` action when you're done with a session to prevent resource leaks.
- **Session Monitoring**: Periodically check for active sessions using `list_browser_sessions` to ensure proper cleanup.
- **Batching**: Group related tasks into batches to minimize the overhead of session creation.
- **Error Handling**: Implement robust error handling with automatic retries for transient failures.

## Testing

You can test the nova-act-mcp server using the MCP Inspector tool:

```bash
# Install MCP Inspector if you haven't already
npm install -g @modelcontextprotocol/inspector

# Run the server with the MCP Inspector
NOVA_ACT_API_KEY="your_api_key_here" npx @modelcontextprotocol/inspector uv --directory /path/to/nova-act-mcp run nova_mcp.py
```

Then use the following input format to test a simple browser action:

```json
{
  "action": "start",
  "url": "https://www.google.com"
}
```

Followed by:

```json
{
  "action": "execute",
  "session_id": "your_session_id_from_previous_response",
  "instruction": "search for tea pots"
}
```

This lets you verify that the server is working correctly and see exactly what the agent is thinking during each step.

## Troubleshooting

### Nova Act API Key Issues

If you see an error about the Nova Act API key:

1. Verify your API key is valid at [https://nova.amazon.com/act](https://nova.amazon.com/act)
2. Check that the key is correctly set in your Claude Desktop configuration
3. Try setting it as an environment variable: `export NOVA_ACT_API_KEY="your_key_here"`

### Browser Automation Problems

If the browser is not behaving as expected:

1. Check the agent_thinking field in the response to see how the agent is interpreting your instructions
2. Make your instructions more specific and actionable
3. For tasks involving forms or logins, be explicit about field names

### Lingering Browser Windows

If you notice browser windows staying open after you're done using the tool:

1. Make sure you always call the `end` action when you're finished with a session
2. Use `list_browser_sessions` to check for any active sessions that need to be closed
3. Restart the MCP server if needed to force cleanup of all browser sessions
4. Check your system's task manager for any lingering browser processes

### Debug Mode

To enable more detailed debugging information:

```bash
export NOVA_MCP_DEBUG=1
```

This will include additional diagnostic information in the responses.

## Contributing

We welcome contributions to improve nova-act-mcp! Here's how you can help:

### Getting Started with Development

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes and add tests if applicable
4. Run tests to ensure your changes work correctly
5. Commit your changes: `git commit -m 'Add some feature'`
6. Push to the branch: `git push origin feature-name`
7. Submit a pull request

### Development Guidelines

- Follow the existing code style and naming conventions
- Write clear, commented code with meaningful variable/function names
- Include documentation for any new features
- Add tests for new functionality
- Update the README if necessary

### Reporting Issues

If you find a bug or have a feature request, please create an issue on the repository. Include:

- A clear description of the issue or feature request
- Steps to reproduce (for bugs)
- Expected behavior
- Actual behavior
- Environment information (OS, Python version, etc.)

### Code Reviews

All submissions require review before being merged. We aim to review pull requests promptly and provide constructive feedback.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgements

- [Amazon Nova Act](https://labs.amazon.science/blog/nova-act) for providing the browser automation SDK
- [Model Context Protocol (MCP)](https://github.com/anthropics/anthropic-cookbook/tree/main/mcp) for the AI agent communication standard

## Feedback for Amazon Nova Act

While we've implemented agent thinking extraction, we note that this information should ideally be directly accessible through the Nova Act API. The current approach requires parsing HTML trace files, which is less efficient than having a dedicated API method. We welcome any future improvements to the Nova Act SDK that would make this process more straightforward.

## Limitations

- **No file uploads**: The browser automation can't upload files from your local system
- **Limited to web interactions**: Can only interact with elements visible on the webpage
- **Some sites may block automation**: Sites with strong anti-bot measures may present challenges
- **Session timeouts**: Long-running sessions may be terminated by websites

## Development

### Managing Dependencies

This project uses [uv](https://github.com/astral-sh/uv) for dependency management, which provides faster and more reliable Python package management.

To update or add dependencies:

1. Edit the `pyproject.toml` file to add or modify dependencies in the appropriate sections:
   ```toml
   dependencies = [
       "new-package>=1.0.0",  # Add your new dependency here
   ]
   ```

2. Use `uv sync` to update the lock file:
   ```bash
   uv sync
   ```

3. Commit both the modified `pyproject.toml` and the updated `uv.lock` file to the repository.

This ensures that all developers and users have consistent dependency versions.

## Future Enhancements

- [x] **Multi-Step Session State**: Support true in-page session persistence across multiple `execute` calls so that form inputs and DOM changes remain live between commands.
- **Improve Profile Persistence**: Enhance handling of profiles for even more reliable cookie and storage reuse.
