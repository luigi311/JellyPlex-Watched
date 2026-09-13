# Functions for Jellyfin and Emby

from __future__ import annotations

import traceback
from datetime import datetime
from math import floor
from typing import Any, Literal

import requests
from loguru import logger
from packaging.version import Version, parse

from src.functions import (
    filename_from_any_path,
    log_marked,
    normalize_name,
)
from src.settings import AppSettings, EmbySettings, JellyfinSettings
from src.watched import (
    LibraryData,
    MediaIdentifiers,
    MediaItem,
    Series,
    UserData,
    WatchedStatus,
    check_same_identifiers,
    expand_watched_updates,
    WatchedUpdate,
    WatchedWriteOutcome,
    WriteOutcomeStatus,
    resulting_media_item,
)


def extract_identifiers_from_item(
    server_type: str,
    item: dict[str, Any],
    generate_guids: bool,
    generate_locations: bool,
) -> MediaIdentifiers:
    title = item.get("Name")
    id = None
    if not title:
        id = item.get("Id")
        logger.debug(f"{server_type}: Name not found for {id}")

    guids = {}
    if generate_guids:
        guids = {k.lower(): v for k, v in item.get("ProviderIds", {}).items()}

    locations: tuple[str, ...] = tuple()
    full_path: str = ""
    if generate_locations:
        if item.get("Path"):
            full_path = item["Path"]
            locations = tuple([filename_from_any_path(full_path)])
        elif item.get("MediaSources"):
            full_paths = [x["Path"] for x in item["MediaSources"] if x.get("Path")]
            locations = tuple([filename_from_any_path(x) for x in full_paths])
            full_path = " ".join(full_paths)

    if generate_guids:
        if not guids:
            logger.debug(
                f"{server_type}: {title if title else id} has no guids{f', locations: {full_path}' if full_path else ''}",
            )

    if generate_locations:
        if not locations:
            logger.debug(
                f"{server_type}: {title if title else id} has no locations{f', guids: {guids}' if guids else ''}",
            )

    return MediaIdentifiers(
        title=title,
        locations=locations,
        imdb_id=guids.get("imdb"),
        tvdb_id=guids.get("tvdb"),
        tmdb_id=guids.get("tmdb"),
    )


def get_mediaitem(
    server_type: str,
    item: dict[str, Any],
    generate_guids: bool,
    generate_locations: bool,
) -> MediaItem:
    user_data = item.get("UserData", {})
    last_played_date = user_data.get("LastPlayedDate")

    viewed_date = datetime.today()
    if last_played_date:
        viewed_date = datetime.fromisoformat(last_played_date.replace("Z", "+00:00"))

    return MediaItem(
        identifiers=extract_identifiers_from_item(
            server_type, item, generate_guids, generate_locations
        ),
        status=WatchedStatus(
            completed=user_data.get("Played"),
            time=floor(user_data.get("PlaybackPositionTicks", 0) / 10000),
            viewed_date=viewed_date,
        ),
    )


