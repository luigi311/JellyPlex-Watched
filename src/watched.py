import copy
from datetime import datetime
from enum import IntEnum
from pydantic import BaseModel, Field
from loguru import logger
from typing import Any

from src.functions import search_mapping, to_aware_utc


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


def compare_media_items(media1: MediaItem, media2: MediaItem) -> Ord:
    media1_viewed_date, media2_viewed_date = (
        to_aware_utc(media1.status.viewed_date),
        to_aware_utc(media2.status.viewed_date),
    )

    # If both are completed, it's a tie.
    if media1.status.completed and media2.status.completed:
        return Ord.TIE

    # If both are not completed, and have the same time, it's a tie.
    if (
        not media1.status.completed
        and not media2.status.completed
        and media1.status.time == media2.status.time
    ):
        return Ord.TIE

    # Compare viewed_date first (only if both have dates)
    if (
        media1_viewed_date
        and media2_viewed_date
        and media1_viewed_date != media2_viewed_date
    ):
        return Ord.A_BETTER if media1_viewed_date > media2_viewed_date else Ord.B_BETTER

    # If one or both items are missing viewed_date, skip date comparison
    # and fall through to completion status and time comparisons

    # Next, compare completed status
    if media1.status.completed != media2.status.completed:
        return Ord.A_BETTER if media1.status.completed else Ord.B_BETTER

    # Finally, compare time
    if media1.status.time != media2.status.time:
        return Ord.A_BETTER if media1.status.time > media2.status.time else Ord.B_BETTER

    return Ord.TIE


def merge_mediaitem_data(media1: MediaItem, media2: MediaItem) -> MediaItem:
    """
    Merge two MediaItem episodes by comparing their watched status.
    If one is completed while the other isn't, choose the completed one.
    If both are completed or both are not, choose the one with the higher time.
    """

    ord_ = compare_media_items(media1, media2)
    return media1 if ord_ in (Ord.A_BETTER, Ord.TIE) else media2


def merge_series_data(series1: Series, series2: Series) -> Series:
    """
    Merge two Series objects by combining their episodes.
    For duplicate episodes (determined by check_same_identifiers), merge their watched status.
    """
    merged_series = copy.deepcopy(series1)
    for ep in series2.episodes:
        for idx, merged_ep in enumerate(merged_series.episodes):
            if check_same_identifiers(ep.identifiers, merged_ep.identifiers):
                merged_series.episodes[idx] = merge_mediaitem_data(merged_ep, ep)
                break
        else:
            merged_series.episodes.append(copy.deepcopy(ep))
    return merged_series


def merge_library_data(lib1: LibraryData, lib2: LibraryData) -> LibraryData:
    """
    Merge two LibraryData objects by extending movies and merging series.
    For series, duplicates are determined using check_same_identifiers.
    """
    merged = copy.deepcopy(lib1)

    # Merge movies.
    for movie in lib2.movies:
        for idx, merged_movie in enumerate(merged.movies):
            if check_same_identifiers(movie.identifiers, merged_movie.identifiers):
                merged.movies[idx] = merge_mediaitem_data(merged_movie, movie)
                break
        else:
            merged.movies.append(copy.deepcopy(movie))

    # Merge series.
    for series2 in lib2.series:
        for idx, series1 in enumerate(merged.series):
            if check_same_identifiers(series1.identifiers, series2.identifiers):
                merged.series[idx] = merge_series_data(series1, series2)
                break
        else:
            merged.series.append(copy.deepcopy(series2))

    return merged


def merge_user_data(user1: UserData, user2: UserData) -> UserData:
    """
    Merge two UserData objects by merging their libraries.
    If a library exists in both, merge its content; otherwise, add the new library.
    """
    merged_libraries = copy.deepcopy(user1.libraries)
    for lib_key, lib_data in user2.libraries.items():
        if lib_key in merged_libraries:
            merged_libraries[lib_key] = merge_library_data(
                merged_libraries[lib_key], lib_data
            )
        else:
            merged_libraries[lib_key] = copy.deepcopy(lib_data)
    return UserData(libraries=merged_libraries)


