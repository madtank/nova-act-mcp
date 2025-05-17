# Nova Act MCP Tests

This directory contains tests for the Nova Act MCP project, organized into different categories:

## Test Categories

### 1. Unit Tests (`unit/`)
Fast tests with no external dependencies. These test individual components and functions in isolation, using mocks for external services.

- `test_tool_registration.py` - Tests registration of tools with the MCP server
- `test_log_compression.py` - Tests log compression functionality

### 2. Mock Tests (`mock/`)
Tests using mocked Nova Act / MCP components. These tests verify interactions with mocked instances of the Nova Act SDK.

- `test_nova_mcp_mock.py` - Tests MCP interactions with a mocked Nova Act instance
- `test_nova_mcp_basic.py` - Basic tests with a mocked Nova Act instance

### 3. Integration Tests (`integration/`)
Tests requiring API key and/or real browser instances. These tests verify that components work correctly with the real Nova Act API.

- `test_inspect_browser.py` - Tests the inspect_browser tool
- `test_nova_mcp_integration.py` - Integration tests for the full MCP
- `test_screenshot_compression.py` - Tests for screenshot compression
- `test_agent_visual_workflow.py` - Visual workflow tests that validate the full agent experience

### 4. Functional Tests (`functional/`)
End-to-end workflow tests that simulate agent usage. These tests verify natural language interactions with real websites.

- `test_nl_agent_workflows.py` - Natural language agent workflow tests using [The Internet Herokuapp](https://the-internet.herokuapp.com)

## Test Assets (`assets/`)
Test-specific assets used by the tests:

- `mock_output.html` - Mock HTML output for testing

## Running Tests

```bash
# Run unit tests only
pytest tests/unit

# Run mock tests only
pytest tests/mock  

# Run integration tests only (requires API key)
pytest tests/integration

# Run functional tests only (requires API key)
pytest tests/functional

# Run all tests
pytest
```

Note: Integration and functional tests require a valid `NOVA_ACT_API_KEY` environment variable and will be skipped if not provided.

## Environment Setup

Some tests require the Nova Act API key to be set as an environment variable:

```bash
export NOVA_ACT_API_KEY=your_api_key_here
```

Tests that require the API key are automatically skipped in CI environments or when the key is not available.

## Inline Screenshot Testing

The `test_inline_execute.py` file tests the automatic inline screenshot feature added in v0.2.7. This test:

1. Starts a browser session
2. Executes an action that triggers a screenshot
3. Verifies the screenshot is included in the response
4. Checks that the screenshot is properly formatted and within size limits

### Viewing Screenshots in Tests

When running the test with output capture disabled (`-s` flag), you can see the base64-encoded screenshot data:

```bash
python -m pytest -vs tests/test_inline_execute.py
```

The test will print:
- The full base64 data of the screenshot
- The size of the image in bytes and KB
- The configured size limit

Sample output:
```
INLINE SCREENSHOT DATA:
data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQAB...

Image size: 58686 bytes (57.31 KB)
Size limit: 256000 bytes (250.00 KB)
```

### Testing Without API Key

When testing in environments without the Nova Act API key, the inline screenshot test is automatically skipped with an appropriate message:

```
SKIPPED [1] tests/test_inline_execute.py:20: Skipping test_inline_execute in CI environment or when API key is not available
```

## CI/CD Testing

In CI/CD environments, tests are configured to run without requiring the Nova Act API key. The test structure follows best practices for both local development testing and CI pipeline compatibility.