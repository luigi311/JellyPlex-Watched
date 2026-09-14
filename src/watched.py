from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any, Literal, TypeVar

from loguru import logger
from pydantic import BaseModel, Field

from src.functions import normalize_name, to_aware_utc
from src.settings import AppSettings


class Ord(IntEnum):
    A_BETTER = -1
    TIE = 0
    B_BETTER = 1


class MediaIdentifiers(BaseModel):
    title: str | None = None

    # File information, will be folder for series and media file for episode/movie
    locations: tuple[str, ...] = tuple()

    # Guids
    imdb_id: str | None = None
    tvdb_id: str | None = None
    tmdb_id: str | None = None

    # A planned winner keeps its native identifiers above. These additional
    # (namespace, value) pairs retain matches learned from permitted histories,
    # including multiple IDs from the same provider or alternate filenames.
    matching_aliases: frozenset[tuple[str, str]] = frozenset()


class WatchedStatus(BaseModel):
    completed: bool
    time: int
    viewed_date: datetime


class MediaItem(BaseModel):
    identifiers: MediaIdentifiers
    status: WatchedStatus


class Series(BaseModel):
    identifiers: MediaIdentifiers
    episodes: list[MediaItem] = Field(default_factory=list)


class LibraryData(BaseModel):
    title: str
    # Discovery metadata used for directional type filters and rule exceptions.
    library_type: str | None = None
    movies: list[MediaItem] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)


class UserData(BaseModel):
    libraries: dict[str, LibraryData] = Field(default_factory=dict)


@dataclass(frozen=True, order=True)
class WatchedScope:
    """One server-native user/library scope along an authorized sync path."""

    server_name: str
    username: str
    library_name: str


@dataclass(frozen=True)
class WatchedUpdate:
    """One pending library update from a source scope to a concrete destination."""

    source_user: str
    target_user: str
    source_library: str
    target_library: str
    library_data: LibraryData
    # Indirect plans retain the original source and every hop, including the
    # destination. source_user/source_library describe the final incoming hop
    # so adapters can resolve its aliases without inventing a direct mapping.
    relay_path: tuple[WatchedScope, ...] = ()


WriteOutcomeStatus = Literal[
    "applied",
    "skipped",
    "unsupported",
    "failed",
    "uncertain",
]


@dataclass(frozen=True)
class WatchedWriteOutcome:
    """Result for one attempted item update on a concrete destination."""

    status: WriteOutcomeStatus
    target_user: str
    target_library: str
    media_item: MediaItem
    series_identifiers: MediaIdentifiers | None = None
    target_user_id: str | None = None
    target_library_id: str | None = None
    target_item_id: str | None = None
    reason: str | None = None


def resulting_media_item(
    media_item: MediaItem,
    completed: bool,
    identifiers: MediaIdentifiers | None = None,
) -> MediaItem:
    """Return the state represented by a completed or partial write."""
    updates: dict[str, Any] = {
        "status": media_item.status.model_copy(
            update={
                "completed": completed,
                "time": 0 if completed else media_item.status.time,
            }
        )
    }
    if identifiers is not None:
        updates["identifiers"] = identifiers
    return media_item.model_copy(
        update=updates
    )


_WatchedData = TypeVar("_WatchedData")


def _lookup_named(
    values: dict[str, _WatchedData], name: str
) -> _WatchedData | None:
    """Find a watched-data entry using the same case-folded lookup as settings."""
    if name in values:
        return values[name]

    name_normalized = normalize_name(name)
    for actual_name, value in values.items():
        if normalize_name(actual_name) == name_normalized:
            return value
    return None


def expand_watched_updates(
    watched_list: dict[str, UserData],
    source_server_name: str,
    target_server_name: str,
    settings: AppSettings,
) -> list[WatchedUpdate]:
    """Expand source-shaped watched data into destination-scoped updates.

    Authorize each source scope before fan-in can combine its history with
    other scopes and discard the original source identity.

    This is also used for callers that provide a complete source watched
    dictionary directly to an adapter. A missing destination history is
    represented by an update with the source library data unchanged; the
    adapter will still verify that the destination user and library exist.
    """
    updates: list[WatchedUpdate] = []
    for source_user, user_data in watched_list.items():
        if not settings.should_sync_user(
            source_user, source_server_name, target_server_name
        ):
            continue
        target_users = settings.sync_targets_for_user(
            source_server_name, source_user, target_server_name
        )
        for target_user in target_users:
            for source_library, library_data in user_data.libraries.items():
                if not settings.should_sync_scope(
                    source_user,
                    source_library,
                    source_server_name,
                    target_server_name,
                    library_type=library_data.library_type,
                ):
                    continue
                target_libraries = settings.sync_targets_for_library(
                    source_server_name,
                    source_library,
                    target_server_name,
                )
                for target_library in target_libraries:
                    updates.append(
                        WatchedUpdate(
                            source_user=source_user,
                            target_user=target_user,
                            source_library=source_library,
                            target_library=target_library,
                            library_data=library_data,
                        )
                    )
    return updates


