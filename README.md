# nova-act-mcp

An MCP server providing tools to control web browsers using the Amazon Nova Act SDK. Enables interactive browser automation with transparent agent reasoning via MCP.

## Table of Contents
- [What is nova-act-mcp?](#what-is-nova-act-mcp)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Getting Started](#getting-started)
- [Understanding Agent Thinking](#understanding-agent-thinking)
- [Tips for Effective Browser Automation](#tips-for-effective-browser-automation)
- [Advanced Features](#advanced-features)
- [Example Capabilities](#example-capabilities)
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
3. Persist cookies and local storage between interactions (profile data is reused)

4. See the agent's step-by-step reasoning process

## Prerequisites

Before getting started, you'll need:

- Python 3.10 or higher
- An Amazon Nova Act API key (get one from [https://nova.amazon.com/act](https://nova.amazon.com/act))
- An MCP-compatible client (Claude Desktop, VSCode with Copilot Plugin, or any other client that supports the Model Context Protocol)

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

### Quick Start with uvx

For the fastest way to get started without cloning the repository or setting up a virtual environment:

```bash
# No clone, no venv – zero-install test
uvx nova-act-mcp control_browser --action start --url https://example.com
```

This uses the Python package manager UVX to directly run the latest version from PyPI.

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

### Navigation Limitations and Best Practices

**IMPORTANT:** The Nova Act agent has specific navigation limitations that are critical to understand:

1. **Always Provide URLs for Page Changes**: When navigating to a different website or page, you MUST include the full URL in the `url` parameter:
   ```json
   {"action": "execute", "session_id": "your-session-id", "url": "https://www.amazon.com/", "instruction": "Search for headphones"}
   ```

2. **No Back Button Navigation**: The agent doesn't understand browser history concepts like "back" or "forward" buttons. To return to a previous page, you must provide its full URL again.

3. **Direct URL Access is Best**: Rather than trying to navigate through multiple pages to reach your target, provide the direct URL of your target page whenever possible.

4. **Page-Specific Actions**: Each instruction should be specific to the current page. If you need to work on different pages, use separate commands with the appropriate URLs.

### Example: Correct Workflow

```
# CORRECT: Direct navigation to target site with specific action
control_browser {"action": "execute", "session_id": "your-session-id", "url": "https://www.amazon.com", "instruction": "Search for bluetooth headphones"}

# CORRECT: New direct navigation to a different site
control_browser {"action": "execute", "session_id": "your-session-id", "url": "https://www.google.com", "instruction": "Search for weather forecast"}
```

### Example: Problematic Workflow

```
# PROBLEMATIC: Expecting navigation without URL
control_browser {"action": "execute", "session_id": "your-session-id", "instruction": "Go to Amazon and search for headphones"}

# PROBLEMATIC: Assuming back button functionality
control_browser {"action": "execute", "session_id": "your-session-id", "instruction": "Go back to the previous page"}
```

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

### Handling Invalid URLs and Navigation Errors

The Nova Act agent handles invalid or inaccessible URLs in different ways, which is important to understand when working with AI systems that might reference non-existent websites:

1. **Non-existent Domains**: If the domain doesn't exist (e.g., `https://this-website-definitely-does-not-exist-123456789.com`), you'll receive an error message like:
   ```
   Error executing instruction: Failed to navigate to execute URL https://non-existent-site.com: 
   Page.goto: net::ERR_NAME_NOT_RESOLVED
   ```

2. **Valid Domain with Non-existent Path**: If the domain exists but the specific page doesn't (e.g., `https://example.com/non-existent-page-12345`), the browser will still load the domain's default page or an error page provided by the website. The agent will describe whatever content appears.

3. **Connection Refused**: For URLs pointing to servers that aren't running or aren't accessible (e.g., `http://localhost:9999`), you'll receive an error like:
   ```
   Error executing instruction: Failed to navigate to execute URL http://localhost:9999: 
   Page.goto: net::ERR_CONNECTION_REFUSED
   ```

**Best Practice**: When dealing with URLs that might not exist (such as those suggested by an AI model), start with a verified root domain first, then navigate to more specific pages:

```
# Start with a known working domain
control_browser {"action": "execute", "session_id": "your-session-id", "url": "https://example.com", "instruction": "Tell me what you see"}

# Then try a more specific path if needed
control_browser {"action": "execute", "session_id": "your-session-id", "url": "https://example.com/specific-path", "instruction": "Tell me what you see"}
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

### Browser Visibility and Screenshots

The nova-act-mcp server has been configured with some important defaults:

- **Headless Mode by Default**: Browsers now start in headless mode (invisible) by default, which improves performance and resource usage. This is ideal for production environments and automated workflows.

- **Screenshot Embedding Disabled**: Screenshot embedding has been disabled to prevent excessive token usage in the context window. Large base64-encoded screenshots were causing token explosions, making conversations difficult to maintain.

You can still:
- Explicitly set `"headless": false` in your requests if you want to observe the browser's actions
- Access Nova Act's HTML logs which are referenced in the response (the path is provided)

**Example:**
```
# Start a headless browser (default)
control_browser {"action": "start", "url": "https://www.google.com"}

# Start a visible browser by overriding the default
control_browser {"action": "start", "url": "https://www.google.com", "headless": false}
```

### Secure Login Handling

Nova Act MCP provides a secure way to handle login credentials that avoids exposing sensitive information in instructions:

```json
// SECURE: Using dedicated username/password parameters
control_browser {
  "action": "execute", 
  "session_id": "your-session-id", 
  "username": "tomsmith", 
  "password": "SuperSecretPassword!"
}
```

When you provide the `username` and/or `password` parameters:

1. The MCP server **directly uses Playwright** to find and fill credential fields
2. Credentials are never exposed in the instruction text or agent thinking
3. If a login form is detected, it will automatically try to submit the form after filling credentials
4. If just `username` is provided without a `password`, it will still attempt form submission (useful for testing invalid login scenarios)

This approach is significantly more secure than including credentials in the instruction text:

```json
// INSECURE: Don't do this!
control_browser {
  "action": "execute", 
  "session_id": "your-session-id", 
  "instruction": "Type username 'tomsmith' and password 'SuperSecretPassword!' into the login form"
}
```

#### How Login Form Detection Works

The tool uses these strategies to find and fill login forms:

1. First tries explicit selectors: `input#username, input[name='username'], input[type='text'], input[name*='user']` for username fields
2. Similarly uses `input#password, input[name='password'], input[type='password'], input[name*='pass']` for password fields  
3. If those fail, it falls back to using Nova Act to "focus the username/password field" and then uses keyboard typing
4. After filling fields, if no further instruction is provided, it automatically clicks the Login button

#### Example: Complete Login Flow

```json
// Start a session on a login page
control_browser {"action": "start", "url": "https://the-internet.herokuapp.com/login"}

// Provide credentials securely (will auto-submit form)
control_browser {
  "action": "execute", 
  "session_id": "your-session-id", 
  "username": "tomsmith", 
  "password": "SuperSecretPassword!"
}

// After login, perform actions on the authenticated page
control_browser {
  "action": "execute", 
  "session_id": "your-session-id", 
  "instruction": "Check if we're logged in successfully"
}
```

This approach keeps credentials out of instruction text while providing a seamless login experience.

### Browser Session State Persistence

One of the key features of nova-act-mcp is its ability to maintain session state across multiple navigation actions. This makes it ideal for complex workflows that span multiple pages on a website.

Our testing has verified that the browser automation tool properly maintains:

1. **Authentication State**: Login sessions persist across page navigations
2. **Cookies & Local Storage**: Site preferences and settings are preserved
3. **Navigation History**: The ability to navigate between pages while maintaining state

This has been verified with workflows that:
- Log in to a secure area
- Navigate to different pages
- Interact with elements on those pages
- Return to the secure area with authentication still intact

For optimal session persistence:

```json
// Start a session
control_browser {"action": "start", "url": "https://example.com/login"}

// Login securely
control_browser {
  "action": "execute", 
  "session_id": "your-session-id", 
  "username": "your-username", 
  "password": "your-password"
}

// Navigate to another page while maintaining session cookies
control_browser {
  "action": "execute", 
  "session_id": "your-session-id", 
  "instruction": "Navigate to https://example.com/account"
}

// Continue working with the authenticated session
control_browser {
  "action": "execute", 
  "session_id": "your-session-id", 
  "instruction": "Check my account balance"
}
```

**Important Note**: While authentication state (cookies, local storage) persists across page navigations, each `execute` command launches a fresh browser context on that same profile. This means that in-page state changes (form fields, JavaScript variables) do not persist between separate `execute` commands. For multi-step interactions on a single page, include all steps in a single instruction.

## Example Capabilities

Nova Act MCP can handle a variety of browser automation tasks:

- **Basic Navigation & Form Handling**: Navigate websites, fill forms, and handle login flows securely
- **Dynamic Content**: Wait for and interact with content that loads asynchronously
- **Structured Data Extraction**: Extract table data and other structured content using JSON schemas
- **Complex Interactions**: Handle alerts, dropdowns, and other interactive elements

<div align="center">
  <a href="#basic-navigation-and-form-handling">
    <img src="assets/test_basic_auth.png" alt="Basic Navigation & Form Authentication" width="250"/>
  </a>
  <a href="#dynamic-content">
    <img src="assets/test_dynamic_loading.png" alt="Dynamic Content Loading" width="250"/>
  </a>
  <a href="#structured-data-extraction">
    <img src="assets/nova-act-extract-news.png" alt="Structured Data Extraction" width="250"/>
  </a>
</div>

For best results, provide clear, specific instructions and follow the navigation best practices outlined above.

### Structured Data Extraction

One of the most powerful capabilities of Nova Act MCP is its ability to extract structured data from web pages using JSON schemas:

```json
// Example schema for extracting table data
{
  "type": "object",
  "properties": {
    "tableData": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "price": {"type": "string"},
          "description": {"type": "string"}
        }
      }
    }
  }
}
```

To use this feature:

```json
// Extract structured data using a schema
control_browser {
  "action": "execute", 
  "session_id": "your-session-id", 
  "schema": {your_schema_here}
}
```

The agent will analyze the page content and extract data that matches your schema structure. This is particularly useful for:

- Extracting product information from e-commerce sites
- Retrieving data from tables and lists
- Gathering structured information from search results
- Collecting consistent data across multiple pages

**Note on Data Size**: The default response size limit is 5000 characters. If you're extracting large datasets that might exceed this limit, consider:
1. Breaking your extraction into smaller chunks
2. Extracting only the most relevant columns
3. Adding pagination to retrieve data in batches

### Form Element Interactions

Nova Act MCP provides specific capabilities for interacting with common form elements. Based on our testing, here are the recommended ways to interact with different form elements:

#### Dropdown Menus

For reliable dropdown interactions, use explicit phrasing:

```json
// Recommended approach for dropdown interaction
control_browser {
  "action": "execute", 
  "session_id": "your-session-id", 
  "instruction": "select Option 2 from the dropdown"
}
```

Our testing shows that these phrasings work consistently:
- "select [option name] from dropdown" 
- "choose [option name] from the dropdown menu"

To verify which option is currently selected, use a schema:

```json
// Check current dropdown selection
control_browser {
  "action": "execute", 
  "session_id": "your-session-id",
  "schema": {
    "type": "object", 
    "properties": {
      "selectedOption": {"type": "string"}
    }
  }
}
```

Less reliable approaches to avoid:
- ❌ "Click on the dropdown" (too vague, may not complete the selection)
- ❌ "Open the dropdown menu" (only opens but doesn't select)

#### Checkboxes

For checkboxes, use precise instructions:

```json
// Toggle a checkbox
control_browser {
  "action": "execute", 
  "session_id": "your-session-id", 
  "instruction": "check the checkbox labeled 'I agree to terms'"
}

// Or uncheck
control_browser {
  "action": "execute", 
  "session_id": "your-session-id", 
  "instruction": "uncheck the checkbox labeled 'Subscribe to newsletter'"
}
```

#### Radio Buttons

For radio button selection:

```json
// Select a radio button
control_browser {
  "action": "execute", 
  "session_id": "your-session-id", 
  "instruction": "select the radio button labeled 'Option B'"
}
```

#### Input Fields

For text input fields:

```json
// Type into an input field
control_browser {
  "action": "execute", 
  "session_id": "your-session-id", 
  "instruction": "type 'example@email.com' into the email field"
}
```

## Performance Considerations

When working with browser automation at scale, keep these performance considerations in mind:

### Resource Management

- **Concurrent Sessions**: Each browser session consumes significant memory. For large-scale automation, consider implementing session pooling and limiting concurrent sessions.
- **Memory Usage**: Chrome instances can use 300MB-1GB of RAM each. Monitor memory usage when running multiple sessions.
- **CPU Utilization**: Browser automation is CPU-intensive, especially when parsing complex pages. Schedule tasks to avoid CPU saturation.

### Optimization Strategies

- **Headless Mode**: For production environments, consider explicitly setting headless mode to true (`"headless": true`) for better resource efficiency. While the default is now non-headless for better debugging, headless browsers use fewer resources.
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

### Setting Up Your Test Environment

Before running tests, ensure you have all the required testing dependencies installed:

```bash
# Install development dependencies including testing packages
uv sync --extra dev

# Verify test dependencies are installed
uv pip list | grep pytest
```

This will install pytest and all related testing packages defined in the `[project.optional-dependencies]` section of your `pyproject.toml`.

### Running Tests

You can test the nova-act-mcp server in several ways:

#### 1. Running Specific Test Files with Detailed Output

For detailed test output with verbose logging, use the `-v` flag. To see print statements in your tests, add the `-s` flag:

```bash
# Run a specific test file with verbose output and print statements
python -m pytest -v -s tests/test_nova_mcp_integration.py

# Run all tests with verbose output
python -m pytest -v


The `-s` flag is particularly useful for debugging as it allows print statements in your tests to be displayed in the console.

#### 2. Using the MCP Inspector Tool

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

For manual testing, we provide a test script that works with The Internet Herokuapp (a testing website):

```bash
# Run the test script to generate a set of test commands
./testing/test_form_interaction.sh

# Follow the instructions to test interactive browser automation
```

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

### Viewing Browser Activity

Since browsers now run in visible mode by default:

1. You can directly observe the automation actions in real-time
2. If you need to hide the browser (for example, in CI/CD environments), explicitly set `"headless": true`
3. For debugging, the response includes the path to Nova Act's HTML log file, which shows detailed execution steps

### Debug Mode

To enable more detailed debugging information:

```bash
export NOVA_MCP_DEBUG=1
```

This will include additional diagnostic information in the responses.

### Common Issues

#### "nova-act is installed but Python can't import it"

This happens because `uv --directory ... run nova_mcp.py` creates a fresh, isolated virtual environment each time it runs. That environment only contains the packages in the current directory (your nova-act-mcp installation), without access to globally installed packages.

**Solution 1: For local development (with a cloned repository)**

Install the "nova-act" extra into the same uv environment before running:

```bash
# From your nova-act-mcp repository directory
cd /path/to/nova-act-mcp
uv pip install -e .[nova-act]   # Pulls nova-act + playwright into the .uv-env folder
```

Your MCP client configuration can remain unchanged:

```json
"nova-browser": {
  "command": "uv",
  "args": [
    "--directory",
    "/path/to/nova-act-mcp",
    "run",
    "nova_mcp.py"
  ],
  "env": { "NOVA_ACT_API_KEY": "your_api_key_here" }
}
```

Once the dependencies are cached in the `.uv-env` folder, every subsequent `uv run` will find nova_act in the Python path.

**Solution 2: Zero-install approach (with uvx)**

For production environments or other machines, use uvx to automatically handle all dependencies:

```toml
# settings.toml or claude_desktop_config.json
[servers.nova-browser]
command   = "uvx"
args      = ["nova-act-mcp[nova-act]@0.2.0"]  # The [nova-act] extra contains browser automation deps
transport = "stdio"

[servers.nova-browser.env]
NOVA_ACT_API_KEY = "${NOVA_ACT_API_KEY}"
HEADLESS         = "true"  # Optional: run browser in headless mode
```

With this approach, uvx will:
1. Download nova-act-mcp version 0.2.0
2. Detect the [nova-act] extra and automatically install nova-act and playwright
3. Launch the nova-act-mcp console script in an isolated environment

This requires no pre-installation or path configuration.

#### Clearing the Cache

If you're experiencing persistent issues, try clearing the uv cache:

```bash
uv cache clear  # Wipes previous temporary environments
```

#### Verify Installation

To verify that nova-act is correctly installed in your uv environment:

```bash
uv --directory /path/to/nova-act-mcp run -c "import nova_act; print(f'nova-act version: {nova_act.__version__}')"
```

If this prints the version without any import errors, your setup is correct.

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
- **Hover interactions not supported**: The current implementation cannot reliably perform hover-based interactions or extract content that appears on hover
- **JavaScript alerts not reliably handled**: While alert dialogs visually appear, the agent cannot properly control or interact with them
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

### Local Development Setup

Setting up a local development environment:

1. Create and activate a virtual environment with uv:
   ```bash
   # From repo root
   uv venv .venv
   
   # On macOS/Linux
   source .venv/bin/activate
   
   # On Windows
   .venv\Scripts\activate
   ```

2. Install the package in development mode with dev dependencies:
   ```bash
   uv pip install -e .[dev]
   ```

3. Verify the installation:
   ```bash
   python -m nova_mcp --version
   ```

4. Run tests to verify everything works:
   ```bash
   pytest -q
   ```

5. For UVX testing (even from within the venv):
   ```bash
   uvx nova-act-mcp@0.2.0 --version
   ```

### Dependency Locking

To ensure reproducible environments:

1. Generate a lockfile (once):
   ```bash
   uv pip compile -o uv.lock
   ```

2. Commit the lockfile to your repository.

3. On new machines or in CI, use:
   ```bash
   uv pip sync -r uv.lock
   ```

This approach prevents dependency issues and ensures consistent behavior across different environments.

## Future Enhancements

- [x] **Multi-Step Session State**: Support true in-page session persistence across multiple `execute` calls so that form inputs and DOM changes remain live between commands.
- [x] **Improved Browser Visibility**: Default to visible browsers for better debugging and observation.
- [x] **Reduced Token Usage**: Disabled screenshot embedding to prevent token explosion in LLM context windows.
- **Improve Profile Persistence**: Enhance handling of profiles for even more reliable cookie and storage reuse.
