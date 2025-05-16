"""
File transfer tools for the Nova Act MCP Server.

This module provides functionality for transferring files between the client and server,
such as retrieving screenshots and logs.
"""

import base64
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional

from .. import mcp
from ..config import log, log_error, initialize_environment

@mcp.tool(
    name="fetch_file",
    description="Retrieves the contents of a file from the server, with optional base64 encoding. Primarily used to access log files, screenshots, and other assets generated during browser automation. Set encode_base64=True for binary files like images. Has a configurable size limit (default 10MB) to prevent excessive token usage with large files."
)
async def fetch_file(
    file_path: str,
    encode_base64: bool = False, 
    max_size: int = 10 * 1024 * 1024  # Default 10MB limit
) -> Dict[str, Any]:
    """
    Fetch a file from the server and optionally encode it as base64.
    
    This tool retrieves the contents of a file from the server's filesystem. It's
    commonly used to access log files, screenshots, and other assets generated during
    browser automation sessions. Binary files (like images) should be retrieved with
    encode_base64=True to ensure proper handling.
    
    Args:
        file_path: The absolute path to the file to fetch. This path should typically
                  come from the output of other tools (like inspect_browser or execute_instruction)
                  that generate or reference files on the server.
        encode_base64: Whether to encode the file content as base64. Set to True for binary
                      files like images, PDFs, etc. Set to False for text files.
        max_size: Maximum file size in bytes that can be fetched. Defaults to 10MB.
                 This limit exists to prevent excessive token usage with large files.
        
    Returns:
        A dictionary containing:
        - file_path (str): The path of the requested file
        - file_name (str): The name of the file (without the path)
        - file_size (int): Size of the file in bytes
        - content_type (str): Detected MIME type of the file
        - content (str): The file content as text or base64-encoded string
        - encoding (str): The encoding used ("utf-8" or "base64")
        - is_binary (bool): Whether the file was detected as binary
        - success (bool): True if the file was successfully retrieved
        - error (Optional[Dict]): Error information if the file could not be retrieved
    """
    initialize_environment()
    
    if not file_path:
        return {
            "error": {
                "message": "Missing required parameter: file_path",
                "code": "MISSING_PARAMETER"
            }
        }
    
    # Normalize path
    file_path = os.path.abspath(os.path.expanduser(file_path))
    
    # Check if the file exists
    if not os.path.isfile(file_path):
        return {
            "error": {
                "message": f"File not found: {file_path}",
                "code": "FILE_NOT_FOUND"
            }
        }
    
    # Check file size
    file_size = os.path.getsize(file_path)
    if file_size > max_size:
        return {
            "error": {
                "message": f"File too large: {file_size} bytes (max {max_size} bytes)",
                "code": "FILE_TOO_LARGE"
            },
            "file_path": file_path,
            "file_size": file_size,
        }
    
    try:
        # Get file metadata
        file_mtime = os.path.getmtime(file_path)
        file_name = os.path.basename(file_path)
        file_ext = os.path.splitext(file_name)[1].lower()
        
        # Determine content type
        content_type = "application/octet-stream"  # Default
        if file_ext in [".jpg", ".jpeg"]:
            content_type = "image/jpeg"
        elif file_ext == ".png":
            content_type = "image/png"
        elif file_ext == ".gif":
            content_type = "image/gif"
        elif file_ext in [".html", ".htm"]:
            content_type = "text/html"
        elif file_ext == ".json":
            content_type = "application/json"
        elif file_ext == ".txt":
            content_type = "text/plain"
        
        # Read the file
        with open(file_path, "rb") as f:
            file_content = f.read()
        
        # Encode as base64 if requested
        if encode_base64:
            encoded_content = base64.b64encode(file_content).decode("utf-8")
            
            # For images, create a data URL
            if content_type.startswith("image/"):
                data_url = f"data:{content_type};base64,{encoded_content}"
                
                # Prepare result with data URL
                result = {
                    "success": True,
                    "file_path": file_path,
                    "file_size": file_size,
                    "file_size_formatted": f"{file_size / 1024:.1f} KB",
                    "file_name": file_name,
                    "content_type": content_type,
                    "timestamp": file_mtime,
                    "timestamp_formatted": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(file_mtime)
                    ),
                    "data_url": data_url,
                    "encoded_content": encoded_content,
                }
            else:
                # Non-image files
                result = {
                    "success": True,
                    "file_path": file_path,
                    "file_size": file_size,
                    "file_size_formatted": f"{file_size / 1024:.1f} KB",
                    "file_name": file_name,
                    "content_type": content_type,
                    "timestamp": file_mtime,
                    "timestamp_formatted": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(file_mtime)
                    ),
                    "encoded_content": encoded_content,
                }
        else:
            # Try to decode as text if it looks like a text file
            if content_type.startswith(("text/", "application/json")):
                try:
                    text_content = file_content.decode("utf-8")
                    
                    # Prepare result with text content
                    result = {
                        "success": True,
                        "file_path": file_path,
                        "file_size": file_size,
                        "file_size_formatted": f"{file_size / 1024:.1f} KB",
                        "file_name": file_name,
                        "content_type": content_type,
                        "timestamp": file_mtime,
                        "timestamp_formatted": time.strftime(
                            "%Y-%m-%d %H:%M:%S", time.localtime(file_mtime)
                        ),
                        "content": text_content,
                    }
                except UnicodeDecodeError:
                    # Not valid UTF-8, treat as binary
                    result = {
                        "success": True,
                        "file_path": file_path,
                        "file_size": file_size,
                        "file_size_formatted": f"{file_size / 1024:.1f} KB",
                        "file_name": file_name,
                        "content_type": content_type,
                        "timestamp": file_mtime,
                        "timestamp_formatted": time.strftime(
                            "%Y-%m-%d %H:%M:%S", time.localtime(file_mtime)
                        ),
                        "is_binary": True,
                        "encoded_content": base64.b64encode(file_content).decode("utf-8"),
                    }
            else:
                # Binary file
                result = {
                    "success": True,
                    "file_path": file_path,
                    "file_size": file_size,
                    "file_size_formatted": f"{file_size / 1024:.1f} KB",
                    "file_name": file_name,
                    "content_type": content_type,
                    "timestamp": file_mtime,
                    "timestamp_formatted": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(file_mtime)
                    ),
                    "is_binary": True,
                    "encoded_content": base64.b64encode(file_content).decode("utf-8"),
                }
        
        log(f"Fetched file: {file_path} ({result['file_size_formatted']})")
        return result
    
    except Exception as e:
        log_error(f"Error fetching file: {str(e)}")
        return {
            "error": {
                "message": f"Error fetching file: {str(e)}",
                "code": "READ_ERROR"
            },
            "file_path": file_path,
        }