def compare_media_items(
    media1: MediaItem,
    media2: MediaItem,
    settings: AppSettings,
    average_time: float,
) -> Ord:
    logger.trace(
        "Comparing the following media items:"
        f"\n'{media1.identifiers}' (completed={media1.status.completed}, time={media1.status.time}, viewed_date={media1.status.viewed_date})"
        f"\n'{media2.identifiers}' (completed={media2.status.completed}, time={media2.status.time}, viewed_date={media2.status.viewed_date})"
    )

    media1_viewed_date, media2_viewed_date = (
        to_aware_utc(media1.status.viewed_date),
        to_aware_utc(media2.status.viewed_date),
    )

    # If both are completed, it's a tie.
    if media1.status.completed and media2.status.completed:
        logger.trace("Both media items are completed. Considering it a tie.")
        return Ord.TIE

    # If both are not completed, but their time is within 10 seconds, it's also a tie.
    if (not media1.status.completed and not media2.status.completed) and abs(
        media1.status.time - media2.status.time
    ) <= 10 * 1_000:
        logger.trace(
            "Both media items are not completed but their time is within 10 seconds. Considering it a tie."
        )
        return Ord.TIE

    # If both have viewed dates, compare them. If they are close enough, consider it a tie.
    if media1_viewed_date and media2_viewed_date:
        # Define threshold time as 25% above the average time plus sleep duration to account for minor discrepancies in viewing times.
        threshold_time = (average_time * 1.25) + float(settings.sleep_duration)
        # If not within threshold_time of each other, choose the more recent one as better.
        if (
            abs((media1_viewed_date - media2_viewed_date).total_seconds())
            > threshold_time
        ):
            logger.trace(
                f"Both media items have viewed dates that are more than {threshold_time} seconds apart. Chosing the more recent one as better."
            )

            return (
                Ord.A_BETTER
                if media1_viewed_date > media2_viewed_date
                else Ord.B_BETTER
            )

    # If one is completed and the other isn't, the completed one is better.
    if media1.status.completed != media2.status.completed:
        logger.trace(
            "One media item is completed while the other is not. Choosing the completed one as better."
        )
        return Ord.A_BETTER if media1.status.completed else Ord.B_BETTER

    # If both are not completed, compare their time. The one with the higher time is better.
    if media1.status.time != media2.status.time:
        logger.trace(
            "Both media items are not completed but have different times. Choosing the one with the higher time as better."
        )
        return Ord.A_BETTER if media1.status.time > media2.status.time else Ord.B_BETTER

    # If we can't determine a clear winner based on the above criteria, consider it a tie.
    logger.trace(
        "Unable to determine a clear winner based on watched status. Considering it a tie."
    )
    return Ord.TIE


def merge_mediaitem_data(
    media1: MediaItem,
    media2: MediaItem,
    settings: AppSettings,
    average_time: float,
) -> MediaItem:
    """
    Merge two MediaItem episodes by comparing their watched status.
    If one is completed while the other isn't, choose the completed one.
    If both are completed or both are not, choose the one with the higher time.
    """

    ord_ = compare_media_items(media1, media2, settings, average_time)
    return media1 if ord_ in (Ord.A_BETTER, Ord.TIE) else media2


def merge_series_data(
    series1: Series, series2: Series, settings: AppSettings, average_time: float
) -> Series:
    """
    Merge two Series objects by combining their episodes.
    For duplicate episodes (determined by check_same_identifiers), merge their watched status.
    """
    merged_series = copy.deepcopy(series1)
    for ep in series2.episodes:
        for idx, merged_ep in enumerate(merged_series.episodes):
            if check_same_identifiers(ep.identifiers, merged_ep.identifiers):
                merged_series.episodes[idx] = merge_mediaitem_data(
                    merged_ep, ep, settings, average_time
                )
                break
        else:
            merged_series.episodes.append(copy.deepcopy(ep))
    return merged_series


