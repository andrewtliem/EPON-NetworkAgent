"""
Background worker that periodically parses telemetry data and caches it.

This pre-processes telemetry data so user requests are instant.
Uses the parsing_agent for consistency with the agent-based architecture.
"""

import asyncio
import json
import time
from pathlib import Path
from threading import Thread
from typing import Optional

from epon_adk.db.netconf_log import get_latest_netconf_records


# Cache configuration
CACHE_DIR = Path(__file__).parent.parent / "cache"
CACHE_FILE = CACHE_DIR / "parsed_telemetry.json"
CACHE_UPDATE_INTERVAL = 60  # seconds (1 minute default)

# Global cache (shared across sessions)
_global_parsed_cache: Optional[dict] = None
_cache_timestamp: Optional[float] = None
_last_processed_record_hash: Optional[str] = None  # Track latest data fingerprint


def get_global_cache() -> Optional[dict]:
    """Get the globally cached parsed data."""
    return _global_parsed_cache


def get_cache_age_seconds() -> Optional[float]:
    """Get the age of the cache in seconds."""
    if _cache_timestamp is None:
        return None
    return time.time() - _cache_timestamp


def compute_data_hash(records: list) -> str:
    """
    Compute a simple hash of the telemetry records to detect changes.
    Uses the first and last record as a fingerprint.
    """
    import hashlib
    if not records:
        return ""
    
    # Use first + last record as fingerprint (lightweight)
    fingerprint = records[0] + records[-1]
    return hashlib.md5(fingerprint.encode()).hexdigest()


def has_new_data(records: list) -> bool:
    """
    Check if the fetched records contain new data compared to last processing.
    
    Returns:
        True if new data detected, False if data unchanged
    """
    global _last_processed_record_hash
    
    current_hash = compute_data_hash(records)
    
    if _last_processed_record_hash is None:
        # First run, consider it new data
        print("🆕 First run - treating as new data")
        _last_processed_record_hash = current_hash
        return True
    
    if current_hash != _last_processed_record_hash:
        print(f"🆕 New data detected (hash changed: {_last_processed_record_hash[:8]} → {current_hash[:8]})")
        _last_processed_record_hash = current_hash
        return True
    else:
        print("⏭️ No new data detected (hash unchanged)")
        return False


def load_cache_from_file() -> Optional[dict]:
    """Load cached data from JSON file."""
    global _global_parsed_cache, _cache_timestamp, _last_processed_record_hash
    
    if not CACHE_FILE.exists():
        return None
    
    try:
        with open(CACHE_FILE, 'r') as f:
            data = json.load(f)
            _global_parsed_cache = data.get("parsed_data")
            _cache_timestamp = data.get("timestamp")
            _last_processed_record_hash = data.get("data_hash")  # Restore hash
            print(f"✅ Loaded cache from file (age: {get_cache_age_seconds():.1f}s)")
            return _global_parsed_cache
    except Exception as e:
        print(f"❌ Failed to load cache file: {e}")
        return None


def save_cache_to_file(parsed_data: dict) -> None:
    """Save parsed data to JSON file for persistence."""
    global _global_parsed_cache, _cache_timestamp
    
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    _global_parsed_cache = parsed_data
    _cache_timestamp = time.time()
    
    cache_obj = {
        "parsed_data": parsed_data,
        "timestamp": _cache_timestamp,
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_cache_timestamp)),
        "data_hash": _last_processed_record_hash  # Save hash for next run
    }
    
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache_obj, f, indent=2)
        print(f"💾 Cache saved to file: {CACHE_FILE}")
    except Exception as e:
        print(f"❌ Failed to save cache file: {e}")


