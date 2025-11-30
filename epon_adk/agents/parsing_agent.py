from typing import Dict, Any, List
import re
import xml.etree.ElementTree as ET

from google.adk.agents import LlmAgent

# ---------- Tool: Parse NETCONF / XML-ish raw record ----------

def parse_telemetry_log(raw_log: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Parse a raw NETCONF / SDN monitoring log containing multiple notifications.
    Returns a dictionary grouped by ONU ID, containing the last 5 records for each ONU.

    Args:
        raw_log: Raw text containing multiple <notification>...</notification> blocks.

    Returns:
        Dict[str, List[Dict]]: Keys are ONU IDs (e.g., "1", "2"). 
        Values are lists of parsed event dicts, sorted by timestamp (newest last).
        Only the last 5 events per ONU are retained.
    """
    # Split raw log into individual notification blocks
    # Simple heuristic: split by </notification>
    blocks = raw_log.split("</notification>")
    
    parsed_events = []
    
    for block in blocks:
        if "<notification" not in block:
            continue
            
        # Re-add the closing tag for XML parsing
        full_block = block + "</notification>"
        
        # Clean up leading whitespace/newlines
        start_idx = full_block.find("<notification")
        if start_idx == -1:
            continue
        clean_block = full_block[start_idx:]
        
        # Parse single record (reuse logic)
        event = _parse_single_record(clean_block)
        if event and event.get("onu_id"):
            parsed_events.append(event)

    # Group by ONU ID
    grouped = {}
    for event in parsed_events:
        oid = str(event["onu_id"])
        if oid not in grouped:
            grouped[oid] = []
        grouped[oid].append(event)
        
    # Keep last 5 per ONU
    final_result = {}
    for oid, events in grouped.items():
        # Sort by timestamp if available, otherwise assume log order (which is usually chronological)
        # We'll just take the last 5 from the list since we parsed in order
        final_result[oid] = events[-5:]
        
    return final_result


def _parse_single_record(raw_record: str) -> Dict[str, Any] | None:
    """Helper to parse a single XML notification block."""
    result: Dict[str, Any] = {
        "timestamp": None,
        "olt_id": None,
        "onu_id": None,
        "qot": {},
        "status": {}
    }

    try:
        root = ET.fromstring(raw_record)
        # Remove namespaces
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]

        # Timestamp
        event_time_elem = root.find(".//eventTime")
        if event_time_elem:
            result["timestamp"] = event_time_elem.text

        # IDs
        olt_elem = root.find(".//olt-id")
        onu_elem = root.find(".//onu-id")
        if olt_elem is not None: result["olt_id"] = olt_elem.text
        if onu_elem is not None: result["onu_id"] = str(onu_elem.text)

        # Metrics
        def _to_float(t): return float(t) if t else None
        
        rx = root.find(".//rx-power")
        snr = root.find(".//snr")
        ber_pre = root.find(".//ber-pre-fec")
        ber_post = root.find(".//ber-post-fec")
        temp = root.find(".//temperature")
        
        result["qot"] = {
            "rx_power_dBm": _to_float(rx.text if rx is not None else None),
            "snr_dB": _to_float(snr.text if snr is not None else None),
            "ber_pre_fec": _to_float(ber_pre.text if ber_pre is not None else None),
            "ber_post_fec": _to_float(ber_post.text if ber_post is not None else None),
            "temperature": _to_float(temp.text if temp is not None else None),
        }

        # Status
        qot_deg = root.find(".//qot-degrade")
        dsp = root.find(".//dsp-adaptation")
        
        result["status"] = {
            "qot_degrade": (qot_deg.text.lower() == 'true') if qot_deg is not None and qot_deg.text else None,
            "dsp_adaptation": dsp.text if dsp is not None else None
        }
        
        return result

    except ET.ParseError:
        return None


parsing_agent = LlmAgent(
    name="parsing_agent",
    model="gemini-2.5-flash",
    description=(
        "Parses raw NETCONF / SDN EPON monitoring logs into structured JSON."
    ),
    instruction=(
        "You receive raw NETCONF log data containing multiple notifications.\n"
        "- Call 'parse_telemetry_log' to parse the entire batch.\n"
        "- The tool will automatically group events by ONU and keep the last 5 history entries for each.\n"
        "- Return the structured JSON with the history per ONU."
    ),
    tools=[parse_telemetry_log],
    output_key="parsed_event",
)