def merge_library_data(
    lib1: LibraryData,
    lib2: LibraryData,
    settings: AppSettings,
    average_time: float,
) -> LibraryData:
    """
    Merge two LibraryData objects by extending movies and merging series.
    For series, duplicates are determined using check_same_identifiers.
    """
    merged = copy.deepcopy(lib1)

    # Merge movies.
    for movie in lib2.movies:
        for idx, merged_movie in enumerate(merged.movies):
            if check_same_identifiers(movie.identifiers, merged_movie.identifiers):
                merged.movies[idx] = merge_mediaitem_data(
                    merged_movie, movie, settings, average_time
                )
                break
        else:
            merged.movies.append(copy.deepcopy(movie))

    # Merge series.
    for series2 in lib2.series:
        for idx, series1 in enumerate(merged.series):
            if check_same_identifiers(series1.identifiers, series2.identifiers):
                merged.series[idx] = merge_series_data(
                    series1, series2, settings, average_time
                )
                break
        else:
            merged.series.append(copy.deepcopy(series2))

    return merged


def merge_destination_watched(
    watched_list: dict[str, UserData],
    outcomes: list[WatchedWriteOutcome],
    settings: AppSettings,
    average_time: float,
) -> dict[str, UserData]:
    """Merge confirmed writes into the cache using destination-native names.

    Adapter receipts already identify the concrete user and library that were
    written. They must be merged against the cache for that same destination;
    translating them through the source server can credit a write to an
    unrelated identity. A receipt for an identity absent from the cache is
    ignored because it cannot be safely associated with the snapshot.
    """
    merged_watched = copy.deepcopy(watched_list)
    user_keys = {normalize_name(key): key for key in merged_watched}

    for outcome in outcomes:
        if outcome.status != "applied":
            continue

        user_key = user_keys.get(normalize_name(outcome.target_user))
        if user_key is None:
            logger.warning(
                "Skipping confirmed watched receipt for unknown destination user {}",
                outcome.target_user,
            )
            continue

        library_keys = {
            normalize_name(key): key
            for key in merged_watched[user_key].libraries
        }
        library_key = library_keys.get(normalize_name(outcome.target_library))
        if library_key is None:
            logger.warning(
                "Skipping confirmed watched receipt for unknown destination "
                "library {} for user {}",
                outcome.target_library,
                outcome.target_user,
            )
            continue

        receipt_library = LibraryData(title=library_key)
        if outcome.series_identifiers is None:
            receipt_library.movies.append(copy.deepcopy(outcome.media_item))
        else:
            receipt_library.series.append(
                Series(
                    identifiers=copy.deepcopy(outcome.series_identifiers),
                    episodes=[copy.deepcopy(outcome.media_item)],
                )
            )

        merged_watched[user_key].libraries[library_key] = merge_library_data(
            merged_watched[user_key].libraries[library_key],
            receipt_library,
            settings,
            average_time,
        )

    return merged_watched


def _coalesce_watched_updates(
    pending_updates: list[WatchedUpdate],
    settings: AppSettings,
    average_time: float,
) -> list[WatchedUpdate]:
    """Combine competing updates that target the same user and library.

    Fan-in mappings can produce several source updates for one concrete
    destination. Sort each group by its source identity before merging so
    equal states are resolved consistently, regardless of source traversal
    order. Duplicate media items are then reduced with the normal watched
    state comparison while distinct items remain in the combined update.
    """
    grouped: dict[tuple[str, str], list[WatchedUpdate]] = {}
    for update in pending_updates:
        destination = (
            normalize_name(update.target_user),
            normalize_name(update.target_library),
        )
        grouped.setdefault(destination, []).append(update)

    coalesced: list[WatchedUpdate] = []
    for destination in sorted(grouped):
        updates = sorted(
            grouped[destination],
            key=lambda update: (
                normalize_name(update.source_user),
                normalize_name(update.source_library),
            ),
        )
        first = updates[0]
        library_data = first.library_data
        for update in updates[1:]:
            library_data = merge_library_data(
                library_data,
                update.library_data,
                settings,
                average_time,
            )

        coalesced.append(
            WatchedUpdate(
                source_user=first.source_user,
                target_user=first.target_user,
                source_library=first.source_library,
                target_library=first.target_library,
                library_data=library_data,
            )
        )

    return coalesced