async def fetch_and_parse_with_agent() -> Optional[dict]:
    """
    Fetch raw telemetry and parse it using the parsing_agent.
    Returns the parsed data as a dict.
    """
    try:
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types
        from epon_adk.agents.parsing_agent import parsing_agent
        
        # Fetch raw telemetry (same as root agent does)
        print("📡 Fetching telemetry data...")
        records = get_latest_netconf_records(count=100, onu_id=None)
        
        if not records:
            print("⚠️ No telemetry data available")
            return None
        
        raw_log = "\n".join(records)
        
        # Parse using the parsing_agent
        print("🤖 Parsing with parsing_agent...")
        
        # Create a temporary session for the agent
        session_service = InMemorySessionService()
        session = await session_service.create_session(
            app_name="background_cache_worker",
            user_id="background_worker"
        )
        
        # Create runner for the parsing agent
        runner = Runner(
            app_name="background_cache_worker",
            agent=parsing_agent,
            session_service=session_service,
        )
        
        # Create the message content
        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=raw_log)],
        )
        
        # Run the agent
        parsed_result = None
        async for event in runner.run_async(
            user_id=session.user_id,
            session_id=session.id,
            new_message=content
        ):
            # Check for tool results (parsing_agent calls parse_telemetry_log)
            func_responses = event.get_function_responses()
            if func_responses:
                for fr in func_responses:
                    print(f"🔍 Debug: Got function response from {fr.name}")
                    print(f"🔍 Debug: Response type: {type(fr.response)}")
                    print(f"🔍 Debug: Response preview: {str(fr.response)[:200]}")
                    
                    if fr.name == "parse_telemetry_log":
                        # The response might be a dict or a JSON string
                        if isinstance(fr.response, dict):
                            parsed_result = fr.response
                            print(f"✅ Got parsed result from tool (dict): {fr.name}")
                        elif isinstance(fr.response, str):
                            try:
                                parsed_result = json.loads(fr.response)
                                print(f"✅ Got parsed result from tool (JSON string): {fr.name}")
                            except json.JSONDecodeError as e:
                                print(f"⚠️ Failed to parse JSON from tool response: {e}")
                                print(f"   Response was: {fr.response[:500]}")
                        else:
                            # Direct assignment if it's already parsed
                            parsed_result = fr.response
                            print(f"✅ Got parsed result from tool (other type): {fr.name}")
            
            # Also check final response as fallback
            if event.is_final_response() and parsed_result is None:
                if event.content and event.content.parts:
                    # Try to extract from text parts
                    for part in event.content.parts:
                        if part.text:
                            try:
                                parsed_result = json.loads(part.text)
                                print("✅ Got parsed result from final text")
                                break
                            except json.JSONDecodeError:
                                # Text is not JSON, skip
                                continue
        
        if parsed_result:
            print(f"✅ Parsed data for {len(parsed_result)} ONUs")
            return parsed_result
        else:
            print("⚠️ Parsing agent returned no data")
            return None
        
    except Exception as e:
        print(f"❌ Error in fetch_and_parse_with_agent: {e}")
        import traceback
        traceback.print_exc()
        return None


def update_cache():
    """Main cache update function - fetches, checks for changes, parses if needed, and saves."""
    print("\n" + "="*60)
    print(f"🔄 Background cache update starting...")
    print("="*60)
    
    # Step 1: Fetch raw telemetry records (lightweight check)
    try:
        print("📡 Fetching telemetry data for change detection...")
        records = get_latest_netconf_records(count=100, onu_id=None)
        
        if not records:
            print("⚠️ No telemetry data available")
            print("="*60 + "\n")
            return
        
        # Step 2: Check if data has changed
        if not has_new_data(records):
            print("✅ Cache is up-to-date, skipping parsing")
            print("="*60 + "\n")
            return
        
        # Step 3: Data changed - proceed with parsing
        print("🤖 New data found - parsing with agent...")
        
    except Exception as e:
        print(f"❌ Error checking for new data: {e}")
        print("="*60 + "\n")
        return
    
    # Step 4: Run async parsing (only if data changed)
    parsed_data = asyncio.run(fetch_and_parse_with_agent())
    
    if parsed_data:
        save_cache_to_file(parsed_data)
        print(f"✅ Cache updated successfully with new data")
    else:
        print(f"⚠️ Cache update failed - parsing returned no data")
    
    print("="*60 + "\n")



def cache_worker_loop(interval_seconds: int = CACHE_UPDATE_INTERVAL):
    """
    Background worker loop that updates cache periodically.
    
    Args:
        interval_seconds: How often to update the cache (default: 60s)
    """
    print(f"🚀 Starting background cache worker (interval: {interval_seconds}s)")
    
    # Initial cache update on startup
    update_cache()
    
    while True:
        try:
            time.sleep(interval_seconds)
            update_cache()
        except KeyboardInterrupt:
            print("⏹️ Background worker stopped by user")
            break
        except Exception as e:
            print(f"❌ Error in background worker: {e}")
            import traceback
            traceback.print_exc()
            # Continue running even if one update fails
            time.sleep(interval_seconds)


def start_background_worker(interval_seconds: int = CACHE_UPDATE_INTERVAL) -> Thread:
    """
    Start the background cache worker in a separate thread.
    
    Args:
        interval_seconds: Update interval in seconds
        
    Returns:
        The Thread object (for monitoring/stopping if needed)
    """
    # Try to load existing cache from file on startup
    load_cache_from_file()
    
    # Start background thread
    worker_thread = Thread(
        target=cache_worker_loop,
        args=(interval_seconds,),
        daemon=True,  # Thread dies when main process dies
        name="TelemetryCacheWorker"
    )
    worker_thread.start()
    
    print(f"✅ Background cache worker started (thread: {worker_thread.name})")
    return worker_thread


if __name__ == "__main__":
    # For testing - run directly
    print("Running cache worker in standalone mode...")
    cache_worker_loop(interval_seconds=30)  # Update every 30s for testing