class JellyfinEmby:
    def __init__(
        self,
        app_settings: AppSettings,
        server_settings: JellyfinSettings | EmbySettings,
        server_type: Literal["Jellyfin", "Emby"],
        headers: dict[str, str],
    ) -> None:
        self.app_settings: AppSettings = app_settings
        self.server_settings = server_settings

        if server_type not in ["Jellyfin", "Emby"]:
            raise Exception(f"Server type {server_type} not supported")
        self.server_type: str = server_type
        self.headers: dict[str, str] = headers

        if not server_settings.baseurl:
            raise Exception(f"{self.server_type} base_url not set")

        self.session = requests.Session()
        self.users: dict[str, str] = self.get_users()
        self.server_name: str = self.info(name_only=True)
        self.server_version: Version = self.info(version_only=True)
        self.update_partial: bool = self.is_partial_update_supported(
            self.server_version
        )

    def query(
        self,
        query: str,
        query_type: Literal["get", "post"],
        identifiers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any] | None:
        try:
            results = None

            if query_type == "get":
                response = self.session.get(
                    self.server_settings.baseurl + query,
                    headers=self.headers,
                    timeout=self.app_settings.request_timeout,
                )
                if response.status_code not in [200, 204]:
                    raise Exception(
                        f"Query failed with status {response.status_code} {response.reason}"
                    )
                if response.status_code == 204:
                    results = None
                else:
                    results = response.json()

            elif query_type == "post":
                response = self.session.post(
                    self.server_settings.baseurl + query,
                    headers=self.headers,
                    json=json,
                    timeout=self.app_settings.request_timeout,
                )
                if response.status_code not in [200, 204]:
                    raise Exception(
                        f"Query failed with status {response.status_code} {response.reason}"
                    )
                if response.status_code == 204:
                    results = None
                else:
                    results = response.json()

            if results:
                if not isinstance(results, list) and not isinstance(results, dict):
                    raise Exception("Query result is not of type list or dict")

            # append identifiers to results
            if identifiers and isinstance(results, dict):
                results["Identifiers"] = identifiers

            return results

        except Exception as e:
            logger.error(
                f"{self.server_type}: Query {query_type} {query}\nResults {results}\n{e}",
            )
            raise Exception(e)

    def info(
        self, name_only: bool = False, version_only: bool = False
    ) -> str | Version | None:
        try:
            query_string = "/System/Info/Public"

            response = self.query(query_string, "get")

            if response and isinstance(response, dict):
                if name_only:
                    return response.get("ServerName")
                elif version_only:
                    return parse(response.get("Version", ""))

                return f"{self.server_type} {response.get('ServerName')}: {response.get('Version')}"
            else:
                return None

        except Exception as e:
            logger.error(f"{self.server_type}: Get server name failed {e}")
            raise Exception(e)

    def get_users(self) -> dict[str, str]:
        try:
            users: dict[str, str] = {}

            query_string = "/Users"
            response = self.query(query_string, "get")

            if response and isinstance(response, list):
                for user in response:
                    users[user["Name"]] = user["Id"]

            return users
        except Exception as e:
            logger.error(f"{self.server_type}: Get users failed {e}")
            raise Exception(e)

    def get_libraries(self) -> dict[str, str]:
        libraries: dict[str, str] = {}
        for user in self.users.items():
            libraries.update(self.get_user_libraries(user))
        return libraries

    def get_user_libraries(self, user: tuple[str, str]) -> dict[str, str]:
        """Return supported libraries visible to this specific user."""
        user_name, user_id = user
        libraries: dict[str, str] = {}
        user_libraries = self.query(f"/Users/{user_id}/Views", "get")

        if not user_libraries or not isinstance(user_libraries, dict):
            logger.error(
                f"{self.server_type}: Failed to get libraries for {user_name}"
            )
            return libraries

        logger.debug(
            f"{self.server_type}: All Libraries for {user_name} {[library.get('Name') for library in user_libraries.get('Items', [])]}"
        )

        for library in user_libraries.get("Items", []):
            library_title = library.get("Name")
            library_type = library.get("CollectionType")

            # If collection type is not set, fallback based on media files
            if not library_type:
                library_id = library.get("Id")
                # Get first 100 items in library
                library_items = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?ParentId={library_id}&Recursive=True&excludeItemTypes=Folder&limit=100",
                    "get",
                )

                if not library_items or not isinstance(library_items, dict):
                    logger.debug(
                        f"{self.server_type}: Failed to get library items for {user_name} {library_title}"
                    )
                    continue

                all_types = set(
                    [x.get("Type") for x in library_items.get("Items", [])]
                )
                types = set([x for x in all_types if x in ["Movie", "Episode"]])

                if not len(types) == 1:
                    logger.debug(
                        f"{self.server_type}: Skipping Library {library_title} didn't find just a single type, found {all_types}",
                    )
                    continue

                library_type = types.pop()

                library_type = (
                    "movies" if library_type == "Movie" else "tvshows"
                )

            if library_type not in ["movies", "tvshows"]:
                logger.debug(
                    f"{self.server_type}: Skipping Library {library_title} found type {library_type}",
                )
                continue

            libraries[library_title] = library_type

        return libraries

    def get_user_library_watched(
        self,
        user_name: str,
        user_id: str,
        library_type: Literal["movies", "tvshows"],
        library_id: str,
        library_title: str,
    ) -> LibraryData:
        user_name = normalize_name(user_name)
        try:
            logger.info(
                f"{self.server_type}: Generating watched for {user_name} in library {library_title}",
            )
            watched = LibraryData(title=library_title)

            # Movies
            if library_type == "movies":
                movie_items = []
                watched_items = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?ParentId={library_id}&Filters=IsPlayed&IncludeItemTypes=Movie&Recursive=True&Fields=ItemCounts,ProviderIds,Path,UserDataLastPlayedDate",
                    "get",
                )

                if watched_items and isinstance(watched_items, dict):
                    movie_items += watched_items.get("Items", [])

                in_progress_items = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?ParentId={library_id}&Filters=IsResumable&IncludeItemTypes=Movie&Recursive=True&Fields=ItemCounts,ProviderIds,Path,UserDataLastPlayedDate",
                    "get",
                )

                if in_progress_items and isinstance(in_progress_items, dict):
                    movie_items += in_progress_items.get("Items", [])

                for movie in movie_items:
                    # Skip if theres no user data which means the movie has not been watched
                    if not movie.get("UserData"):
                        continue

                    # Skip if theres no media tied to the movie
                    if not movie.get("MediaSources") and not movie.get("Path"):
                        continue

                    # Skip if not watched or watched less than a minute
                    if (
                        movie["UserData"].get("Played")
                        or movie["UserData"].get("PlaybackPositionTicks", 0) > 600000000
                    ):
                        watched.movies.append(
                            get_mediaitem(
                                self.server_type,
                                movie,
                                self.app_settings.generate_guids,
                                self.app_settings.generate_locations,
                            )
                        )

            # TV Shows
            if library_type == "tvshows":
                # Retrieve a list of watched TV shows
                all_shows = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?ParentId={library_id}&isPlaceHolder=false&IncludeItemTypes=Series&Recursive=True&Fields=ProviderIds,Path,RecursiveItemCount",
                    "get",
                )

                if not all_shows or not isinstance(all_shows, dict):
                    logger.debug(
                        f"{self.server_type}: Failed to get shows for {user_name} in {library_title}"
                    )
                    return watched

                # Fetch series IDs that have resumable (partially watched) episodes
                resumable_episodes = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?ParentId={library_id}&Filters=IsResumable&IncludeItemTypes=Episode&Recursive=True&Fields=SeriesId",
                    "get",
                )
                resumable_series_ids = set()
                if resumable_episodes and isinstance(resumable_episodes, dict):
                    for ep in resumable_episodes.get("Items", []):
                        series_id = ep.get("SeriesId")
                        if series_id:
                            resumable_series_ids.add(series_id)

                # Filter the list of shows to only include those that have been partially or fully watched
                watched_shows_filtered = []
                for show in all_shows.get("Items", []):
                    if not show.get("UserData"):
                        continue

                    # Include shows with resumable episodes even if none are fully played
                    if show.get("Id") in resumable_series_ids:
                        watched_shows_filtered.append(show)
                        continue

                    # Jellyfin can report a played series with an unavailable
                    # aggregate episode count for custom libraries.
                    if show["UserData"].get("Played"):
                        watched_shows_filtered.append(show)
                        continue

                    played_percentage = show["UserData"].get("PlayedPercentage")
                    if played_percentage is None:
                        # Emby no longer shows PlayedPercentage
                        total_episodes = show.get("RecursiveItemCount")
                        unplayed_episodes = show["UserData"].get("UnplayedItemCount")

                        if total_episodes is None or total_episodes <= 0:
                            # Failed to get total count of episodes
                            continue

                        if (
                            unplayed_episodes is not None
                            and unplayed_episodes < total_episodes
                        ):
                            watched_shows_filtered.append(show)
                    else:
                        if played_percentage > 0:
                            watched_shows_filtered.append(show)

                # Retrieve the watched/partially watched list of episodes of each watched show
                for show in watched_shows_filtered:
                    show_name = show.get("Name")
                    show_guids = {
                        k.lower(): v for k, v in show.get("ProviderIds", {}).items()
                    }
                    show_locations = (
                        tuple([filename_from_any_path(show["Path"])])
                        if show.get("Path")
                        else tuple()
                    )

                    show_episodes = self.query(
                        f"/Shows/{show.get('Id')}/Episodes"
                        + f"?userId={user_id}&isPlaceHolder=false&Fields=ProviderIds,Path,UserDataLastPlayedDate",
                        "get",
                    )

                    if not show_episodes or not isinstance(show_episodes, dict):
                        logger.debug(
                            f"{self.server_type}: Failed to get episodes for {user_name} {library_title} {show_name}"
                        )
                        continue

                    # Iterate through the episodes
                    # Create a list to store the episodes
                    episode_mediaitem = []
                    for episode in show_episodes.get("Items", []):
                        if not episode.get("UserData"):
                            continue

                        if not episode.get("MediaSources") and not episode.get("Path"):
                            continue

                        # If watched or watched more than a minute
                        if (
                            episode["UserData"].get("Played")
                            or episode["UserData"].get("PlaybackPositionTicks", 0)
                            > 600000000
                        ):
                            episode_mediaitem.append(
                                get_mediaitem(
                                    self.server_type,
                                    episode,
                                    self.app_settings.generate_guids,
                                    self.app_settings.generate_locations,
                                )
                            )

                    if episode_mediaitem:
                        watched.series.append(
                            Series(
                                identifiers=MediaIdentifiers(
                                    title=show.get("Name"),
                                    locations=show_locations,
                                    imdb_id=show_guids.get("imdb"),
                                    tvdb_id=show_guids.get("tvdb"),
                                    tmdb_id=show_guids.get("tmdb"),
                                ),
                                episodes=episode_mediaitem,
                            )
                        )

            return watched
        except Exception as e:
            logger.error(
                f"{self.server_type}: Failed to get watched for {user_name} in library {library_title}, Error: {e}",
            )

            logger.error(traceback.format_exc())
            return LibraryData(title=library_title)

    def get_watched(
        self,
        users: dict[str, str],
        sync_libraries: list[str],
        users_watched: dict[str, UserData] | None = None,
        *,
        library_types: dict[str, str] | None = None,
    ) -> dict[str, UserData]:
        try:
            if not users_watched:
                users_watched: dict[str, UserData] = {}
            sync_library_names = {normalize_name(name) for name in sync_libraries}
            discovered_types = {
                normalize_name(name): kind for name, kind in (library_types or {}).items()
            }

            for user_name, user_id in users.items():
                user_key = normalize_name(user_name)
                if user_key not in users_watched:
                    users_watched[user_key] = UserData()

                all_libraries = self.query(f"/Users/{user_id}/Views", "get")
                if not all_libraries or not isinstance(all_libraries, dict):
                    logger.debug(
                        f"{self.server_type}: Failed to get all libraries for {user_name}"
                    )
                    continue

                for library in all_libraries.get("Items", []):
                    library_id = library.get("Id")
                    library_title = library.get("Name")
                    library_type = library.get("CollectionType") or discovered_types.get(
                        normalize_name(library_title) if library_title else ""
                    )

                    if not library_id or not library_title or not library_type:
                        logger.debug(
                            f"{self.server_type}: Failed to get library data for {user_name} {library_title}"
                        )
                        continue

                    if normalize_name(library_title) not in sync_library_names:
                        continue

                    if library_title in users_watched[user_key].libraries:
                        logger.info(
                            f"{self.server_type}: {user_name} {library_title} watched history has already been gathered, skipping"
                        )
                        continue

                    if library_type != "movies" and library_type != "tvshows":
                        continue

                    # Get watched for user
                    library_data = self.get_user_library_watched(
                        user_name,
                        user_id,
                        "movies" if library_type == "movies" else "tvshows",
                        library_id,
                        library_title,
                    )

                    if user_key not in users_watched:
                        users_watched[user_key] = UserData()

                    users_watched[user_key].libraries[library_title] = (
                        library_data
                    )

            return users_watched
        except Exception as e:
            logger.error(f"{self.server_type}: Failed to get watched, Error: {e}")
            return {}

    def update_user_watched(
        self,
        user_name: str,
        user_id: str,
        library_data: LibraryData,
        library_name: str,
        library_id: str,
        dryrun: bool,
    ) -> list[WatchedWriteOutcome]:
        outcomes: list[WatchedWriteOutcome] = []
        target_user = normalize_name(user_name)

        def optional_string(value: object) -> str | None:
            return str(value) if value is not None else None

        def add_outcome(
            status: WriteOutcomeStatus,
            media_item: MediaItem,
            *,
            completed: bool | None = None,
            target_identifiers: MediaIdentifiers | None = None,
            series_identifiers: MediaIdentifiers | None = None,
            target_item_id: object = None,
            reason: str | None = None,
        ) -> None:
            if status == "applied" and completed is not None:
                media_item = resulting_media_item(
                    media_item,
                    completed,
                    target_identifiers,
                )
            outcomes.append(
                WatchedWriteOutcome(
                    status=status,
                    target_user=target_user,
                    target_library=library_name,
                    media_item=media_item,
                    series_identifiers=series_identifiers,
                    target_user_id=user_id,
                    target_library_id=library_id,
                    target_item_id=optional_string(target_item_id),
                    reason=reason,
                )
            )

        # If there are no movies or shows to update, exit early.
        if not library_data.series and not library_data.movies:
            return outcomes

        logger.info(
            f"{self.server_type}: Updating watched for {user_name} in library {library_name}",
        )

        # Update movies.
        if library_data.movies:
            try:
                jellyfin_search = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?SortBy=SortName&SortOrder=Ascending&Recursive=True&ParentId={library_id}"
                    + "&Fields=ItemCounts,ProviderIds,Path&IncludeItemTypes=Movie",
                    "get",
                )
            except Exception as error:
                logger.debug(
                    f"{self.server_type}: Failed to get movies for {user_name} {library_name}: {error}"
                )
                jellyfin_search = None

            matched_movies: set[int] = set()
            if not jellyfin_search or not isinstance(jellyfin_search, dict):
                for movie in library_data.movies:
                    add_outcome("uncertain", movie, reason="movie discovery failed")
            else:
                for jellyfin_video in jellyfin_search.get("Items", []):
                    jelly_identifiers = extract_identifiers_from_item(
                        self.server_type,
                        jellyfin_video,
                        self.app_settings.generate_guids,
                        self.app_settings.generate_locations,
                    )
                    # Check each stored movie for a match.
                    for movie_index, stored_movie in enumerate(library_data.movies):
                        if not check_same_identifiers(
                            jelly_identifiers, stored_movie.identifiers
                        ):
                            continue

                        matched_movies.add(movie_index)
                        jellyfin_video_id = jellyfin_video.get("Id")
                        target_item_id = jellyfin_video_id
                        viewed_date: str = stored_movie.status.viewed_date.isoformat(
                            timespec="milliseconds"
                        ).replace("+00:00", "Z")

                        if stored_movie.status.completed:
                            msg = f"{self.server_type}: {jellyfin_video.get('Name')} as watched for {user_name} in {library_name}"
                            if not dryrun:
                                user_data_payload: dict[str, Any] = {
                                    "PlayCount": 1,
                                    "Played": True,
                                    "PlaybackPositionTicks": 0,
                                    "LastPlayedDate": viewed_date,
                                }
                                try:
                                    if jellyfin_video_id is None:
                                        raise ValueError("destination item has no ID")
                                    self.query(
                                        f"/Users/{user_id}/Items/{jellyfin_video_id}/UserData",
                                        "post",
                                        json=user_data_payload,
                                    )
                                except Exception as error:
                                    logger.error(
                                        f"{self.server_type}: Failed to mark {jellyfin_video.get('Name')} as watched, Error: {error}"
                                    )
                                    add_outcome(
                                        "failed",
                                        stored_movie,
                                        completed=True,
                                        target_item_id=target_item_id,
                                        reason=str(error),
                                    )
                                    break

                            logger.success(f"{'[DRYRUN] ' if dryrun else ''}{msg}")
                            log_marked(
                                self.server_type,
                                self.server_name,
                                user_name,
                                library_name,
                                jellyfin_video.get("Name"),
                                mark_file=self.app_settings.mark_file,
                            )
                            add_outcome(
                                "skipped" if dryrun else "applied",
                                stored_movie,
                                completed=True,
                                target_identifiers=jelly_identifiers,
                                target_item_id=target_item_id,
                                reason="dry-run" if dryrun else None,
                            )
                        elif self.update_partial:
                            msg = f"{self.server_type}: {jellyfin_video.get('Name')} as partially watched for {floor(stored_movie.status.time / 60_000)} minutes for {user_name} in {library_name}"
                            if not dryrun:
                                user_data_payload = {
                                    "PlayCount": 0,
                                    "Played": False,
                                    "PlaybackPositionTicks": stored_movie.status.time
                                    * 10_000,
                                    "LastPlayedDate": viewed_date,
                                }
                                try:
                                    if jellyfin_video_id is None:
                                        raise ValueError("destination item has no ID")
                                    self.query(
                                        f"/Users/{user_id}/Items/{jellyfin_video_id}/UserData",
                                        "post",
                                        json=user_data_payload,
                                    )
                                except Exception as error:
                                    logger.error(
                                        f"{self.server_type}: Failed to update {jellyfin_video.get('Name')} timeline, Error: {error}"
                                    )
                                    add_outcome(
                                        "failed",
                                        stored_movie,
                                        completed=False,
                                        target_item_id=target_item_id,
                                        reason=str(error),
                                    )
                                    break

                            logger.success(f"{'[DRYRUN] ' if dryrun else ''}{msg}")
                            log_marked(
                                self.server_type,
                                self.server_name,
                                user_name,
                                library_name,
                                jellyfin_video.get("Name"),
                                duration=floor(stored_movie.status.time / 60_000),
                                mark_file=self.app_settings.mark_file,
                            )
                            add_outcome(
                                "skipped" if dryrun else "applied",
                                stored_movie,
                                completed=False,
                                target_identifiers=jelly_identifiers,
                                target_item_id=target_item_id,
                                reason="dry-run" if dryrun else None,
                            )
                        else:
                            add_outcome(
                                "unsupported",
                                stored_movie,
                                target_item_id=target_item_id,
                                reason="partial updates are unsupported",
                            )
                        break

                for movie_index, stored_movie in enumerate(library_data.movies):
                    if movie_index not in matched_movies:
                        add_outcome("skipped", stored_movie, reason="media not found")

        # Update TV Shows (series/episodes).
        if library_data.series:
            try:
                jellyfin_search = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?SortBy=SortName&SortOrder=Ascending&Recursive=True&ParentId={library_id}"
                    + "&Fields=ItemCounts,ProviderIds,Path&IncludeItemTypes=Series",
                    "get",
                )
            except Exception as error:
                logger.debug(
                    f"{self.server_type}: Failed to get shows for {user_name} {library_name}: {error}"
                )
                jellyfin_search = None

            matched_episodes: set[tuple[int, int]] = set()
            if not jellyfin_search or not isinstance(jellyfin_search, dict):
                for series in library_data.series:
                    for episode in series.episodes:
                        add_outcome(
                            "uncertain",
                            episode,
                            series_identifiers=series.identifiers,
                            reason="show discovery failed",
                        )
            else:
                jellyfin_shows = [x for x in jellyfin_search.get("Items", [])]
                for jellyfin_show in jellyfin_shows:
                    jellyfin_show_identifiers = extract_identifiers_from_item(
                        self.server_type,
                        jellyfin_show,
                        self.app_settings.generate_guids,
                        self.app_settings.generate_locations,
                    )
                    # Try to find a matching series in the stored library.
                    for series_index, stored_series in enumerate(library_data.series):
                        if not check_same_identifiers(
                            jellyfin_show_identifiers, stored_series.identifiers
                        ):
                            continue

                        logger.trace(
                            f"Found matching show for '{jellyfin_show.get('Name')}'",
                        )
                        jellyfin_show_id = jellyfin_show.get("Id")
                        try:
                            if jellyfin_show_id is None:
                                raise ValueError("destination show has no ID")
                            jellyfin_episodes = self.query(
                                f"/Shows/{jellyfin_show_id}/Episodes"
                                + f"?userId={user_id}&Fields=ItemCounts,ProviderIds,Path",
                                "get",
                            )
                        except Exception as error:
                            logger.debug(
                                f"{self.server_type}: Failed to get episodes for {user_name} {library_name} {jellyfin_show.get('Name')}: {error}"
                            )
                            jellyfin_episodes = None

                        if not jellyfin_episodes or not isinstance(
                            jellyfin_episodes, dict
                        ):
                            for episode_index, stored_ep in enumerate(
                                stored_series.episodes
                            ):
                                if (series_index, episode_index) not in matched_episodes:
                                    add_outcome(
                                        "uncertain",
                                        stored_ep,
                                        series_identifiers=stored_series.identifiers,
                                        reason="episode discovery failed",
                                    )
                            break

                        for jellyfin_episode in jellyfin_episodes.get("Items", []):
                            jellyfin_episode_identifiers = extract_identifiers_from_item(
                                self.server_type,
                                jellyfin_episode,
                                self.app_settings.generate_guids,
                                self.app_settings.generate_locations,
                            )
                            for episode_index, stored_ep in enumerate(
                                stored_series.episodes
                            ):
                                if not check_same_identifiers(
                                    jellyfin_episode_identifiers,
                                    stored_ep.identifiers,
                                ):
                                    continue

                                matched_episodes.add((series_index, episode_index))
                                jellyfin_episode_id = jellyfin_episode.get("Id")
                                target_item_id = jellyfin_episode_id
                                viewed_date: str = stored_ep.status.viewed_date.isoformat(
                                    timespec="milliseconds"
                                ).replace("+00:00", "Z")
                                episode_name = (
                                    f"{jellyfin_episode.get('SeriesName')} "
                                    f"{jellyfin_episode.get('SeasonName')} Episode "
                                    f"{jellyfin_episode.get('IndexNumber')} "
                                    f"{jellyfin_episode.get('Name')}"
                                )

                                if stored_ep.status.completed:
                                    msg = (
                                        f"{self.server_type}: {episode_name}"
                                        + f" as watched for {user_name} in {library_name}"
                                    )
                                    if not dryrun:
                                        user_data_payload = {
                                            "PlayCount": 1,
                                            "Played": True,
                                            "PlaybackPositionTicks": 0,
                                            "LastPlayedDate": viewed_date,
                                        }
                                        try:
                                            if jellyfin_episode_id is None:
                                                raise ValueError(
                                                    "destination episode has no ID"
                                                )
                                            self.query(
                                                f"/Users/{user_id}/Items/{jellyfin_episode_id}/UserData",
                                                "post",
                                                json=user_data_payload,
                                            )
                                        except Exception as error:
                                            logger.error(
                                                f"{self.server_type}: Failed to mark {episode_name} as watched, Error: {error}"
                                            )
                                            add_outcome(
                                                "failed",
                                                stored_ep,
                                                completed=True,
                                                series_identifiers=stored_series.identifiers,
                                                target_item_id=target_item_id,
                                                reason=str(error),
                                            )
                                            break

                                    logger.success(
                                        f"{'[DRYRUN] ' if dryrun else ''}{msg}"
                                    )
                                    log_marked(
                                        self.server_type,
                                        self.server_name,
                                        user_name,
                                        library_name,
                                        jellyfin_episode.get("SeriesName"),
                                        jellyfin_episode.get("Name"),
                                        mark_file=self.app_settings.mark_file,
                                    )
                                    add_outcome(
                                        "skipped" if dryrun else "applied",
                                        stored_ep,
                                        completed=True,
                                        target_identifiers=jellyfin_episode_identifiers,
                                        series_identifiers=jellyfin_show_identifiers,
                                        target_item_id=target_item_id,
                                        reason="dry-run" if dryrun else None,
                                    )
                                elif self.update_partial:
                                    msg = (
                                        f"{self.server_type}: {episode_name}"
                                        + f" as partially watched for {floor(stored_ep.status.time / 60_000)} minutes for {user_name} in {library_name}"
                                    )
                                    if not dryrun:
                                        user_data_payload = {
                                            "PlayCount": 0,
                                            "Played": False,
                                            "PlaybackPositionTicks": stored_ep.status.time
                                            * 10_000,
                                            "LastPlayedDate": viewed_date,
                                        }
                                        try:
                                            if jellyfin_episode_id is None:
                                                raise ValueError(
                                                    "destination episode has no ID"
                                                )
                                            self.query(
                                                f"/Users/{user_id}/Items/{jellyfin_episode_id}/UserData",
                                                "post",
                                                json=user_data_payload,
                                            )
                                        except Exception as error:
                                            logger.error(
                                                f"{self.server_type}: Failed to update {episode_name} timeline, Error: {error}"
                                            )
                                            add_outcome(
                                                "failed",
                                                stored_ep,
                                                completed=False,
                                                series_identifiers=stored_series.identifiers,
                                                target_item_id=target_item_id,
                                                reason=str(error),
                                            )
                                            break

                                    logger.success(
                                        f"{'[DRYRUN] ' if dryrun else ''}{msg}"
                                    )
                                    log_marked(
                                        self.server_type,
                                        self.server_name,
                                        user_name,
                                        library_name,
                                        jellyfin_episode.get("SeriesName"),
                                        jellyfin_episode.get("Name"),
                                        duration=floor(stored_ep.status.time / 60_000),
                                        mark_file=self.app_settings.mark_file,
                                    )
                                    add_outcome(
                                        "skipped" if dryrun else "applied",
                                        stored_ep,
                                        completed=False,
                                        target_identifiers=jellyfin_episode_identifiers,
                                        series_identifiers=jellyfin_show_identifiers,
                                        target_item_id=target_item_id,
                                        reason="dry-run" if dryrun else None,
                                    )
                                else:
                                    add_outcome(
                                        "unsupported",
                                        stored_ep,
                                        series_identifiers=stored_series.identifiers,
                                        target_item_id=target_item_id,
                                        reason="partial updates are unsupported",
                                    )
                                break
                        break

                for series_index, stored_series in enumerate(library_data.series):
                    for episode_index, stored_ep in enumerate(stored_series.episodes):
                        if (series_index, episode_index) not in matched_episodes:
                            add_outcome(
                                "skipped",
                                stored_ep,
                                series_identifiers=stored_series.identifiers,
                                reason="media not found",
                            )

        return outcomes

    def _resolve_local_users(
        self, source_server: str, source_user: str
    ) -> list[tuple[str, str]]:
        """
        Resolve a source-server username to every matching local user.

        Candidate names on this server come from the settings model
        (sync_targets_for_user — explicit user_mappings aliases plus the
        implicit same-username fallback). Every candidate matching one of this
        server's actual users is returned so one-to-many mappings reach every
        target account.
        """
        this_server = self.server_settings.name
        candidates = self.app_settings.sync_targets_for_user(
            source_server, source_user, this_server
        )
        candidates_normalized = {normalize_name(c) for c in candidates}
        matched: list[tuple[str, str]] = []

        for key, user_id in self.users.items():
            if normalize_name(key) in candidates_normalized:
                matched.append((key, user_id))

        return matched

    def _resolve_local_libraries(
        self,
        source_server: str,
        source_library: str,
        available_libraries: list[dict[str, Any]],
    ) -> list[tuple[str, str]]:
        """
        Resolve a source-server library name to every matching local library.

        Candidates come from sync_targets_for_library; every candidate present
        in `available_libraries` (matched on Name, case-insensitive) is
        returned, preserving the server's actual Name casing.
        """
        this_server = self.server_settings.name
        candidates = self.app_settings.sync_targets_for_library(
            source_server, source_library, this_server
        )
        candidates_normalized = {normalize_name(c) for c in candidates}
        matched: list[tuple[str, str]] = []

        for library in available_libraries:
            name = library.get("Name")
            lib_id = library.get("Id")
            if name and lib_id and normalize_name(name) in candidates_normalized:
                matched.append((name, lib_id))

        return matched

    def update_watched(
        self,
        watched_list: dict[str, UserData] | list[WatchedUpdate],
        source_server_name: str,
    ) -> list[WatchedWriteOutcome]:
        """
        Apply watch state from `watched_list` onto this server.

        User and library correspondence is resolved through the settings model
        via source_server's configured name, so explicit mappings and the
        implicit same-name fallback are both honored. A list of
        :class:`WatchedUpdate` values is scoped to one target user and library;
        a source-shaped dictionary is expanded to that form for compatibility.
        A write requires both the source user and source library to pass
        policy; the coarse server direction only admits the pair for
        processing.
        """
        dryrun = self.app_settings.dryrun
        write_outcomes: list[WatchedWriteOutcome] = []

        pending_updates = (
            watched_list
            if isinstance(watched_list, list)
            else expand_watched_updates(
                watched_list,
                source_server_name,
                self.server_settings.name,
                self.app_settings,
            )
        )

        for update in pending_updates:
            user = update.source_user
            if not self.app_settings.should_sync_user(
                user, source_server_name, self.server_settings.name
            ):
                logger.debug(
                    f"{self.server_type}: {user} (from {source_server_name}) skipped"
                )
                continue

            target_user_normalized = normalize_name(update.target_user)
            resolved_users = [
                resolved_user
                for resolved_user in self._resolve_local_users(
                    source_server_name, user
                )
                if normalize_name(resolved_user[0]) == target_user_normalized
            ]
            if not resolved_users:
                logger.info(
                    f"{self.server_type}: {user} (from {source_server_name}) not found on this server, skipping"
                )
                continue

            for user_name, user_id in resolved_users:
                jellyfin_libraries = self.query(
                    f"/Users/{user_id}/Views",
                    "get",
                )

                if not jellyfin_libraries or not isinstance(jellyfin_libraries, dict):
                    logger.debug(
                        f"{self.server_type}: Failed to get libraries for {user_name}"
                    )
                    continue

                available_libraries = [x for x in jellyfin_libraries.get("Items", [])]

                if not self.app_settings.should_sync_library(
                    update.source_library, source_server_name, self.server_settings.name
                ):
                    logger.debug(
                        f"{self.server_type}: {update.source_library} (from {source_server_name}) skipped"
                    )
                    continue

                target_library_normalized = normalize_name(update.target_library)
                resolved_libraries = [
                    resolved_library
                    for resolved_library in self._resolve_local_libraries(
                        source_server_name,
                        update.source_library,
                        available_libraries,
                    )
                    if normalize_name(resolved_library[0]) == target_library_normalized
                ]
                if not resolved_libraries:
                    logger.info(
                        f"{self.server_type}: Library {update.source_library} (from {source_server_name}) not found in library list",
                    )
                    continue

                for resolved_library_name, library_id in resolved_libraries:
                    try:
                        outcomes = self.update_user_watched(
                            user_name,
                            user_id,
                            update.library_data,
                            resolved_library_name,
                            library_id,
                            dryrun,
                        )
                        if outcomes:
                            write_outcomes.extend(outcomes)
                    except Exception as e:
                        logger.error(
                            f"{self.server_type}: Error updating watched for {user_name} in {resolved_library_name}, {e}",
                        )

        return write_outcomes
