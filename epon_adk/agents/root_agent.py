from typing import Optional
from google.adk.agents import LlmAgent
from google.adk.tools import ToolContext
from epon_adk.utils.logging_agent_tool import LoggingAgentTool
from epon_adk.db.netconf_log import get_single_netconf_record, get_latest_netconf_records

from .parsing_agent import parsing_agent
from .compliance_agent import compliance_agent
from .reflection_agent import reflection_agent
from .data_analysis_agent import data_analysis_agent


def get_cached_telemetry_data(tool_context: ToolContext) -> str:
    """
    Check if we have recently parsed telemetry data.
    
    Checks two sources (in order):
    1. Global background cache (updated every N minutes automatically)
    2. Session-specific cache (updated during this session)
    
    Returns:
        JSON string of cached parsed data if available, or message indicating no cache.
    """
    import json
    from epon_adk.background import get_global_cache, get_cache_age_seconds
    
    # First, try global background cache
    global_cache = get_global_cache()
    if global_cache:
        cache_age = get_cache_age_seconds()
        return (
            f"Cached data available from background worker "
            f"(age: {cache_age:.0f}s, use this instead of re-fetching):\n"
            f"{json.dumps(global_cache)}"
        )
    
    # Second, try session-specific cache
    session_cache = tool_context.state.get("parsed_telemetry_data")
    if session_cache:
        return f"Cached data available from session (use this instead of re-fetching):\n{session_cache}"
    
    return "No cached data. You need to fetch and parse fresh telemetry."


def store_parsed_telemetry(parsed_data: str, tool_context: ToolContext) -> str:
    """
    Store parsed telemetry data in session state for reuse in follow-up questions.
    
    Args:
        parsed_data: JSON string of parsed telemetry data to cache
        
    Returns:
        Confirmation message
    """
    tool_context.state["parsed_telemetry_data"] = parsed_data
    return "Parsed data cached in session for reuse."


def get_netconf_telemetry(onu_id: Optional[str] = None) -> str:
    """
    Retrieve the latest raw NETCONF telemetry logs.
    
    Args:
        onu_id: Optional ONU ID to filter by (e.g., "1", "2"). 
                If provided, returns logs only for that ONU.
                If None, returns the last 50 log entries for all ONUs.
        
    Returns:
        Raw NETCONF XML string containing multiple notifications.
    """
    # If ONU ID is specific, we still want history, so let's get enough records
    count = 20 if onu_id else 100
    
    records = get_latest_netconf_records(count=count, onu_id=onu_id)
    
    if records:
        return "\n".join(records)
    else:
        return "No telemetry data available"


