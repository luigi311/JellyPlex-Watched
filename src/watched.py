import copy
from pydantic import BaseModel, Field
from loguru import logger
from typing import Any

from src.functions import search_mapping


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
    in favor of item2 (from watched_list_2), based on:
      - Duplicate criteria:
          * They match if any file location is shared OR
            at least one of imdb_id, tvdb_id, or tmdb_id matches.
      - Watched status:
          * If one is complete and the other is not, remove the incomplete one.
          * If both are incomplete, remove the one with lower progress (time).
          * If both are complete, remove item1 as duplicate.
    """
    if not check_same_identifiers(item1.identifiers, item2.identifiers):
        return False

    # Compare watched statuses.
    status1 = item1.status
    status2 = item2.status

    # If one is complete and the other isn't, remove the one that's not complete.
    if status1.completed != status2.completed:
        if not status1.completed and status2.completed:
            return True  # Remove item1 since it's not complete.
        else:
            return False  # Do not remove item1; it's complete.

    # Both have the same completed status.
    if not status1.completed and not status2.completed:
        # Both incomplete: remove the one with lower progress (time)
        if status1.time < status2.time:
            return True  # Remove item1 because it has watched less.
        elif status1.time > status2.time:
            return False  # Keep item1 because it has more progress.
        else:
            # Same progress; Remove duplicate
            return True

    # If both are complete, consider item1 the duplicate and remove it.
    return True


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
