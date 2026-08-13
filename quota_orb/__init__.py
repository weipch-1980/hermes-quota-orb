"""Provider-neutral read-only quota semantics for Quota Orb."""

from .core import normalize_snapshot, unavailable_snapshot

__all__ = ["normalize_snapshot", "unavailable_snapshot"]
__version__ = "0.5.1"
