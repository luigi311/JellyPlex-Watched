from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from loguru import logger


class CacheEntry(TypedDict):
    completed: bool
    time: int | None
    source_viewed_at: str
    updated_at: str


CacheData = dict[str, dict[str, dict[str, CacheEntry]]]


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_time(value: int | None) -> int:
    return 0 if value is None else int(value)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_iso_datetime(value: datetime | None) -> str | None:
    if not value:
        return None
    return _ensure_aware_utc(value).isoformat().replace("+00:00", "Z")


def _norm_machine_id(value: str | None) -> str | None:
    if value is None:
        return None
    return str(value).strip().lower()


def _norm_user_key(value: str | None) -> str | None:
    if value is None:
        return None
    return str(value).strip().lower()


def _norm_rating_key(value: str | int | None) -> str | None:
    if value is None:
        return None
    return str(value).strip()


def state_matches(
    completed: bool, time: int | None, state_entry: CacheEntry | None
) -> bool:
    if not state_entry:
        return False
    if state_entry.get("completed") != completed:
        return False
    if completed:
        return True
    return _normalize_time(state_entry.get("time")) == _normalize_time(time)


def resolve_viewed_date(
    last_viewed_at: datetime | None,
    completed: bool,
    time: int | None,
    state_entry: CacheEntry | None,
) -> datetime:
    if state_matches(completed, time, state_entry):
        source_viewed_at = _parse_iso_datetime(state_entry.get("source_viewed_at"))
        if source_viewed_at:
            return _ensure_aware_utc(source_viewed_at)

    if last_viewed_at:
        return _ensure_aware_utc(last_viewed_at)

    return datetime.now(timezone.utc)


class PlexCache:
    def __init__(self, path: str, ttl_seconds: int | None = None) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds
        self.dirty = False
        self.data, upgraded = self._load()
        if upgraded:
            self.dirty = True

    def _load(self) -> tuple[CacheData, bool]:
        if not self.path or not os.path.exists(self.path):
            return {}, False
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                content = file.read().strip()
            if not content:
                logger.info(f"Plex cache: empty file {self.path}, starting fresh")
                return {}, False
            raw = json.loads(content)
        except Exception as exc:
            logger.warning(f"Plex cache: failed to load {self.path}: {exc}")
            return {}, False

        if not isinstance(raw, dict):
            logger.warning(f"Plex cache: expected dict in {self.path}")
            return {}, False

        normalized: CacheData = {}
        changed = False
        required = {"completed", "time", "source_viewed_at", "updated_at"}

        for machine_key, users in raw.items():
            machine_norm = _norm_machine_id(machine_key)
            if not machine_norm or not isinstance(users, dict):
                changed = True
                continue
            if machine_norm != machine_key:
                changed = True

            for user_key, items in users.items():
                user_norm = _norm_user_key(user_key)
                if not user_norm or not isinstance(items, dict):
                    changed = True
                    continue
                if user_norm != user_key:
                    changed = True

                for rating_key, entry in items.items():
                    rating_norm = _norm_rating_key(rating_key)
                    if not rating_norm or not isinstance(entry, dict):
                        changed = True
                        continue
                    if rating_norm != rating_key:
                        changed = True
                    if required.difference(entry.keys()):
                        changed = True
                        continue

                    updated_at = _parse_iso_datetime(entry.get("updated_at"))
                    source_viewed_at = _parse_iso_datetime(
                        entry.get("source_viewed_at")
                    )
                    if not updated_at or not source_viewed_at:
                        changed = True
                        continue

                    completed = entry.get("completed")
                    time = entry.get("time")
                    if not isinstance(completed, bool) or (
                        time is not None and not isinstance(time, int)
                    ):
                        changed = True
                        continue

                    machine_bucket = normalized.setdefault(machine_norm, {})
                    user_bucket = machine_bucket.setdefault(user_norm, {})
                    existing = user_bucket.get(rating_norm)
                    if existing:
                        existing_ts = _parse_iso_datetime(existing.get("updated_at"))
                        changed = True
                        if existing_ts and updated_at > existing_ts:
                            user_bucket[rating_norm] = entry
                    else:
                        user_bucket[rating_norm] = entry

        total_entries = sum(
            len(items) for users in normalized.values() for items in users.values()
        )
        logger.info(f"Plex cache: loaded {total_entries} entrie(s) from {self.path}")

        return normalized, changed

    def _get_entry(
        self, machine_id: str, user_key: str, rating_key: str
    ) -> CacheEntry | None:
        return self.data.get(machine_id, {}).get(user_key, {}).get(rating_key)

    def get(
        self, machine_id: str | None, user_key: str | None, rating_key: str | int | None
    ) -> CacheEntry | None:
        machine_norm = _norm_machine_id(machine_id)
        user_norm = _norm_user_key(user_key)
        rating_norm = _norm_rating_key(rating_key)
        if not machine_norm or not user_norm or not rating_norm:
            return None
        return self._get_entry(machine_norm, user_norm, rating_norm)

    def set(
        self,
        machine_id: str | None,
        user_key: str | None,
        rating_key: str | int | None,
        completed: bool,
        time: int | None,
        source_viewed_at: datetime | None,
    ) -> None:
        machine_norm = _norm_machine_id(machine_id)
        user_norm = _norm_user_key(user_key)
        rating_norm = _norm_rating_key(rating_key)
        if not machine_norm or not user_norm or not rating_norm:
            return
        source_iso = _to_iso_datetime(source_viewed_at)
        updated_iso = _to_iso_datetime(datetime.now(timezone.utc))
        if not source_iso or not updated_iso:
            return
        entry: CacheEntry = {
            "completed": bool(completed),
            "time": int(time) if time is not None else None,
            "source_viewed_at": source_iso,
            "updated_at": updated_iso,
        }
        machine_bucket = self.data.setdefault(machine_norm, {})
        user_bucket = machine_bucket.setdefault(user_norm, {})
        user_bucket[rating_norm] = entry
        self.dirty = True

    def _prune(self) -> None:
        if not self.ttl_seconds or self.ttl_seconds <= 0:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.ttl_seconds)
        removed = 0
        for machine_id, users in list(self.data.items()):
            for user_key, items in list(users.items()):
                for rating_key, entry in list(items.items()):
                    updated_at = _parse_iso_datetime(entry.get("updated_at"))
                    if not updated_at or updated_at < cutoff:
                        del items[rating_key]
                        removed += 1
                if not items:
                    del users[user_key]
            if not users:
                del self.data[machine_id]
        if removed:
            self.dirty = True
            logger.info(f"Plex cache: pruned {removed} stale entries")

    def save(self) -> None:
        if not self.path:
            return
        self._prune()
        if not self.dirty:
            return
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump(self.data, file, indent=2, sort_keys=True)
        self.dirty = False
