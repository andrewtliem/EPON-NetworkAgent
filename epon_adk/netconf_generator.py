import time
import random
from datetime import datetime, timezone
from pathlib import Path

# ================== CONFIG ==================
LOG_FILE = Path(__file__).parent / "db" / "epon_netconf_telemetry.log"
INTERVAL_SECONDS = 5        # change this to your desired interval (e.g. 1, 10, 60)
NUM_ONUS = 8                # number of simulated ONUs
OLT_ID = "OLT-01"
# ============================================

# Keep simple state per ONU so values drift realistically
onu_state = {
    onu_id: {
        "rx_power": -23.0 + random.uniform(-2, 2),   # dBm
        "snr": 22.0 + random.uniform(-3, 3),         # dB
        "temp": 55.0 + random.uniform(-5, 5)         # °C
    }
    for onu_id in range(1, NUM_ONUS + 1)
}

def generate_onu_metrics(onu_id: int) -> dict:
    """Generate one telemetry sample for a given ONU with slight random drift."""
    s = onu_state[onu_id]

    # Smooth drift
    s["rx_power"] += random.uniform(-0.2, 0.2)
    s["snr"]      += random.uniform(-0.5, 0.5)
    s["temp"]     += random.uniform(-0.2, 0.2)

    # Clamp to reasonable ranges
    s["rx_power"] = max(-30.0, min(-15.0, s["rx_power"]))
    s["snr"]      = max(10.0,  min(30.0, s["snr"]))
    s["temp"]     = max(40.0,  min(80.0, s["temp"]))

    # BER & FEC based on SNR (very rough)
    snr = s["snr"]
    ber_pre = 10 ** (-snr / 5.0)           # just a toy model
    ber_post = ber_pre / 100.0

    # Occasionally create a degradation / anomaly
    qot_degrade = False
    dsp_slow = False
    if random.random() < 0.05:  # 5% chance
        s["rx_power"] -= random.uniform(1, 3)
        s["snr"]      -= random.uniform(2, 5)
        s["temp"]     += random.uniform(1, 3)
        qot_degrade = True
        if random.random() < 0.5:
            dsp_slow = True

    return {
        "olt_id": OLT_ID,
        "onu_id": onu_id,
        "rx_power": round(s["rx_power"], 2),
        "snr": round(s["snr"], 2),
        "ber_pre": f"{ber_pre:.2e}",
        "ber_post": f"{ber_post:.2e}",
        "temperature": round(s["temp"], 1),
        "qot_degrade": qot_degrade,
        "dsp_slow": dsp_slow,
    }

def build_netconf_notification_xml(ts_iso: str, m: dict) -> str:
    """Build a NETCONF-style XML notification string."""
    xml = f"""<notification xmlns="urn:ietf:params:xml:ns:netconf:notification:1.0">
  <eventTime>{ts_iso}</eventTime>
  <onu-telemetry xmlns="urn:vendor:epon:telemetry">
    <olt-id>{m['olt_id']}</olt-id>
    <onu-id>{m['onu_id']}</onu-id>
    <rx-power>{m['rx_power']}</rx-power>           <!-- dBm -->
    <snr>{m['snr']}</snr>                          <!-- dB -->
    <ber-pre-fec>{m['ber_pre']}</ber-pre-fec>
    <ber-post-fec>{m['ber_post']}</ber-post-fec>
    <temperature>{m['temperature']}</temperature>  <!-- Celsius -->
    <alarms>
      <qot-degrade>{"true" if m['qot_degrade'] else "false"}</qot-degrade>
      <dsp-adaptation>{"slow" if m['dsp_slow'] else "normal"}</dsp-adaptation>
    </alarms>
  </onu-telemetry>
</notification>
"""
    return xml

def append_to_log(text: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Read existing content
    if LOG_FILE.exists():
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    else:
        lines = []
    
    # Append new text
    new_lines = text.splitlines(keepends=True)
    new_lines.append("\n") # Add separator
    lines.extend(new_lines)
    
    # Keep only the last 500 lines (approx 10-15 notifications) to prevent unlimited growth
    # Each notification is ~15 lines. 500 lines = ~30 notifications.
    MAX_LINES = 500
    if len(lines) > MAX_LINES:
        lines = lines[-MAX_LINES:]
        
    # Write back
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)

def main():
    print(f"Starting EPON NETCONF telemetry generator.")
    print(f"Writing to: {LOG_FILE}")
    print(f"Interval: {INTERVAL_SECONDS} seconds, ONUs: {NUM_ONUS}")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            for onu_id in range(1, NUM_ONUS + 1):
                metrics = generate_onu_metrics(onu_id)
                xml = build_netconf_notification_xml(ts, metrics)
                append_to_log(xml)
            print(f"[{ts}] wrote telemetry for {NUM_ONUS} ONUs")
            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped by user.")

if __name__ == "__main__":
    main()
