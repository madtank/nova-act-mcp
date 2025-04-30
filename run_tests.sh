#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Running Nova Act MCP tests...${NC}"

# Check if API key is set in environment
if [ -z "$NOVA_ACT_API_KEY" ]; then
    echo -e "${YELLOW}Warning: NOVA_ACT_API_KEY environment variable not set.${NC}"
    echo -e "Some integration tests will be skipped."
    
    # Check if .env file exists
    if [ -f .env ]; then
        echo -e "${GREEN}Found .env file, sourcing environment variables...${NC}"
        # Source environment variables from .env file
        source .env
        echo -e "${GREEN}Environment variables loaded.${NC}"
    fi
fi

# Make sure we're in the virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${YELLOW}Activating virtual environment...${NC}"
    if [ -d "venv" ]; then
        source venv/bin/activate
    elif [ -d ".venv" ]; then
        source .venv/bin/activate
    else
        echo -e "${RED}Virtual environment not found. Please create it first.${NC}"
        echo -e "Run: python -m venv venv && source venv/bin/activate && uv sync"
        exit 1
    fi
fi

echo -e "${BLUE}Running tests with pytest...${NC}"
python -m pytest -v tests/test_nova_mcp.py tests/test_nova_mcp_mock.py tests/test_nova_mcp_basic.py tests/test_nova_mcp_integration.py

echo -e "${GREEN}Tests completed!${NC}"
