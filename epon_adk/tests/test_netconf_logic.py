"""
Simple test to verify NETCONF parsing and compliance checking logic.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.parsing_agent import parse_telemetry_log
from agents.compliance_agent import check_ieee_8023_compliance


def test_parsing():
    """Test NETCONF XML parsing with batch data."""
    print("Testing NETCONF Batch Parsing...")
    
    # Create a batch with 2 records for ONU-2
    sample_xml = """<notification xmlns="urn:ietf:params:xml:ns:netconf:notification:1.0">
  <eventTime>2025-11-24T10:00:00.000+00:00</eventTime>
  <onu-telemetry xmlns="urn:vendor:epon:telemetry">
    <olt-id>OLT-01</olt-id>
    <onu-id>2</onu-id>
    <rx-power>-23.5</rx-power>
    <snr>22.0</snr>
    <ber-pre-fec>1.2e-05</ber-pre-fec>
    <ber-post-fec>1.2e-07</ber-post-fec>
    <temperature>55.0</temperature>
    <alarms>
      <qot-degrade>false</qot-degrade>
      <dsp-adaptation>normal</dsp-adaptation>
    </alarms>
  </onu-telemetry>
</notification>
<notification xmlns="urn:ietf:params:xml:ns:netconf:notification:1.0">
  <eventTime>2025-11-24T10:00:05.000+00:00</eventTime>
  <onu-telemetry xmlns="urn:vendor:epon:telemetry">
    <olt-id>OLT-01</olt-id>
    <onu-id>2</onu-id>
    <rx-power>-23.6</rx-power>
    <snr>21.9</snr>
    <ber-pre-fec>1.3e-05</ber-pre-fec>
    <ber-post-fec>1.3e-07</ber-post-fec>
    <temperature>55.1</temperature>
    <alarms>
      <qot-degrade>false</qot-degrade>
      <dsp-adaptation>normal</dsp-adaptation>
    </alarms>
  </onu-telemetry>
</notification>"""
    
    result = parse_telemetry_log(sample_xml)
    
    assert "2" in result
    assert len(result["2"]) == 2
    
    # Check latest record (last in list)
    latest = result["2"][-1]
    assert latest["qot"]["rx_power_dBm"] == -23.6
    
    print("  ✓ Batch parsing: OK")


def test_compliance_normal():
    """Test compliance check for normal signal."""
    print("\nTesting Compliance (Normal Signal)...")
    
    event = {
        "timestamp": "2025-11-24T10:00:00Z",
        "olt_id": "OLT-01",
        "onu_id": "2",
        "qot": {
            "rx_power_dBm": -23.5,
            "snr_dB": 22.0,
            "ber_pre_fec": 1.2e-09,
            "ber_post_fec": 1.2e-11,
            "temperature": 55.0
        },
        "status": {
            "qot_degrade": False,
            "dsp_adaptation": "normal"
        }
    }
    
    result = check_ieee_8023_compliance(event)
    
    assert result["severity"] == "info"
    assert "No abnormal conditions detected" in result["probable_causes"][0]
    
    print("  ✓ Normal signal compliance: OK")


def test_compliance_degraded():
    """Test compliance check for degraded signal."""
    print("\nTesting Compliance (Degraded Signal)...")
    
    event = {
        "timestamp": "2025-11-24T10:00:00Z",
        "olt_id": "OLT-01",
        "onu_id": "3",
        "qot": {
            "rx_power_dBm": -29.5,
            "snr_dB": 12.0,
            "ber_pre_fec": 5.2e-05,
            "ber_post_fec": 5.2e-07,
            "temperature": 78.0
        },
        "status": {
            "qot_degrade": True,
            "dsp_adaptation": "slow"
        }
    }
    
    result = check_ieee_8023_compliance(event)
    
    print(f"  Debug - Severity: {result['severity']}")
    print(f"  Debug - Layer: {result['likely_layer']}")
    print(f"  Debug - Causes: {result['probable_causes']}")
    
    assert result["likely_layer"] == "PHY"
    # Updated assertion to match new message "QoT degradation reported by ONU."
    assert "QoT degradation" in result["probable_causes"][0]
    assert len(result["suggested_actions"]) > 0
    
    print("  ✓ Degraded signal compliance: OK")


if __name__ == "__main__":
    try:
        test_parsing()
        test_compliance_normal()
        test_compliance_degraded()
        print("\n✅ ALL TESTS PASSED")
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