def find_target_user_keys(
    settings: AppSettings,
    source_server: str,
    source_user: str,
    target_server: str,
    target_watched: dict[str, Any],
) -> list[str]:
    """
    Find every key in `target_watched` that corresponds to `source_user` (as
    known on `source_server`) on `target_server`.

    Resolves candidate target usernames via settings.sync_targets_for_user
    (which handles explicit user_mappings aliases plus the implicit
    same-username fallback) and returns *every* candidate that is actually
    present as a key in `target_watched`. A single source user may fan out
    to multiple target users (e.g. a shared family Plex account mapping to
    several individual Jellyfin users), so this returns a list. Matching uses
    the shared case-folded name normalization.
    """
    matched: list[str] = []
    target_keys = {normalize_name(key): key for key in target_watched}
    for target in settings.sync_targets_for_user(
        source_server, source_user, target_server
    ):
        target_key = target if target in target_watched else target_keys.get(
            normalize_name(target)
        )
        if target_key is not None:
            matched.append(target_key)
    return matched


def find_target_library_keys(
    settings: AppSettings,
    source_server: str,
    source_library: str,
    target_server: str,
    target_libraries: dict[str, Any],
) -> list[str]:
    """
    Library counterpart of find_target_user_keys. Resolves candidate target
    library names via settings.sync_targets_for_library and returns every one
    present in `target_libraries` (libraries can fan out too).
    """
    matched: list[str] = []
    target_keys = {normalize_name(key): key for key in target_libraries}
    for target in settings.sync_targets_for_library(
        source_server, source_library, target_server
    ):
        target_key = target if target in target_libraries else target_keys.get(
            normalize_name(target)
        )
        if target_key is not None:
            matched.append(target_key)
    return matched


def merge_server_watched(
    watched_list_1: dict[str, UserData],
    watched_list_2: dict[str, UserData],
    server_1_name: str,
    server_2_name: str,
    settings: AppSettings,
    average_time: float,
) -> dict[str, UserData]:
    """
    Merge two dictionaries of UserData while taking into account possible
    differences in user and library keys.

    User/library correspondence between the two servers is resolved through
    the settings model (sync_targets_for_user / sync_targets_for_library),
    so explicit mappings and the implicit same-name fallback are both
    handled. server_1 / server_2 supply the configured server names that the
    settings lookups key off of.
    """
    merged_watched = copy.deepcopy(watched_list_1)

    for user_2, user_data in watched_list_2.items():
        # A server_2 user may correspond to multiple server_1 users
        # (fan-out). Merge this user's data into every matching server_1 key.
        user_keys = find_target_user_keys(
            settings, server_2_name, user_2, server_1_name, merged_watched
        )
        if not user_keys:
            merged_watched[user_2] = copy.deepcopy(user_data)
            continue

        for user_key in user_keys:
            for lib_key, lib_data in user_data.libraries.items():
                mapped_lib_keys = find_target_library_keys(
                    settings,
                    server_2_name,
                    lib_key,
                    server_1_name,
                    merged_watched[user_key].libraries,
                )
                if not mapped_lib_keys:
                    merged_watched[user_key].libraries[lib_key] = copy.deepcopy(
                        lib_data
                    )
                else:
                    for mapped_lib_key in mapped_lib_keys:
                        merged_watched[user_key].libraries[mapped_lib_key] = (
                            merge_library_data(
                                merged_watched[user_key].libraries[mapped_lib_key],
                                lib_data,
                                settings,
                                average_time,
                            )
                        )

    return merged_watched


def media_identifier_keys(item: MediaIdentifiers) -> frozenset[tuple[str, str]]:
    """Return namespaced matching keys; titles are never identity evidence."""
    keys = {("location", location) for location in item.locations}
    for provider, value in (
        ("imdb", item.imdb_id),
        ("tvdb", item.tvdb_id),
        ("tmdb", item.tmdb_id),
    ):
        if value:
            keys.add((provider, value))
    return frozenset(keys) | item.matching_aliases


def check_same_identifiers(item1: MediaIdentifiers, item2: MediaIdentifiers) -> bool:
    return not media_identifier_keys(item1).isdisjoint(media_identifier_keys(item2))


