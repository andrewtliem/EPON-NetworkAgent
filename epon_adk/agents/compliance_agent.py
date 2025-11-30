from typing import Dict, Any, List

from google.adk.agents import LlmAgent


# ---------- Tool: Heuristic IEEE 802.3-style compliance checks ----------

def check_ieee_8023_compliance(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Heuristic EPON QoT / PHY-layer compliance check aligned with general
    IEEE 802.3 optical expectations. NOT a clause-accurate implementation.

    Returns a dict with:
      - severity: 'info' | 'warning' | 'critical'
      - likely_layer: e.g. 'PHY' or 'Unknown'
      - probable_causes: list of human-readable strings
      - suggested_actions: list of operator actions
      - notes: extra context
      - is_abnormal: True if any abnormal condition is present
      - health: 'normal' | 'minor_issue' | 'major_issue'
    """

    qot = event.get("qot", {}) or {}
    status = event.get("status", {}) or {}

    rx = qot.get("rx_power_dBm")
    ber_pre = qot.get("ber_pre_fec")
    ber_post = qot.get("ber_post_fec")
    snr = qot.get("snr_dB")
    temp = qot.get("temperature")
    qot_degrade = status.get("qot_degrade")
    dsp_state = status.get("dsp_adaptation")

    likely_layer = "Unknown"
    severity = "info"
    causes: List[str] = []
    actions: List[str] = []
    notes: List[str] = []

    # Normalize DSP state
    dsp_state_norm = None
    if isinstance(dsp_state, str):
        dsp_state_norm = dsp_state.lower()

    # ------------------------------
    # 1. QoT Degradation Flag
    # ------------------------------
    if qot_degrade is True:
        likely_layer = "PHY"
        severity = "critical"
        causes.append("QoT degradation reported by ONU.")
        actions.extend([
            "Verify fiber continuity and connectors on the PON link.",
            "Measure optical power with OPM or perform OTDR test.",
            "Inspect splitter ports/splices for excessive loss.",
        ])
        notes.append(
            "QoT degrade indicates optical signal margins falling outside "
            "normal operating envelope for EPON PHY optics."
        )

    # ------------------------------
    # 2. Rx Power Window (Optical Budget)
    # ------------------------------
    if rx is not None:
        if rx < -26.5:  # near sensitivity
            if likely_layer == "Unknown":
                likely_layer = "PHY"
            if severity == "info":
                severity = "warning"
            causes.append(f"Low received optical power ({rx:.2f} dBm).")
            actions.append("Check passive plant for excessive insertion loss.")
            notes.append(
                "Receiver input is near sensitivity limit for common EPON ONU optics."
            )

        if rx < -28:  # dangerously low
            if likely_layer == "Unknown":
                likely_layer = "PHY"
            severity = "critical"
            causes.append("Received optical power beyond sensitivity threshold.")
            actions.append("Urgently inspect fiber drop and connectors.")

    # ------------------------------
    # 3. BER Classification
    # ------------------------------
    if ber_pre is not None:
        if ber_pre > 1e-3:
            likely_layer = "PHY"
            severity = "critical"
            causes.append(f"Pre-FEC BER {ber_pre:.2e} extremely high.")
            actions.extend([
                "Perform optical path inspection immediately.",
                "Verify laser launch conditions and ONU optics health.",
            ])
        elif ber_pre > 1e-4:
            if likely_layer == "Unknown":
                likely_layer = "PHY"
            if severity == "info":
                severity = "warning"
            causes.append(f"Pre-FEC BER {ber_pre:.2e} above nominal.")
            actions.append("Check clock recovery / dispersion on long-reach PON.")
        elif ber_pre > 1e-5:
            # Still considered abnormal, but mild
            if likely_layer == "Unknown":
                likely_layer = "PHY"
            if severity == "info":
                severity = "warning"  # promote to warning so it's clearly not normal
            causes.append("Pre-FEC BER slightly elevated.")
            actions.append("Monitor BER trend over time.")

    # ------------------------------
    # 4. SNR Classification
    # ------------------------------
    if snr is not None:
        if snr < 12:
            likely_layer = "PHY"
            severity = "critical"
            causes.append(f"SNR critically low ({snr:.1f} dB).")
            actions.append(
                "Investigate reflections, macro-bends, or noisy transmitters."
            )
        elif snr < 15:
            if severity == "info":
                severity = "warning"
            likely_layer = "PHY"
            causes.append(f"SNR marginal ({snr:.1f} dB).")
            actions.append(
                "Inspect connectors for contamination or micro-bends."
            )

    # ------------------------------
    # 5. High Temperature
    # ------------------------------
    if temp is not None and temp > 75:
        likely_layer = "PHY"
        if severity == "info":
            severity = "warning"
        causes.append(f"High ONU temperature ({temp}°C).")
        actions.append("Check ONU ambient conditions and ventilation.")

    # ------------------------------
    # 6. DSP Adaptation Problems
    # ------------------------------
    if dsp_state_norm in ["slow", "degraded", "tracking"]:
        likely_layer = "PHY"
        if severity == "info":
            severity = "warning"
        causes.append("DSP adaptation struggling (slow/degraded).")
        actions.append("Check for unstable optical power or high dispersion.")
        notes.append(
            "DSP struggling often correlates with low SNR or fluctuating power."
        )

    # ------------------------------
    # 7. If nothing triggered
    # ------------------------------
    if not causes:
        # This is the ONLY fully-normal case
        causes.append("No abnormal conditions detected.")
        actions.append("Continue monitoring.")
        notes.append(
            "Event appears to be within normal IEEE 802.3 EPON operating range."
        )
        is_abnormal = False
    else:
        # Anything that added a cause (other than the above block) is abnormal
        is_abnormal = True
        # Always add monitoring if event is not critical
        if severity in ["info", "warning"]:
            actions.append("Continue monitoring link quality trends.")

    # Map severity + abnormal flag to a simple health state
    if not is_abnormal:
        health = "normal"
    elif severity == "critical":
        health = "major_issue"
    else:
        health = "minor_issue"

    return {
        "timestamp": event.get("timestamp"),
        "olt_id": event.get("olt_id"),
        "onu_id": event.get("onu_id"),
        "likely_layer": likely_layer,
        "severity": severity,
        "probable_causes": causes,
        "suggested_actions": actions,
        "notes": notes,
        "is_abnormal": is_abnormal,
        "health": health,
    }


# ---------- Tool: Vendor knowledge base search ----------

def search_vendor_knowledge_base(query: str) -> str:
    """
    Search online for vendor-specific error codes, hardware bugs, or forum discussions.

    Use this when the compliance check reports abnormal conditions
    (warning/critical, or health != 'normal') OR when the event contains
    vendor-specific error texts, alarm IDs, hex codes, or device/model names.

    Args:
        query: A concise search query string (e.g.,
               "Huawei MA5800 ONU LOS alarm 0x45",
               "Nokia ISAM high pre-FEC BER threshold").

    Returns:
        A short summary of the top search results.
    """
    try:
        from duckduckgo_search import DDGS
        results = DDGS().text(query, max_results=3)
        if not results:
            return "No relevant search results found."

        summary_lines = ["Search Results:"]
        for r in results:
            title = r.get("title", "").strip()
            body = r.get("body", "").strip()
            href = r.get("href", "").strip()
            summary_lines.append(f"- {title}: {body} ({href})")
        return "\n".join(summary_lines)
    except Exception as e:
        return f"Search failed: {str(e)}"


# ---------- LLM Agent: EPON compliance analysis ----------

compliance_agent = LlmAgent(
    name="compliance_agent",
    model="gemini-2.5-flash",
    description=(
        "Analyzes EPON QoT and fault events and suggests actions aligned "
        "with IEEE 802.3 EPON operational practices."
    ),
    instruction=(
        "You receive parsed EPON telemetry events as JSON.\n"
        "\n"
        "TOOL USAGE\n"
        "- ALWAYS call the tool `check_ieee_8023_compliance` first for every event.\n"
        "- After you get the compliance result, decide whether to call "
        "the tool `search_vendor_knowledge_base` as follows:\n"
        "  * You SHOULD call it when severity is 'critical' or health is 'major_issue'.\n"
        "  * You MAY call it when severity is 'warning' or health is 'minor_issue', "
        "    especially if the event or notes contain vendor-specific error codes, "
        "    alarm IDs, hex codes (like 0x..), or device/model names.\n"
        "  * You SHOULD NOT call it when health is 'normal' and the only probable cause is "
        "    'No abnormal conditions detected.'.\n"
        "\n"
        "INTERPRETATION RULES (STRICT)\n"
        "- The fields `severity`, `health`, and `is_abnormal` from `check_ieee_8023_compliance` "
        "are the single source of truth for whether the link is normal or not.\n"
        "- NEVER describe a case as 'normal', 'no issues', or 'no problem' if "
        "`is_abnormal` is True OR `health` is not 'normal'.\n"
        "- If `health` == 'normal' AND `probable_causes` is exactly "
        "['No abnormal conditions detected.'], you MUST explicitly state that the "
        "link is normal.\n"
        "- If `health` == 'minor_issue', explicitly describe it as a MINOR or SOFT issue "
        "that still requires monitoring (not fully normal).\n"
        "- If `health` == 'major_issue' OR `severity` == 'critical', explicitly describe it "
        "as a MAJOR or CRITICAL issue.\n"
        "- DO NOT override, downplay, or reinterpret `severity`, `health`, or `is_abnormal`.\n"
        "\n"
        "VENDOR SEARCH BEHAVIOR\n"
        "- When you call `search_vendor_knowledge_base`, build a short query that includes "
        "the vendor/model name (if present) and the key symptom(s) from the compliance result "
        "or event (e.g., high BER, LOS, specific error code).\n"
        "- Use the search results only to add context (e.g., 'this pattern matches a known "
        "firmware issue') and more concrete operator actions, but DO NOT contradict the "
        "tool's severity or health.\n"
        "\n"
        "OUTPUT FORMAT\n"
        "- Base your entire answer on the outputs of the tools you called.\n"
        "- You may add brief engineering explanations, but DO NOT invent IEEE clause "
        "numbers or normative standard text.\n"
        "- The final answer MUST be a single JSON object under key 'compliance_analysis'.\n"
        "- Include for each ONU/event: severity, health, is_abnormal, probable causes, "
        "suggested actions, and a short operator-facing summary.\n"
    ),
    tools=[check_ieee_8023_compliance, search_vendor_knowledge_base],
    output_key="compliance_analysis",
)
