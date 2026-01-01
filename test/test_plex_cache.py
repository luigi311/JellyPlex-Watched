from datetime import datetime, timezone
import json
import tempfile
import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
sys.path.append(parent)

from src.plex_cache import PlexCache, resolve_viewed_date


def test_resolve_viewed_date_completed_uses_state():
    last_viewed_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    state_entry = {
        "completed": True,
        "time": None,
        "source_viewed_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
    }
    result = resolve_viewed_date(last_viewed_at, True, None, state_entry)
    assert result == datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_resolve_viewed_date_partial_uses_state():
    last_viewed_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    state_entry = {
        "completed": False,
        "time": 1000,
        "source_viewed_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
    }
    result = resolve_viewed_date(last_viewed_at, False, 1000, state_entry)
    assert result == datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_resolve_viewed_date_partial_normalizes_time():
    last_viewed_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    state_entry = {
        "completed": False,
        "time": None,
        "source_viewed_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
    }
    result = resolve_viewed_date(last_viewed_at, False, 0, state_entry)
    assert result == datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_resolve_viewed_date_uses_plex_when_state_mismatch():
    last_viewed_at = datetime(2026, 1, 1, 12, 0, 0)
    state_entry = {
        "completed": False,
        "time": 2000,
        "source_viewed_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
    }
    result = resolve_viewed_date(last_viewed_at, False, 1000, state_entry)
    assert result == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_plex_cache_user_key_isolated():
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        tmp.write("{}")
        tmp_path = tmp.name

    try:
        state = PlexCache(tmp_path, ttl_seconds=0)
        state.set("PlexServer1", "User1", 10, False, 1000, datetime.now(timezone.utc))
        state.set("PlexServer1", "User2", 10, False, 2000, datetime.now(timezone.utc))
        assert state.get("PlexServer1", "user1", 10).get("time") == 1000
        assert state.get("PlexServer1", "user2", 10).get("time") == 2000
    finally:
        os.remove(tmp_path)


def test_plex_cache_drops_invalid_entries():
    data = {
        "PlexServer1": {
            "User1": {"10": {"completed": True}},
            "User2": "invalid",
            "User3": {
                "11": {
                    "completed": False,
                    "time": 1000,
                    "source_viewed_at": "2025-01-01T00:00:00Z",
                    "updated_at": "not-a-date",
                }
            },
        },
        "PlexServer2": "invalid",
        "PlexServer3": {
            "User4": {
                "12": {
                    "completed": False,
                    "time": 1000,
                    "source_viewed_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2025-01-02T00:00:00Z",
                }
            }
        },
    }
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        json.dump(data, tmp)
        tmp_path = tmp.name

    try:
        state = PlexCache(tmp_path, ttl_seconds=0)
        assert state.data == {
            "plexserver3": {
                "user4": {
                    "12": {
                        "completed": False,
                        "time": 1000,
                        "source_viewed_at": "2025-01-01T00:00:00Z",
                        "updated_at": "2025-01-02T00:00:00Z",
                    }
                }
            }
        }
    finally:
        os.remove(tmp_path)


def test_plex_cache_prune_drops_stale_entries():
    data = {
        "PlexServer1": {
            "User1": {
                "10": {
                    "completed": False,
                    "time": 1000,
                    "source_viewed_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2000-01-01T00:00:00Z",
                }
            }
        }
    }
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        json.dump(data, tmp)
        tmp_path = tmp.name

    try:
        state = PlexCache(tmp_path, ttl_seconds=60)
        state.save()
        assert state.data == {}
    finally:
        os.remove(tmp_path)


def test_plex_cache_prune_keeps_recent_entries():
    recent = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    data = {
        "PlexServer1": {
            "User1": {
                "10": {
                    "completed": False,
                    "time": 1000,
                    "source_viewed_at": "2025-01-01T00:00:00Z",
                    "updated_at": recent,
                }
            }
        }
    }
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        json.dump(data, tmp)
        tmp_path = tmp.name

    try:
        state = PlexCache(tmp_path, ttl_seconds=86400)
        state.save()
        assert state.data != {}
    finally:
        os.remove(tmp_path)


def test_plex_cache_normalizes_duplicate_keys():
    data = {
        "PlexServer1": {
            "User1": {
                "10": {
                    "completed": False,
                    "time": 1000,
                    "source_viewed_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2025-01-02T00:00:00Z",
                }
            }
        },
        "plexserver1": {
            "user1": {
                "10": {
                    "completed": False,
                    "time": 2000,
                    "source_viewed_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2025-01-03T00:00:00Z",
                }
            }
        },
    }
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        json.dump(data, tmp)
        tmp_path = tmp.name

    try:
        state = PlexCache(tmp_path, ttl_seconds=0)
        assert state.get("plexserver1", "user1", 10).get("time") == 2000
    finally:
        os.remove(tmp_path)
