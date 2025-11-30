from contextvars import ContextVar
from typing import List, Dict, Any
from datetime import datetime

# Context variable to hold the logs for the current request
# We initialize it with None, and set it to a new list at the start of each request
_request_logs: ContextVar[List[Dict[str, Any]]] = ContextVar('request_logs', default=None)

def init_logs():
    """Initialize a new log list for the current context."""
    _request_logs.set([])

def get_logs() -> List[Dict[str, Any]]:
    """Get the logs for the current context."""
    logs = _request_logs.get()
    if logs is None:
        return []
    return logs

def log_adk_event(event):
    """Log an ADK event to the current context."""
    logs = _request_logs.get()
    if logs is None:
        return

    # Logic extracted from app.py to format the event
    log_entry = {
        "author": event.author,
        "timestamp": event.timestamp,
        "type": "text",
        "content": ""
    }
    
    # Check for function calls
    func_calls = event.get_function_calls()
    if func_calls:
        log_entry["type"] = "tool_call"
        calls = []
        for fc in func_calls:
            calls.append(f"{fc.name}({fc.args})")
        log_entry["content"] = "; ".join(calls)
        logs.append(log_entry)
        return

    # Check for function responses
    func_resps = event.get_function_responses()
    if func_resps:
        log_entry["type"] = "tool_result"
        resps = []
        for fr in func_resps:
            resps.append(f"Result from {fr.name}")
        log_entry["content"] = "; ".join(resps)
        logs.append(log_entry)
        return

    # Regular text content
    if event.content and event.content.parts:
        text_parts = []
        for part in event.content.parts:
            if part.text:
                text_parts.append(part.text)
        
        if text_parts:
            log_entry["content"] = "\n".join(text_parts)
            logs.append(log_entry)
