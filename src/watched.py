from __future__ import annotations

import copy
from datetime import datetime
from enum import IntEnum
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from src.functions import to_aware_utc
from src.settings import AppSettings

if TYPE_CHECKING:
    from src.emby import Emby
    from src.jellyfin import Jellyfin
    from src.plex import Plex


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
    movies: list[MediaItem] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)


class UserData(BaseModel):
    libraries: dict[str, LibraryData] = Field(default_factory=dict)


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
    several individual Jellyfin users), so this returns a list. Keys in the
    watched dicts are the literal names each server reports (lowercased), so
    matching is done on lowercased names.
    """
    matched: list[str] = []
    for target in settings.sync_targets_for_user(
        source_server, source_user, target_server
    ):
        if target in target_watched:
            matched.append(target)
        elif target.lower() in target_watched:
            matched.append(target.lower())
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
    for target in settings.sync_targets_for_library(
        source_server, source_library, target_server
    ):
        if target in target_libraries:
            matched.append(target)
        elif target.lower() in target_libraries:
            matched.append(target.lower())
    return matched


def merge_server_watched(
    watched_list_1: dict[str, UserData],
    watched_list_2: dict[str, UserData],
    server_1: Plex | Jellyfin | Emby,
    server_2: Plex | Jellyfin | Emby,
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
    s1_name = server_1.server_settings.name
    s2_name = server_2.server_settings.name

    merged_watched = copy.deepcopy(watched_list_1)

    for user_2, user_data in watched_list_2.items():
        # A server_2 user may correspond to multiple server_1 users
        # (fan-out). Merge this user's data into every matching server_1 key.
        user_keys = find_target_user_keys(
            settings, s2_name, user_2, s1_name, merged_watched
        )
        if not user_keys:
            merged_watched[user_2] = copy.deepcopy(user_data)
            continue

        for user_key in user_keys:
            for lib_key, lib_data in user_data.libraries.items():
                mapped_lib_keys = find_target_library_keys(
                    settings,
                    s2_name,
                    lib_key,
                    s1_name,
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


def check_same_identifiers(item1: MediaIdentifiers, item2: MediaIdentifiers) -> bool:
    # Check for duplicate based on file locations:
    if item1.locations and item2.locations:
        if set(item1.locations) & set(item2.locations):
            return True

    # Check for duplicate based on GUIDs:
    if (
        (item1.imdb_id and item2.imdb_id and item1.imdb_id == item2.imdb_id)
        or (item1.tvdb_id and item2.tvdb_id and item1.tvdb_id == item2.tvdb_id)
        or (item1.tmdb_id and item2.tmdb_id and item1.tmdb_id == item2.tmdb_id)
    ):
        return True

    return False


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


def cleanup_watched(
    watched_list_1: dict[str, UserData],
    watched_list_2: dict[str, UserData],
    server_1: Plex | Jellyfin | Emby,
    server_2: Plex | Jellyfin | Emby,
    settings: AppSettings,
    average_time: float,
) -> dict[str, UserData]:
    s1_name = server_1.server_settings.name
    s2_name = server_2.server_settings.name

    modified_watched_list_1 = copy.deepcopy(watched_list_1)

    # remove entries from watched_list_1 that are in watched_list_2
    for user_1 in watched_list_1:
        # A server_1 user may correspond to multiple server_2 users
        # (fan-out). An item is eligible for removal if it's already watched
        # on ANY of the matched server_2 users.
        user_2_keys = find_target_user_keys(
            settings, s1_name, user_1, s2_name, watched_list_2
        )
        if not user_2_keys:
            continue

        for library_1_key in watched_list_1[user_1].libraries:
            # Gather every matching server_2 library across all matched
            # server_2 users, and pool their movies/series so a "watched on
            # the other side" check considers all fan-out targets together.
            pooled_movies: list[MediaItem] = []
            pooled_series: list[Series] = []
            for user_2 in user_2_keys:
                library_2_keys = find_target_library_keys(
                    settings,
                    s1_name,
                    library_1_key,
                    s2_name,
                    watched_list_2[user_2].libraries,
                )
                for library_2_key in library_2_keys:
                    library_2 = watched_list_2[user_2].libraries[library_2_key]
                    pooled_movies.extend(library_2.movies)
                    pooled_series.extend(library_2.series)

            if not pooled_movies and not pooled_series:
                continue

            library_1 = watched_list_1[user_1].libraries[library_1_key]

            filtered_movies = []
            for movie in library_1.movies:
                remove_flag = False
                for movie2 in pooled_movies:
                    if check_remove_entry(movie, movie2, settings, average_time):
                        logger.trace(f"Removing movie: {movie.identifiers.title}")
                        remove_flag = True
                        break

                if not remove_flag:
                    filtered_movies.append(movie)

            modified_watched_list_1[user_1].libraries[
                library_1_key
            ].movies = filtered_movies

            # TV Shows
            filtered_series_list = []
            for series1 in library_1.series:
                # Collect every matching show across the pooled targets, then
                # treat their episodes as one pool for removal decisions.
                matching_episodes: list[MediaItem] = []
                for series2 in pooled_series:
                    if check_same_identifiers(series1.identifiers, series2.identifiers):
                        matching_episodes.extend(series2.episodes)

                if not matching_episodes:
                    # No matching show on any target; keep the series as is.
                    filtered_series_list.append(series1)
                else:
                    # We have a matching show; now clean up the episodes.
                    filtered_episodes = []
                    for ep1 in series1.episodes:
                        remove_flag = False
                        for ep2 in matching_episodes:
                            if check_remove_entry(ep1, ep2, settings, average_time):
                                logger.trace(
                                    f"Removing episode '{ep1.identifiers.title}' from show '{series1.identifiers.title}'",
                                )
                                remove_flag = True
                                break
                        if not remove_flag:
                            filtered_episodes.append(ep1)

                    # Only keep the series if there are remaining episodes.
                    if filtered_episodes:
                        modified_series1 = copy.deepcopy(series1)
                        modified_series1.episodes = filtered_episodes
                        filtered_series_list.append(modified_series1)
                    else:
                        logger.trace(
                            f"Removing entire show '{series1.identifiers.title}' as no episodes remain after cleanup.",
                        )
            modified_watched_list_1[user_1].libraries[
                library_1_key
            ].series = filtered_series_list

    # After processing, remove any library that is completely empty.
    for user, user_data in modified_watched_list_1.items():
        new_libraries = {}
        for lib_key, library in user_data.libraries.items():
            if library.movies or library.series:
                new_libraries[lib_key] = library
            else:
                logger.trace(f"Removing empty library '{lib_key}' for user '{user}'")
        user_data.libraries = new_libraries

    return modified_watched_list_1
