"""
Enhanced extract_agent_thinking function with support for nova_instance.

This is a replacement for the existing function in utils.py.
"""

def extract_agent_thinking(
    result: Any, 
    nova_instance: Optional[Any] = None,  # Add nova_instance parameter
    html_path_to_parse: Optional[str] = None,
    instruction: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Extract agent thinking steps from NovaAct results.
    
    Args:
        result: NovaAct result object
        nova_instance: The NovaAct instance (optional)
        html_path_to_parse: Path to HTML log file to parse
        instruction: Original instruction for context
        
    Returns:
        tuple: A tuple containing a list of agent messages and debug info
    """
    agent_messages_structured = []
    debug_info = {}
    
    def _clean_thought(t: str) -> str:
        """Clean up raw thinking text by handling escapes and whitespace."""
        return t.strip().replace("\\n", "\n").replace('\\"', '"')
    
    log_debug(f"[extract_agent_thinking] Starting with result: {type(result)}, nova_instance: {type(nova_instance) if nova_instance else None}")
    
    # Method 1: Direct fields from result object
    if result:
        log_debug("[extract_agent_thinking] Checking result object attributes")
        # Check result.metadata.thinking
        if hasattr(result, "metadata") and hasattr(result.metadata, "thinking") and result.metadata.thinking:
            log_debug("[extract_agent_thinking] Found result.metadata.thinking")
            thinking_items = result.metadata.thinking
            if isinstance(thinking_items, list):
                for i, t in enumerate(thinking_items):
                    cleaned = _clean_thought(str(t))
                    if cleaned:
                        agent_messages_structured.append({
                            "role": "agent_thinking",
                            "step": i + 1,
                            "content": cleaned,
                            "source": "result_metadata_thinking",
                        })
            elif thinking_items:  # Handle single item
                cleaned = _clean_thought(str(thinking_items))
                if cleaned:
                    agent_messages_structured.append({
                        "role": "agent_thinking",
                        "step": 1,
                        "content": cleaned,
                        "source": "result_metadata_thinking",
                    })
        
        # Check result.thinking
        if hasattr(result, "thinking") and result.thinking:
            log_debug("[extract_agent_thinking] Found result.thinking")
            thinking_items = result.thinking
            if isinstance(thinking_items, list):
                for i, t in enumerate(thinking_items):
                    cleaned = _clean_thought(str(t))
                    if cleaned:
                        agent_messages_structured.append({
                            "role": "agent_thinking",
                            "step": i + 1,
                            "content": cleaned,
                            "source": "result_thinking",
                        })
            elif thinking_items:  # Handle single item
                cleaned = _clean_thought(str(thinking_items))
                if cleaned:
                    agent_messages_structured.append({
                        "role": "agent_thinking",
                        "step": 1,
                        "content": cleaned,
                        "source": "result_thinking",
                    })
        
        # Check result.thoughts
        if hasattr(result, "thoughts") and result.thoughts:
            log_debug("[extract_agent_thinking] Found result.thoughts")
            thoughts_items = result.thoughts
            if isinstance(thoughts_items, list):
                for i, t in enumerate(thoughts_items):
                    cleaned = _clean_thought(str(t))
                    if cleaned:
                        agent_messages_structured.append({
                            "role": "agent_thinking",
                            "step": i + 1,
                            "content": cleaned,
                            "source": "result_thoughts",
                        })
            elif thoughts_items:  # Handle single item
                cleaned = _clean_thought(str(thoughts_items))
                if cleaned:
                    agent_messages_structured.append({
                        "role": "agent_thinking",
                        "step": 1,
                        "content": cleaned,
                        "source": "result_thoughts",
                    })
    
    # Method 2: Raw logs from nova_instance.get_logs() if available
    if nova_instance and hasattr(nova_instance, "get_logs") and callable(getattr(nova_instance, "get_logs")):
        try:
            log_debug("[extract_agent_thinking] Attempting to get logs from nova_instance.get_logs()")
            raw_logs = nova_instance.get_logs()
            
            if raw_logs:
                log_debug(f"[extract_agent_thinking] Got logs of type: {type(raw_logs)}")
                log_lines = []
                
                # Handle different return types from get_logs()
                if isinstance(raw_logs, str):
                    log_lines = raw_logs.splitlines()
                elif isinstance(raw_logs, list):
                    log_lines = raw_logs
                
                # Process log lines looking for thinking patterns
                thinking_count = 0
                for line in log_lines:
                    if not line:
                        continue
                        
                    # Patterns for think() calls, including various quote styles
                    # Standard think("...") pattern
                    think_match = re.search(r'think\s*\(\s*["\']([^"\']+)["\']', str(line))
                    if not think_match:
                        # Try multiline pattern with triple quotes or backticks
                        think_match = re.search(r'think\s*\(\s*(?:"""|\'\'\')(.*?)(?:"""|\'\'\')(?:\s*\))?', str(line), re.DOTALL)
                    if not think_match:
                        # Try think(`...`) pattern with backticks
                        think_match = re.search(r'think\s*\(\s*`(.*?)`\s*\)', str(line), re.DOTALL)
                    
                    if think_match:
                        thinking_content = think_match.group(1)
                        cleaned = _clean_thought(thinking_content)
                        if cleaned:
                            thinking_count += 1
                            agent_messages_structured.append({
                                "role": "agent_thinking",
                                "step": thinking_count,
                                "content": cleaned,
                                "source": "nova_raw_logs",
                            })
                
                if thinking_count > 0:
                    log_debug(f"[extract_agent_thinking] Found {thinking_count} thinking steps in raw logs")
                    debug_info["raw_logs_thinking_count"] = thinking_count
        except Exception as e:
            log_error(f"[extract_agent_thinking] Error extracting thinking from raw logs: {str(e)}")
            debug_info["raw_logs_error"] = str(e)
    
    # Method 3: HTML log parsing if available and needed
    if html_path_to_parse and os.path.exists(html_path_to_parse):
        try:
            log_debug(f"[extract_agent_thinking] Parsing HTML log: {html_path_to_parse}")
            with open(html_path_to_parse, "r", encoding="utf-8") as f:
                html_content = f.read()
            
            # Extract messages using regex patterns
            thinking_pattern = r'<div class="message-thinking">(.*?)</div>'
            action_pattern = r'<div class="message-action">(.*?)</div>'
            
            # Find all thinking steps
            thinking_matches = re.findall(thinking_pattern, html_content, re.DOTALL)
            html_thinking_count = 0
            
            for thinking in thinking_matches:
                cleaned = _clean_thought(html.unescape(thinking).strip())
                if cleaned:
                    html_thinking_count += 1
                    # Check if this thinking is already in our list (avoid duplicates)
                    if not any(msg.get("content") == cleaned for msg in agent_messages_structured):
                        agent_messages_structured.append({
                            "role": "agent_thinking",
                            "step": html_thinking_count,
                            "content": cleaned,
                            "source": "html_log",
                        })
            
            # Find all action steps (only if we need them)
            action_matches = re.findall(action_pattern, html_content, re.DOTALL)
            for i, action in enumerate(action_matches):
                cleaned = _clean_thought(html.unescape(action).strip())
                if cleaned:
                    agent_messages_structured.append({
                        "role": "agent_action",
                        "step": i + 1,
                        "content": cleaned,
                        "source": "html_log",
                    })
            
            if html_thinking_count > 0:
                log_debug(f"[extract_agent_thinking] Found {html_thinking_count} thinking steps in HTML log")
                debug_info["html_thinking_count"] = html_thinking_count
        except Exception as e:
            log_error(f"[extract_agent_thinking] Error parsing HTML log: {str(e)}")
            debug_info["html_parse_error"] = str(e)
    
    # Fallback: If no thinking found and result has a response, use it as a fallback
    if not agent_messages_structured and result and hasattr(result, "response"):
        response = result.response
        log_debug("[extract_agent_thinking] No thinking found, checking result.response as fallback")
        
        if response and isinstance(response, str):
            # Check if it looks like actual thinking (not just a simple status)
            if not re.match(r'^\s*(action|task)\s+(executed|complete|finished|done)', response.lower()):
                cleaned = _clean_thought(response)
                if cleaned:
                    agent_messages_structured.append({
                        "role": "agent_thinking",
                        "step": 1,
                        "content": cleaned,
                        "source": "result_response_fallback",
                    })
                    log_debug("[extract_agent_thinking] Using result.response as fallback thinking")
                    debug_info["used_response_fallback"] = True
    
    # Add debug info
    debug_info["message_count"] = len(agent_messages_structured)
    debug_info["sources"] = list(set(msg.get("source") for msg in agent_messages_structured))
    
    # Sort messages by step for a consistent order
    agent_messages_structured.sort(key=lambda x: x.get("step", 0))
    
    log_debug(f"[extract_agent_thinking] Extracted {len(agent_messages_structured)} agent messages")
    return agent_messages_structured, debug_info