root_agent = LlmAgent(
    name="root_agent",
    model="gemini-2.5-flash",
    description="Root orchestrator for EPON monitoring and troubleshooting.",
    instruction=(
        "You are the Root Orchestrator Agent for an EPON network monitoring system.\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️  CRITICAL WORKFLOW - READ CAREFULLY ⚠️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "STEP 1: CHECK CACHE (MANDATORY)\n"
        "═══════════════════════════════\n"
        "ALWAYS start by calling 'get_cached_telemetry_data()'.\n"
        "This returns EITHER:\n"
        "  A) 'Cached data available...' + JSON data\n"
        "  B) 'No cached data'\n\n"
        
        "STEP 2: CONDITIONAL LOGIC\n"
        "═══════════════════════════════\n"
        "IF you received 'Cached data available':\n"
        "  → The JSON is ALREADY PARSED\n"
        "  → SKIP fetching (DO NOT call get_netconf_telemetry)\n"
        "  → SKIP parsing (DO NOT call parsing_agent)\n"
        "  → GO DIRECTLY to Step 3\n\n"
        
        "IF you received 'No cached data':\n"
        "  → THEN and ONLY THEN:\n"
        "    1. Call 'get_netconf_telemetry' to get raw XML\n"
        "    2. Call 'parsing_agent' to parse it\n"
        "    3. Call 'store_parsed_telemetry' to cache the result\n"
        "    4. Proceed to Step 3\n\n"
        
        "STEP 3: EXTRACT LATEST DATA\n"
        "═══════════════════════════════\n"
        "⚠️ CRITICAL: The cached JSON contains HISTORICAL data (up to 5 records per ONU).\n"
        "For CURRENT STATUS checks:\n"
        "  → Extract ONLY the LAST record from each ONU's array\n"
        "  → Example: If ONU '2' has [rec1, rec2, rec3, rec4, rec5]\n"
        "             USE ONLY rec5 (the latest/most recent)\n"
        "  → This represents the CURRENT state, not historical issues\n\n"
        
        "For HISTORICAL ANALYSIS (trends, charts):\n"
        "  → Use ALL records from the array\n"
        "  → Only when user explicitly asks for history/trends\n\n"
        
        "STEP 4: ANALYSIS\n"
        "═══════════════════════════════\n"
        "With the LATEST record(s):\n"
        "  - For HEALTH/STATUS: Call 'compliance_agent' with LATEST only → 'reflection_agent'\n"
        "  - For CHARTS/GRAPHS: Call 'data_analysis_agent' with historical data\n\n"
        
        "STEP 5: USER RESPONSE\\n"
        "═══════════════════════════════\\n"
        "⚠️⚠️⚠️ ABSOLUTELY CRITICAL ⚠️⚠️⚠️\\n"
        "After calling compliance_agent and reflection_agent:\\n"
        "  → You will receive JSON output from verified_analysis\\n"
        "  → DO NOT RETURN THIS JSON TO THE USER\\n"
        "  → YOU MUST SYNTHESIZE A FINAL RESPONSE\\n\\n"
        
        "Your final response to the user MUST:\\n"
        "  1. Be in NATURAL LANGUAGE (plain English)\\n"
        "  2. Summarize the analysis results\\n"
        "  3. Highlight key findings (status, severity, issues)\\n"
        "  4. List actionable recommendations\\n"
        "  5. Use **bold** for warnings/severity\\n"
        "  6. Use bullet points for clarity\\n"
        "  7. Include context and explanations\\n\\n"
        
        "Example Synthesis:\\n"
        "Instead of: ```json {verified_analysis: {...}} ```\\n"
        "Say: 'Based on the analysis, **ONU 1 is experiencing a MINOR issue** \\n"
        "with slightly elevated Pre-FEC BER. This requires monitoring but is \\n"
        "not critical. Recommended actions: \\n"
        "- Monitor BER trend over time\\n"
        "- Continue monitoring link quality trends\\n"
        "The issue is manageable with proper observation.'\\n\\n"
        
        "For charts: Include image as ![Chart](path)\\n"
        "For normal status: Explicitly state 'Network is healthy'\\n"
        "For issues: Clearly explain severity, causes, and actions\\n\\n"
        
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\\n"
        "⛔ FORBIDDEN ACTIONS ⛔\\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\\n"
        "- DO NOT fetch telemetry if cache exists\\n"
        "- DO NOT call parsing_agent if cache exists\\n"
        "- ❌❌❌ DO NOT OUTPUT RAW JSON TO USERS ❌❌❌\\n"
        "- ❌❌❌ DO NOT RETURN verified_analysis DIRECTLY ❌❌❌\\n"
        "- ❌❌❌ DO NOT RETURN compliance_analysis DIRECTLY ❌❌❌\\n"
        "- DO NOT skip checking cache first\\n"
        "- DO NOT analyze historical data for current status\\n"
        "- DO NOT send all 5 records to compliance_agent\\n\\n"

        
        "EXAMPLE CORRECT FLOW:\n"
        "User asks: 'What is ONU 2 status?'\n"
        "1. ✓ Call get_cached_telemetry_data()\n"
        "2. ✓ See cached JSON: {'2': [rec1, rec2, rec3, rec4, rec5]}\n"
        "3. ✓ Extract ONLY rec5 (latest) from ONU '2'\n"
        "4. ✓ Call compliance_agent with rec5 only\n"
        "5. ✓ Call reflection_agent\n"
        "6. ✓ Return answer based on CURRENT state (rec5)\n\n"
        
        "EXAMPLE HISTORICAL QUERY:\n"
        "User asks: 'Show me ONU 2 trend over time'\n"
        "1. ✓ Call get_cached_telemetry_data()\n"
        "2. ✓ See cached JSON: {'2': [rec1, rec2, rec3, rec4, rec5]}\n"
        "3. ✓ Use ALL 5 records for trend analysis\n"
        "4. ✓ Call data_analysis_agent with all 5 records\n"
        "5. ✓ Return chart showing trend\n"
    ),
    tools=[
        get_cached_telemetry_data,
        store_parsed_telemetry,
        get_netconf_telemetry,
        LoggingAgentTool(parsing_agent),
        LoggingAgentTool(compliance_agent),
        LoggingAgentTool(reflection_agent),
        LoggingAgentTool(data_analysis_agent),
    ],
    sub_agents=[parsing_agent, compliance_agent, reflection_agent, data_analysis_agent],
)
