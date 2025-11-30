import asyncio
import os
import uuid
from flask import Flask, render_template, request, jsonify, session
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Import our agent and DB setup
# We need to make sure the root dir is in pythonpath or we use relative imports if running as module
import sys
from pathlib import Path
# Add the project root to sys.path
sys.path.append(str(Path(__file__).parent.parent.parent))
# Add the epon_adk directory to sys.path so 'db' module can be found
sys.path.append(str(Path(__file__).parent.parent))

from epon_adk.agents.root_agent import root_agent
from epon_adk.db import netconf_log
from epon_adk.utils.event_logger import init_logs, get_logs, log_adk_event
from epon_adk.background import start_background_worker, get_global_cache

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')

APP_NAME = "epon_web_app"
USER_ID = "web_user"

# Background cache worker
CACHE_UPDATE_INTERVAL = int(os.environ.get('CACHE_UPDATE_INTERVAL', '60'))  # seconds

# Global runner and session service
runner = None
session_service = None

async def init_runner():
    global runner, session_service
    session_service = InMemorySessionService()
    runner = Runner(
        app_name=APP_NAME,
        agent=root_agent,
        session_service=session_service,
    )
    print("Runner initialized.")

# Start background cache worker on app startup
print(f"🚀 Starting background telemetry cache worker (interval: {CACHE_UPDATE_INTERVAL}s)...")
cache_worker_thread = start_background_worker(interval_seconds=CACHE_UPDATE_INTERVAL)


@app.before_request
async def startup():
    pass

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
async def chat():
    global runner, session_service
    if runner is None:
        await init_runner()

    # Get or create session ID for this browser client
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
        # Create the session in the InMemorySessionService
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=session['session_id'],
        )
        print(f"New session created: {session['session_id']}")
    
    client_session_id = session['session_id']

    # Initialize logs for this request context
    init_logs()

    data = request.json
    user_message = data.get("message", "")

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    content = types.Content(
        role="user",
        parts=[types.Part(text=user_message)],
    )

    response_text = ""
    
    try:
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=client_session_id,
            new_message=content,
        ):
            # Log root agent events
            log_adk_event(event)

            if event.is_final_response():
                if event.content and event.content.parts:
                     response_text = event.content.parts[0].text
    except Exception as e:
        print(f"Error during agent execution: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

    # Retrieve all logs (root + sub-agents)
    logs = get_logs()
    return jsonify({"response": response_text, "logs": logs, "session_id": client_session_id})

@app.route("/inject", methods=["POST"])
def inject():
    data = request.json
    scenario = data.get("scenario")
    onu_id = data.get("onu_id", 2)  # Default to ONU-2
    
    if not scenario:
        return jsonify({"error": "Missing scenario"}), 400
    
    if scenario == "degrade_onu":
        netconf_log.inject_degraded_signal(onu_id)
    elif scenario == "clear_issues":
        netconf_log.inject_normal_signal(onu_id)
    elif scenario == "ddos_attack":
        # For now, we'll reuse degraded signal as a proxy for network issues
        netconf_log.inject_degraded_signal(onu_id)
    else:
        return jsonify({"error": f"Unknown scenario: {scenario}"}), 400
    
    return jsonify({"status": "success", "scenario": scenario, "onu_id": onu_id})

if __name__ == "__main__":
    # In production we might use hypercorn/uvicorn, but for dev flask.run is fine.
    # Flask 2.0+ supports async routes.
    app.run(debug=True, port=8080)
