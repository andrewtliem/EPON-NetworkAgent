from pathlib import Path
from typing import Optional, List
import xml.etree.ElementTree as ET

LOG_FILE = Path(__file__).parent / "epon_netconf_telemetry.log"


def get_latest_netconf_records(count: int = 10, onu_id: Optional[str] = None) -> List[str]:
    """
    Read the most recent NETCONF records from the telemetry log.
    
    Args:
        count: Number of records to return (default 10)
        onu_id: Optional ONU ID to filter by (e.g., "1", "2")
        
    Returns:
        List of raw NETCONF XML strings
    """
    if not LOG_FILE.exists():
        return []
    
    # Read all records (each notification is separated by newlines)
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Split by notification tags
    records = []
    current_record = []
    
    for line in content.split("\n"):
        if line.strip().startswith("<notification"):
            current_record = [line]
        elif line.strip().startswith("</notification>"):
            current_record.append(line)
            records.append("\n".join(current_record))
            current_record = []
        elif current_record:
            current_record.append(line)
    
    # Filter by ONU if specified
    if onu_id:
        filtered = []
        for record in records:
            try:
                root = ET.fromstring(record)
                # Remove namespace
                for elem in root.iter():
                    if "}" in elem.tag:
                        elem.tag = elem.tag.split("}", 1)[1]
                onu_elem = root.find(".//onu-id")
                if onu_elem is not None and str(onu_elem.text) == str(onu_id):
                    filtered.append(record)
            except ET.ParseError:
                continue
        return filtered[-count:] if filtered else []
    
    # Return the most recent ones
    return records[-count:] if records else []


def get_single_netconf_record(onu_id: str) -> Optional[str]:
    """
    Get the most recent NETCONF record for a specific ONU.
    
    Args:
        onu_id: ONU ID to look up (e.g., "1", "2")
        
    Returns:
        Raw NETCONF XML string or None
    """
    records = get_latest_netconf_records(count=1, onu_id=onu_id)
    return records[0] if records else None


def clear_log():
    """Clear the telemetry log file."""
    if LOG_FILE.exists():
        LOG_FILE.unlink()
    print(f"Cleared telemetry log: {LOG_FILE}")


def inject_degraded_signal(onu_id: int):
    """
    Inject a degraded signal event for a specific ONU.
    
    This is used for testing/simulation purposes.
    """
    from datetime import datetime, timezone
    
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    
    xml = f"""<notification xmlns="urn:ietf:params:xml:ns:netconf:notification:1.0">
  <eventTime>{ts}</eventTime>
  <onu-telemetry xmlns="urn:vendor:epon:telemetry">
    <olt-id>OLT-01</olt-id>
    <onu-id>{onu_id}</onu-id>
    <rx-power>-29.5</rx-power>           <!-- dBm - degraded -->
    <snr>12.3</snr>                      <!-- dB - low -->
    <ber-pre-fec>5.2e-05</ber-pre-fec>   <!-- high -->
    <ber-post-fec>5.2e-07</ber-post-fec>
    <temperature>78.2</temperature>      <!-- Celsius - high -->
    <alarms>
      <qot-degrade>true</qot-degrade>
      <dsp-adaptation>slow</dsp-adaptation>
    </alarms>
  </onu-telemetry>
</notification>
"""
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(xml)
        f.write("\n")
    
    print(f"Injected degraded signal event for ONU-{onu_id}")


def inject_normal_signal(onu_id: int):
    """
    Inject a normal/healthy signal event for a specific ONU.
    """
    from datetime import datetime, timezone
    
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    
    xml = f"""<notification xmlns="urn:ietf:params:xml:ns:netconf:notification:1.0">
  <eventTime>{ts}</eventTime>
  <onu-telemetry xmlns="urn:vendor:epon:telemetry">
    <olt-id>OLT-01</olt-id>
    <onu-id>{onu_id}</onu-id>
    <rx-power>-22.0</rx-power>           <!-- dBm - good -->
    <snr>24.5</snr>                      <!-- dB - good -->
    <ber-pre-fec>2.1e-09</ber-pre-fec>   <!-- low -->
    <ber-post-fec>2.1e-11</ber-post-fec>
    <temperature>52.0</temperature>      <!-- Celsius - normal -->
    <alarms>
      <qot-degrade>false</qot-degrade>
      <dsp-adaptation>normal</dsp-adaptation>
    </alarms>
  </onu-telemetry>
</notification>
"""
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(xml)
        f.write("\n")
    
    print(f"Injected normal signal event for ONU-{onu_id}")