def merge_server_watched(
    watched_list_1: dict[str, UserData],
    watched_list_2: dict[str, UserData],
    user_mapping: dict[str, str] | None = None,
    library_mapping: dict[str, str] | None = None,
) -> dict[str, UserData]:
    """
    Merge two dictionaries of UserData while taking into account possible
    differences in user and library keys via the provided mappings.
    """
    merged_watched = copy.deepcopy(watched_list_1)

    for user_2, user_data in watched_list_2.items():
        # Determine matching user key.
        user_key = user_mapping.get(user_2, user_2) if user_mapping else user_2
        if user_key not in merged_watched:
            merged_watched[user_2] = copy.deepcopy(user_data)
            continue

        for lib_key, lib_data in user_data.libraries.items():
            mapped_lib_key = (
                library_mapping.get(lib_key, lib_key) if library_mapping else lib_key
            )
            if mapped_lib_key not in merged_watched[user_key].libraries:
                merged_watched[user_key].libraries[lib_key] = copy.deepcopy(lib_data)
            else:
                merged_watched[user_key].libraries[mapped_lib_key] = merge_library_data(
                    merged_watched[user_key].libraries[mapped_lib_key],
                    lib_data,
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


def check_remove_entry(item1: MediaItem, item2: MediaItem) -> bool:
    """
    Returns True if item1 (from watched_list_1) should be removed
    in favor of item2 (from watched_list_2)
    """
    if not check_same_identifiers(item1.identifiers, item2.identifiers):
        return False

    # Removal policy for cleanup: drop item1 if item2 is as-good-or-better.
    return compare_media_items(item1, item2) in (Ord.B_BETTER, Ord.TIE)


def cleanup_watched(
    watched_list_1: dict[str, UserData],
    watched_list_2: dict[str, UserData],
    user_mapping: dict[str, str] | None = None,
    library_mapping: dict[str, str] | None = None,
) -> dict[str, UserData]:
    modified_watched_list_1 = copy.deepcopy(watched_list_1)

    # remove entries from watched_list_1 that are in watched_list_2
    for user_1 in watched_list_1:
        user_other = None
        if user_mapping:
            user_other = search_mapping(user_mapping, user_1)
        user_2 = get_other(watched_list_2, user_1, user_other)
        if user_2 is None:
            continue

        for library_1_key in watched_list_1[user_1].libraries:
            library_other = None
            if library_mapping:
                library_other = search_mapping(library_mapping, library_1_key)
            library_2_key = get_other(
                watched_list_2[user_2].libraries, library_1_key, library_other
            )
            if library_2_key is None:
                continue

            library_1 = watched_list_1[user_1].libraries[library_1_key]
            library_2 = watched_list_2[user_2].libraries[library_2_key]

            filtered_movies = []
            for movie in library_1.movies:
                remove_flag = False
                for movie2 in library_2.movies:
                    if check_remove_entry(movie, movie2):
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
                matching_series = None
                for series2 in library_2.series:
                    if check_same_identifiers(series1.identifiers, series2.identifiers):
                        matching_series = series2
                        break

                if matching_series is None:
                    # No matching show in watched_list_2; keep the series as is.
                    filtered_series_list.append(series1)
                else:
                    # We have a matching show; now clean up the episodes.
                    filtered_episodes = []
                    for ep1 in series1.episodes:
                        remove_flag = False
                        for ep2 in matching_series.episodes:
                            if check_remove_entry(ep1, ep2):
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


def get_other(
    watched_list: dict[str, Any], object_1: str, object_2: str | None
) -> str | None:
    if object_1 in watched_list:
        return object_1

    if object_2 and object_2 in watched_list:
        return object_2

    logger.info(
        f"{object_1}{' and ' + object_2 if object_2 else ''} not found in watched list 2"
    )

    return None