def check_remove_entry(
    item1: MediaItem,
    item2: MediaItem,
    settings: AppSettings,
    average_time: float,
) -> bool:
    """
    Returns True if item1 (from watched_list_1) should be removed
    in favor of item2 (from watched_list_2)
    """
    if not check_same_identifiers(item1.identifiers, item2.identifiers):
        return False

    # Removal policy for cleanup: drop item1 if item2 is as-good-or-better.
    return compare_media_items(item1, item2, settings, average_time) in (
        Ord.B_BETTER,
        Ord.TIE,
    )


def filter_library_watched(
    source_library: LibraryData,
    target_library: LibraryData | None,
    settings: AppSettings,
    average_time: float,
) -> LibraryData:
    """Copy source items whose state is better than the matching destination."""
    target_movies = target_library.movies if target_library else []
    target_series_list = target_library.series if target_library else []

    filtered_movies = []
    for movie in source_library.movies:
        if any(
            check_remove_entry(movie, target_movie, settings, average_time)
            for target_movie in target_movies
        ):
            logger.trace(
                f"Removing movie '{movie.identifiers.title}' for "
                f"library {target_library.title if target_library else source_library.title}"
            )
        else:
            filtered_movies.append(copy.deepcopy(movie))

    filtered_series_list: list[Series] = []
    for source_series in source_library.series:
        matching_episodes: list[MediaItem] = []
        for target_series in target_series_list:
            if check_same_identifiers(
                source_series.identifiers, target_series.identifiers
            ):
                matching_episodes.extend(target_series.episodes)

        if not matching_episodes:
            filtered_series_list.append(copy.deepcopy(source_series))
            continue

        filtered_episodes = []
        for source_episode in source_series.episodes:
            if any(
                check_remove_entry(
                    source_episode,
                    target_episode,
                    settings,
                    average_time,
                )
                for target_episode in matching_episodes
            ):
                logger.trace(
                    f"Removing episode '{source_episode.identifiers.title}' "
                    f"from show '{source_series.identifiers.title}' for "
                    f"library {target_library.title if target_library else source_library.title}"
                )
            else:
                filtered_episodes.append(copy.deepcopy(source_episode))

        if filtered_episodes:
            filtered_series = copy.deepcopy(source_series)
            filtered_series.episodes = filtered_episodes
            filtered_series_list.append(filtered_series)
        else:
            logger.trace(
                f"Removing entire show '{source_series.identifiers.title}' "
                f"in library {target_library.title if target_library else source_library.title}"
            )

    return LibraryData(
        title=source_library.title,
        library_type=source_library.library_type,
        movies=filtered_movies,
        series=filtered_series_list,
    )


def cleanup_watched(
    watched_list_1: dict[str, UserData],
    watched_list_2: dict[str, UserData],
    server_1_name: str,
    server_2_name: str,
    settings: AppSettings,
    average_time: float,
    *,
    require_destination_scope: bool = False,
) -> list[WatchedUpdate]:
    """Return pending updates with comparisons scoped to each destination.

    A source user or library can fan out to several destinations. Each
    destination gets its own comparison against its own watched history, so
    one destination having an item does not suppress the update for another.
    """
    pending_updates: list[WatchedUpdate] = []

    for update in expand_watched_updates(
        watched_list_1,
        server_1_name,
        server_2_name,
        settings,
    ):
        target_user_data = _lookup_named(watched_list_2, update.target_user)
        target_library = (
            _lookup_named(target_user_data.libraries, update.target_library)
            if target_user_data is not None
            else None
        )

        # Global fetches omit unknown/failed scopes; never treat these as empty.
        if require_destination_scope and target_library is None:
            continue

        if not settings.should_sync_scope(
            update.source_user,
            update.source_library,
            server_1_name,
            server_2_name,
            library_type=update.library_data.library_type,
            target_library_type=target_library.library_type if target_library else None,
        ):
            continue

        filtered = filter_library_watched(
            update.library_data, target_library, settings, average_time
        )
        if filtered.movies or filtered.series:
            pending_updates.append(
                WatchedUpdate(
                    source_user=update.source_user,
                    target_user=update.target_user,
                    source_library=update.source_library,
                    target_library=update.target_library,
                    library_data=filtered,
                )
            )

    return _coalesce_watched_updates(pending_updates, settings, average_time)
