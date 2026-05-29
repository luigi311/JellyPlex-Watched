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
        base_url: str,
        token: str,
        headers: dict[str, str],
    ) -> None:
        self.app_settings: AppSettings = app_settings
        self.server_settings = server_settings

        if server_type not in ["Jellyfin", "Emby"]:
            raise Exception(f"Server type {server_type} not supported")
        self.server_type: str = server_type
        self.base_url: str = base_url
        self.token: str = token
        self.headers: dict[str, str] = headers

        if not self.base_url:
            raise Exception(f"{self.server_type} base_url not set")

        if not self.token:
            raise Exception(f"{self.server_type} token not set")

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
                    self.base_url + query,
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
                    self.base_url + query,
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
        try:
            libraries: dict[str, str] = {}

            # Theres no way to get all libraries so individually get list of libraries from all users
            users = self.get_users()

            for user_name, user_id in users.items():
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
        except Exception as e:
            logger.error(f"{self.server_type}: Get libraries failed {e}")
            raise Exception(e)

    def get_user_library_watched(
        self,
        user_name: str,
        user_id: str,
        library_type: Literal["movies", "tvshows"],
        library_id: str,
        library_title: str,
    ) -> LibraryData:
        user_name = user_name.lower()
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

                    played_percentage = show["UserData"].get("PlayedPercentage")
                    if played_percentage is None:
                        # Emby no longer shows PlayedPercentage
                        total_episodes = show.get("RecursiveItemCount")
                        unplayed_episodes = show["UserData"].get("UnplayedItemCount")

                        if total_episodes is None:
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

            logger.info(
                f"{self.server_type}: Finished getting watched for {user_name} in library {library_title}",
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
    ) -> dict[str, UserData]:
        try:
            if not users_watched:
                users_watched: dict[str, UserData] = {}

            for user_name, user_id in users.items():
                if user_name.lower() not in users_watched:
                    users_watched[user_name.lower()] = UserData()

                all_libraries = self.query(f"/Users/{user_id}/Views", "get")
                if not all_libraries or not isinstance(all_libraries, dict):
                    logger.debug(
                        f"{self.server_type}: Failed to get all libraries for {user_name}"
                    )
                    continue

                for library in all_libraries.get("Items", []):
                    library_id = library.get("Id")
                    library_title = library.get("Name")
                    library_type = library.get("CollectionType")

                    if not library_id or not library_title or not library_type:
                        logger.debug(
                            f"{self.server_type}: Failed to get library data for {user_name} {library_title}"
                        )
                        continue

                    if library_title not in sync_libraries:
                        continue

                    if library_title in users_watched[user_name.lower()].libraries:
                        logger.info(
                            f"{self.server_type}: {user_name} {library_title} watched history has already been gathered, skipping"
                        )
                        continue

                    # Get watched for user
                    library_data = self.get_user_library_watched(
                        user_name,
                        user_id,
                        library_type,
                        library_id,
                        library_title,
                    )

                    if user_name.lower() not in users_watched:
                        users_watched[user_name.lower()] = UserData()

                    users_watched[user_name.lower()].libraries[library_title] = (
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
    ) -> None:
        try:
            # If there are no movies or shows to update, exit early.
            if not library_data.series and not library_data.movies:
                return

            logger.info(
                f"{self.server_type}: Updating watched for {user_name} in library {library_name}",
            )

            # Update movies.
            if library_data.movies:
                jellyfin_search = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?SortBy=SortName&SortOrder=Ascending&Recursive=True&ParentId={library_id}"
                    + "&Fields=ItemCounts,ProviderIds,Path&IncludeItemTypes=Movie",
                    "get",
                )

                if not jellyfin_search or not isinstance(jellyfin_search, dict):
                    logger.debug(
                        f"{self.server_type}: Failed to get movies for {user_name} {library_name}"
                    )
                    return

                for jellyfin_video in jellyfin_search.get("Items", []):
                    jelly_identifiers = extract_identifiers_from_item(
                        self.server_type,
                        jellyfin_video,
                        self.app_settings.generate_guids,
                        self.app_settings.generate_locations,
                    )
                    # Check each stored movie for a match.
                    for stored_movie in library_data.movies:
                        if check_same_identifiers(
                            jelly_identifiers, stored_movie.identifiers
                        ):
                            jellyfin_video_id = jellyfin_video.get("Id")

                            viewed_date: str = (
                                stored_movie.status.viewed_date.isoformat(
                                    timespec="milliseconds"
                                ).replace("+00:00", "Z")
                            )

                            if stored_movie.status.completed:
                                msg = f"{self.server_type}: {jellyfin_video.get('Name')} as watched for {user_name} in {library_name}"
                                if not dryrun:
                                    user_data_payload: dict[str, Any] = {
                                        "PlayCount": 1,
                                        "Played": True,
                                        "PlaybackPositionTicks": 0,
                                        "LastPlayedDate": viewed_date,
                                    }
                                    self.query(
                                        f"/Users/{user_id}/Items/{jellyfin_video_id}/UserData",
                                        "post",
                                        json=user_data_payload,
                                    )

                                logger.success(f"{'[DRYRUN] ' if dryrun else ''}{msg}")
                                log_marked(
                                    self.server_type,
                                    self.server_name,
                                    user_name,
                                    library_name,
                                    jellyfin_video.get("Name"),
                                    mark_file=self.app_settings.mark_file,
                                )
                            elif self.update_partial:
                                msg = f"{self.server_type}: {jellyfin_video.get('Name')} as partially watched for {floor(stored_movie.status.time / 60_000)} minutes for {user_name} in {library_name}"

                                if not dryrun:
                                    user_data_payload: dict[str, Any] = {
                                        "PlayCount": 0,
                                        "Played": False,
                                        "PlaybackPositionTicks": stored_movie.status.time
                                        * 10_000,
                                        "LastPlayedDate": viewed_date,
                                    }
                                    self.query(
                                        f"/Users/{user_id}/Items/{jellyfin_video_id}/UserData",
                                        "post",
                                        json=user_data_payload,
                                    )

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
                        else:
                            logger.trace(
                                f"{self.server_type}: Skipping movie {jellyfin_video.get('Name')} as it is not in mark list for {user_name}",
                            )

            # Update TV Shows (series/episodes).
            if library_data.series:
                jellyfin_search = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?SortBy=SortName&SortOrder=Ascending&Recursive=True&ParentId={library_id}"
                    + "&Fields=ItemCounts,ProviderIds,Path&IncludeItemTypes=Series",
                    "get",
                )
                if not jellyfin_search or not isinstance(jellyfin_search, dict):
                    logger.debug(
                        f"{self.server_type}: Failed to get shows for {user_name} {library_name}"
                    )
                    return

                jellyfin_shows = [x for x in jellyfin_search.get("Items", [])]

                for jellyfin_show in jellyfin_shows:
                    jellyfin_show_identifiers = extract_identifiers_from_item(
                        self.server_type,
                        jellyfin_show,
                        self.app_settings.generate_guids,
                        self.app_settings.generate_locations,
                    )
                    # Try to find a matching series in your stored library.
                    for stored_series in library_data.series:
                        if check_same_identifiers(
                            jellyfin_show_identifiers, stored_series.identifiers
                        ):
                            logger.trace(
                                f"Found matching show for '{jellyfin_show.get('Name')}'",
                            )
                            # Now update episodes.
                            # Get the list of Plex episodes for this show.
                            jellyfin_show_id = jellyfin_show.get("Id")
                            jellyfin_episodes = self.query(
                                f"/Shows/{jellyfin_show_id}/Episodes"
                                + f"?userId={user_id}&Fields=ItemCounts,ProviderIds,Path",
                                "get",
                            )

                            if not jellyfin_episodes or not isinstance(
                                jellyfin_episodes, dict
                            ):
                                logger.debug(
                                    f"{self.server_type}: Failed to get episodes for {user_name} {library_name} {jellyfin_show.get('Name')}"
                                )
                                return

                            for jellyfin_episode in jellyfin_episodes.get("Items", []):
                                jellyfin_episode_identifiers = (
                                    extract_identifiers_from_item(
                                        self.server_type,
                                        jellyfin_episode,
                                        self.app_settings.generate_guids,
                                        self.app_settings.generate_locations,
                                    )
                                )
                                for stored_ep in stored_series.episodes:
                                    if check_same_identifiers(
                                        jellyfin_episode_identifiers,
                                        stored_ep.identifiers,
                                    ):
                                        jellyfin_episode_id = jellyfin_episode.get("Id")

                                        viewed_date: str = (
                                            stored_ep.status.viewed_date.isoformat(
                                                timespec="milliseconds"
                                            ).replace("+00:00", "Z")
                                        )

                                        if stored_ep.status.completed:
                                            msg = (
                                                f"{self.server_type}: {jellyfin_episode.get('SeriesName')} {jellyfin_episode.get('SeasonName')} Episode {jellyfin_episode.get('IndexNumber')} {jellyfin_episode.get('Name')}"
                                                + f" as watched for {user_name} in {library_name}"
                                            )
                                            if not dryrun:
                                                user_data_payload: dict[str, Any] = {
                                                    "PlayCount": 1,
                                                    "Played": True,
                                                    "PlaybackPositionTicks": 0,
                                                    "LastPlayedDate": viewed_date,
                                                }
                                                self.query(
                                                    f"/Users/{user_id}/Items/{jellyfin_episode_id}/UserData",
                                                    "post",
                                                    json=user_data_payload,
                                                )

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
                                        elif self.update_partial:
                                            msg = (
                                                f"{self.server_type}: {jellyfin_episode.get('SeriesName')} {jellyfin_episode.get('SeasonName')} Episode {jellyfin_episode.get('IndexNumber')} {jellyfin_episode.get('Name')}"
                                                + f" as partially watched for {floor(stored_ep.status.time / 60_000)} minutes for {user_name} in {library_name}"
                                            )

                                            if not dryrun:
                                                user_data_payload: dict[str, Any] = {
                                                    "PlayCount": 0,
                                                    "Played": False,
                                                    "PlaybackPositionTicks": stored_ep.status.time
                                                    * 10_000,
                                                    "LastPlayedDate": viewed_date,
                                                }
                                                self.query(
                                                    f"/Users/{user_id}/Items/{jellyfin_episode_id}/UserData",
                                                    "post",
                                                    json=user_data_payload,
                                                )

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
                                                duration=floor(
                                                    stored_ep.status.time / 60_000
                                                ),
                                                mark_file=self.app_settings.mark_file,
                                            )
                                    else:
                                        logger.trace(
                                            f"{self.server_type}: Skipping episode {jellyfin_episode.get('Name')} as it is not in mark list for {user_name}",
                                        )
                        else:
                            logger.trace(
                                f"{self.server_type}: Skipping show {jellyfin_show.get('Name')} as it is not in mark list for {user_name}",
                            )

        except Exception as e:
            logger.error(
                f"{self.server_type}: Error updating watched for {user_name} in library {library_name}, {e}",
            )

    def _resolve_local_user(
        self, source_server: str, source_user: str
    ) -> tuple[str, str] | None:
        """
        Resolve a source-server username to (user_name, user_id) on this
        server.

        Candidate names on this server come from the settings model
        (sync_targets_for_user — explicit user_mappings aliases plus the
        implicit same-username fallback). The first candidate matching one of
        this server's actual users (case-insensitive) wins. Returns None if no
        candidate matches.
        """
        this_server = self.server_settings.name
        candidates = self.app_settings.sync_targets_for_user(
            source_server, source_user, this_server
        )
        candidates_lc = {c.lower() for c in candidates}

        for key, user_id in self.users.items():
            if key.lower() in candidates_lc:
                return key, user_id

        return None

    def _resolve_local_library(
        self,
        source_server: str,
        source_library: str,
        available_libraries: list[dict[str, Any]],
    ) -> tuple[str, str] | None:
        """
        Resolve a source-server library name to (library_name, library_id) on
        this server.

        Candidates come from sync_targets_for_library; the first present in
        `available_libraries` (matched on Name, case-insensitive) is returned,
        preserving the server's actual Name casing.
        """
        this_server = self.server_settings.name
        candidates = self.app_settings.sync_targets_for_library(
            source_server, source_library, this_server
        )
        candidates_lc = {c.lower() for c in candidates}

        for library in available_libraries:
            name = library.get("Name")
            if name and name.lower() in candidates_lc:
                return name, library["Id"]

        return None

    def update_watched(
        self,
        watched_list: dict[str, UserData],
        source_server_name: str,
    ) -> None:
        """
        Apply watch state from `watched_list` (keyed by names as reported on
        `source_server`) onto this server.

        User and library correspondence is resolved through the settings model
        via source_server's configured name, so explicit mappings and the
        implicit same-name fallback are both honored. Fan-out is resolved
        upstream; each key here maps to a single user/library on this server.
        """
        dryrun = self.app_settings.dryrun

        for user, user_data in watched_list.items():
            resolved_user = self._resolve_local_user(source_server_name, user)
            if resolved_user is None:
                logger.info(
                    f"{self.server_type}: {user} (from {source_server_name}) not found on this server, skipping"
                )
                continue

            user_name, user_id = resolved_user

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

            for library_name in user_data.libraries:
                library_data = user_data.libraries[library_name]

                resolved_library = self._resolve_local_library(
                    source_server_name, library_name, available_libraries
                )
                if resolved_library is None:
                    logger.info(
                        f"{self.server_type}: Library {library_name} (from {source_server_name}) not found in library list",
                    )
                    continue

                resolved_library_name, library_id = resolved_library

                try:
                    self.update_user_watched(
                        user_name,
                        user_id,
                        library_data,
                        resolved_library_name,
                        library_id,
                        dryrun,
                    )
                except Exception as e:
                    logger.error(
                        f"{self.server_type}: Error updating watched for {user_name} in library {resolved_library_name}, {e}",
                    )
