"""Shared dependencies for FastAPI routes.

Provides a StorageManager singleton via lifespan and shared query parameter models.
"""

from __future__ import annotations

from src.storage.manager import StorageManager

# Module-level singleton — initialized during app lifespan
_storage: StorageManager | None = None


async def init_storage() -> StorageManager:
    """Initialize the StorageManager singleton. Called once at startup."""
    global _storage
    _storage = StorageManager()
    await _storage.initialize()
    return _storage


async def shutdown_storage() -> None:
    """Close the StorageManager. Called once at shutdown."""
    global _storage
    if _storage:
        await _storage.close()
        _storage = None


def get_storage() -> StorageManager:
    """FastAPI dependency — returns the initialized StorageManager."""
    assert _storage is not None, "StorageManager not initialized"
    return _storage
