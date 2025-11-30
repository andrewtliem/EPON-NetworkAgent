"""Background workers for EPON ADK."""

from .telemetry_cache_worker import (
    start_background_worker,
    get_global_cache,
    get_cache_age_seconds,
    update_cache,
)

__all__ = [
    "start_background_worker",
    "get_global_cache",
    "get_cache_age_seconds",
    "update_cache",
]
