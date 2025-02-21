# Functions for Jellyfin and Emby

import traceback
import os
from math import floor
from typing import Any, Literal
from dotenv import load_dotenv
import requests
from packaging.version import parse, Version

from src.functions import (
    logger,
    search_mapping,
    log_marked,
    str_to_bool,
)
from src.watched import (
    LibraryData,
    MediaIdentifiers,
    MediaItem,
    WatchedStatus,
    Series,
    UserData,
    check_same_identifiers,
)

load_dotenv(override=True)

generate_guids = str_to_bool(os.getenv("GENERATE_GUIDS", "True"))
generate_locations = str_to_bool(os.getenv("GENERATE_LOCATIONS", "True"))


def extract_identifiers_from_item(server_type, item: dict) -> MediaIdentifiers:
    title = item.get("Name", None)
    id = None
    if not title:
        id = item.get("Id")
        logger(f"{server_type}: Name not found in {id}", 1)

    guids = {}
    if generate_guids:
        guids = {k.lower(): v for k, v in item["ProviderIds"].items()}
        if not guids:
            logger(
                f"{server_type}: {title if title else id} has no guids",
                1,
            )

    locations = tuple()
    if generate_locations:
        if "Path" in item:
            locations = tuple([item.get("Path").split("/")[-1]])
        elif "MediaSources" in item:
            locations = tuple(
                [x["Path"].split("/")[-1] for x in item["MediaSources"] if "Path" in x]
            )

        if not locations:
            logger(f"{server_type}: {title if title else id} has no locations", 1)

    return MediaIdentifiers(
        title=title,
        locations=locations,
        imdb_id=guids.get("imdb", None),
        tvdb_id=guids.get("tvdb", None),
        tmdb_id=guids.get("tmdb", None),
    )


def get_mediaitem(server_type, item: dict) -> MediaItem:
    return MediaItem(
        identifiers=extract_identifiers_from_item(server_type, item),
        status=WatchedStatus(
            completed=item["UserData"]["Played"],
            time=floor(item["UserData"]["PlaybackPositionTicks"] / 10000),
        ),
    )


class JellyfinEmby:
    def __init__(
        self,
        server_type: Literal["Jellyfin", "Emby"],
        baseurl: str,
        token: str,
        headers: dict[str, str],
    ):
        if server_type not in ["Jellyfin", "Emby"]:
            raise Exception(f"Server type {server_type} not supported")
        self.server_type = server_type
        self.baseurl = baseurl
        self.token = token
        self.headers = headers
        self.timeout = int(os.getenv("REQUEST_TIMEOUT", 300))

        if not self.baseurl:
            raise Exception(f"{self.server_type} baseurl not set")

        if not self.token:
            raise Exception(f"{self.server_type} token not set")

        self.session = requests.Session()
        self.users = self.get_users()
        self.server_name = self.info(name_only=True)

    def query(
        self,
        query: str,
        query_type: Literal["get", "post"],
        identifiers: dict[str, str] | None = None,
        json: dict[str, float] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        try:
            results: (
                dict[str, list[Any] | dict[str, str]] | list[dict[str, Any]] | None
            ) = None

            if query_type == "get":
                response = self.session.get(
                    self.baseurl + query, headers=self.headers, timeout=self.timeout
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
                    self.baseurl + query,
                    headers=self.headers,
                    json=json,
                    timeout=self.timeout,
                )
                if response.status_code not in [200, 204]:
                    raise Exception(
                        f"Query failed with status {response.status_code} {response.reason}"
                    )
                if response.status_code == 204:
                    results = None
                else:
                    results = response.json()

            if results is not None:
                if not isinstance(results, list) and not isinstance(results, dict):
                    raise Exception("Query result is not of type list or dict")

            # append identifiers to results
            if identifiers and results:
                results["Identifiers"] = identifiers

            return results

        except Exception as e:
            logger(
                f"{self.server_type}: Query {query_type} {query}\nResults {results}\n{e}",
                2,
            )
            raise Exception(e)

    def info(
        self, name_only: bool = False, version_only: bool = False
    ) -> str | Version | None:
        try:
            query_string = "/System/Info/Public"

            response: dict[str, Any] = self.query(query_string, "get")

            if response:
                if name_only:
                    return response["ServerName"]
                elif version_only:
                    return parse(response["Version"])

                return f"{self.server_type} {response.get('ServerName')}: {response.get('Version')}"
            else:
                return None

        except Exception as e:
            logger(f"{self.server_type}: Get server name failed {e}", 2)
            raise Exception(e)

    def get_users(self) -> dict[str, str]:
        try:
            users: dict[str, str] = {}

            query_string = "/Users"
            response: list[dict[str, str | bool]] = self.query(query_string, "get")

            # If response is not empty
            if response:
                for user in response:
                    if isinstance(user["Name"], str) and isinstance(user["Id"], str):
                        users[user["Name"]] = user["Id"]

            return users
        except Exception as e:
            logger(f"{self.server_type}: Get users failed {e}", 2)
            raise Exception(e)

    def get_libraries(self) -> dict[str, str]:
        try:
            libraries = {}

            # Theres no way to get all libraries so individually get list of libraries from all users
            users = self.get_users()

            for _, user_id in users.items():
                user_libraries: dict = self.query(f"/Users/{user_id}/Views", "get")
                for library in user_libraries["Items"]:
                    library_title = library["Name"]
                    library_type = library.get("CollectionType")

                    if library_type not in ["movies", "tvshows"]:
                        logger(
                            f"{self.server_type}: Skipping Library {library_title} found type {library_type}",
                            1,
                        )
                        continue

                    libraries[library_title] = library_type

            return libraries
        except Exception as e:
            logger(f"{self.server_type}: Get libraries failed {e}", 2)
            raise Exception(e)

    def get_user_library_watched(
        self, user_name, user_id, library_type, library_id, library_title
    ) -> LibraryData:
        user_name = user_name.lower()
        try:
            logger(
                f"{self.server_type}: Generating watched for {user_name} in library {library_title}",
                0,
            )
            watched = LibraryData(title=library_title)

            # Movies
            if library_type == "Movie":
                watched_items = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?ParentId={library_id}&Filters=IsPlayed&IncludeItemTypes=Movie&Recursive=True&Fields=ItemCounts,ProviderIds,MediaSources",
                    "get",
                ).get("Items", [])

                in_progress_items = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?ParentId={library_id}&Filters=IsResumable&IncludeItemTypes=Movie&Recursive=True&Fields=ItemCounts,ProviderIds,MediaSources",
                    "get",
                ).get("Items", [])

                for movie in watched_items + in_progress_items:
                    # Skip if theres no user data which means the movie has not been watched
                    if "UserData" not in movie:
                        continue

                    # Skip if theres no media tied to the movie
                    if "MediaSources" not in movie or movie["MediaSources"] == {}:
                        continue

                    # Skip if not watched or watched less than a minute
                    if (
                        movie["UserData"]["Played"] == True
                        or movie["UserData"]["PlaybackPositionTicks"] > 600000000
                    ):
                        watched.movies.append(get_mediaitem(self.server_type, movie))

            # TV Shows
            if library_type in ["Series", "Episode"]:
                # Retrieve a list of watched TV shows
                watched_shows = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?ParentId={library_id}&isPlaceHolder=false&IncludeItemTypes=Series&Recursive=True&Fields=ProviderIds,Path,RecursiveItemCount",
                    "get",
                ).get("Items", [])

                # Filter the list of shows to only include those that have been partially or fully watched
                watched_shows_filtered = []
                for show in watched_shows:
                    if "UserData" not in show:
                        continue

                    if "PlayedPercentage" in show["UserData"]:
                        if show["UserData"]["PlayedPercentage"] > 0:
                            watched_shows_filtered.append(show)

                # Retrieve the watched/partially watched list of episodes of each watched show
                for show in watched_shows_filtered:
                    show_guids = {k.lower(): v for k, v in show["ProviderIds"].items()}
                    show_locations = (
                        tuple([show["Path"].split("/")[-1]])
                        if "Path" in show
                        else tuple()
                    )

                    show_episodes = self.query(
                        f"/Shows/{show['Id']}/Episodes"
                        + f"?userId={user_id}&isPlaceHolder=false&Fields=ProviderIds,MediaSources",
                        "get",
                    ).get("Items", [])

                    # Iterate through the episodes
                    # Create a list to store the episodes
                    episode_mediaitem = []
                    for episode in show_episodes:
                        if "UserData" not in episode:
                            continue

                        if (
                            "MediaSources" not in episode
                            or episode["MediaSources"] == {}
                        ):
                            continue

                        # If watched or watched more than a minute
                        if (
                            episode["UserData"]["Played"] == True
                            or episode["UserData"]["PlaybackPositionTicks"] > 600000000
                        ):
                            episode_mediaitem.append(
                                get_mediaitem(self.server_type, episode)
                            )

                    if episode_mediaitem:
                        watched.series.append(
                            Series(
                                identifiers=MediaIdentifiers(
                                    title=show.get("Name"),
                                    locations=show_locations,
                                    imdb_id=show_guids.get("imdb", None),
                                    tvdb_id=show_guids.get("tvdb", None),
                                    tmdb_id=show_guids.get("tmdb", None),
                                ),
                                episodes=episode_mediaitem,
                            )
                        )

            logger(
                f"{self.server_type}: Finished getting watched for {user_name} in library {library_title}",
                1,
            )

            return watched
        except Exception as e:
            logger(
                f"{self.server_type}: Failed to get watched for {user_name} in library {library_title}, Error: {e}",
                2,
            )

            logger(traceback.format_exc(), 2)
            return {}

    def get_watched(
        self, users: dict[str, str], sync_libraries: list[str]
    ) -> dict[str, UserData]:
        try:
            users_watched: dict[str, UserData] = {}

            for user_name, user_id in users.items():
                libraries = []

                all_libraries = self.query(f"/Users/{user_id}/Views", "get")
                for library in all_libraries["Items"]:
                    library_id = library["Id"]
                    library_title = library["Name"]

                    if library_title not in sync_libraries:
                        continue

                    identifiers: dict[str, str] = {
                        "library_id": library_id,
                        "library_title": library_title,
                    }
                    libraries.append(
                        self.query(
                            f"/Users/{user_id}/Items"
                            + f"?ParentId={library_id}&Filters=IsPlayed&Recursive=True&excludeItemTypes=Folder&limit=100",
                            "get",
                            identifiers=identifiers,
                        )
                    )

                for library in libraries:
                    if len(library["Items"]) == 0:
                        continue

                    library_id: str = library["Identifiers"]["library_id"]
                    library_title: str = library["Identifiers"]["library_title"]

                    # Get all library types excluding "Folder"
                    types = set(
                        [
                            x["Type"]
                            for x in library["Items"]
                            if x["Type"] in ["Movie", "Series", "Episode"]
                        ]
                    )

                    for library_type in types:
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
            logger(f"{self.server_type}: Failed to get watched, Error: {e}", 2)
            raise Exception(e)

    def update_user_watched(
        self,
        user_name: str,
        user_id: str,
        library_data: LibraryData,
        library_name: str,
        library_id: str,
        update_partial: bool,
        dryrun: bool,
    ):
        try:
            # If there are no movies or shows to update, exit early.
            if not library_data.series and not library_data.movies:
                return

            logger(
                f"{self.server_type}: Updating watched for {user_name} in library {library_name}",
                1,
            )

            # Update movies.
            if library_data.movies:
                jellyfin_search = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?SortBy=SortName&SortOrder=Ascending&Recursive=True&ParentId={library_id}"
                    + "&isPlayed=false&Fields=ItemCounts,ProviderIds,MediaSources&IncludeItemTypes=Movie",
                    "get",
                )
                for jellyfin_video in jellyfin_search["Items"]:
                    jelly_identifiers = extract_identifiers_from_item(
                        self.server_type, jellyfin_video
                    )
                    # Check each stored movie for a match.
                    for stored_movie in library_data.movies:
                        if check_same_identifiers(
                            jelly_identifiers, stored_movie.identifiers
                        ):
                            jellyfin_video_id = jellyfin_video["Id"]
                            if stored_movie.status.completed:
                                msg = f"{self.server_type}: {jellyfin_video.get('Name')} as watched for {user_name} in {library_name}"
                                if not dryrun:
                                    logger(msg, 5)
                                    self.query(
                                        f"/Users/{user_id}/PlayedItems/{jellyfin_video_id}",
                                        "post",
                                    )
                                else:
                                    logger(msg, 6)

                                log_marked(
                                    self.server_type,
                                    self.server_name,
                                    user_name,
                                    library_name,
                                    jellyfin_video.get("Name"),
                                )
                            elif update_partial:
                                msg = f"{self.server_type}: {jellyfin_video.get('Name')} as partially watched for {floor(stored_movie.status.time / 60_000)} minutes for {user_name} in {library_name}"

                                if not dryrun:
                                    logger(msg, 5)
                                    playback_position_payload = {
                                        "PlaybackPositionTicks": stored_movie.status.time
                                        * 10_000,
                                    }
                                    self.query(
                                        f"/Users/{user_id}/Items/{jellyfin_video_id}/UserData",
                                        "post",
                                        json=playback_position_payload,
                                    )
                                else:
                                    logger(msg, 6)

                                log_marked(
                                    self.server_type,
                                    self.server_name,
                                    user_name,
                                    library_name,
                                    jellyfin_video.get("Name"),
                                    duration=floor(stored_movie.status.time / 60_000),
                                )
                        else:
                            logger(
                                f"{self.server_type}: Skipping movie {jellyfin_video.get('Name')} as it is not in mark list for {user_name}",
                                3,
                            )

            # Update TV Shows (series/episodes).
            if library_data.series:
                jellyfin_search = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?SortBy=SortName&SortOrder=Ascending&Recursive=True&ParentId={library_id}"
                    + "&Fields=ItemCounts,ProviderIds,Path&IncludeItemTypes=Series",
                    "get",
                )
                jellyfin_shows = [x for x in jellyfin_search["Items"]]

                for jellyfin_show in jellyfin_shows:
                    jellyfin_show_identifiers = extract_identifiers_from_item(
                        self.server_type, jellyfin_show
                    )
                    # Try to find a matching series in your stored library.
                    for stored_series in library_data.series:
                        if check_same_identifiers(
                            jellyfin_show_identifiers, stored_series.identifiers
                        ):
                            logger(
                                f"Found matching show for '{jellyfin_show.get('Name')}'",
                                1,
                            )
                            # Now update episodes.
                            # Get the list of Plex episodes for this show.
                            jellyfin_show_id = jellyfin_show["Id"]
                            jellyfin_episodes = self.query(
                                f"/Shows/{jellyfin_show_id}/Episodes"
                                + f"?userId={user_id}&Fields=ItemCounts,ProviderIds,MediaSources",
                                "get",
                            )

                            for jellyfin_episode in jellyfin_episodes["Items"]:
                                jellyfin_episode_identifiers = (
                                    extract_identifiers_from_item(
                                        self.server_type, jellyfin_episode
                                    )
                                )
                                for stored_ep in stored_series.episodes:
                                    if check_same_identifiers(
                                        jellyfin_episode_identifiers,
                                        stored_ep.identifiers,
                                    ):
                                        jellyfin_episode_id = jellyfin_episode["Id"]
                                        if stored_ep.status.completed:
                                            msg = (
                                                f"{self.server_type}: {jellyfin_episode['SeriesName']} {jellyfin_episode['SeasonName']} Episode {jellyfin_episode.get('IndexNumber')} {jellyfin_episode.get('Name')}"
                                                + f" as watched for {user_name} in {library_name}"
                                            )
                                            if not dryrun:
                                                logger(msg, 5)
                                                self.query(
                                                    f"/Users/{user_id}/PlayedItems/{jellyfin_episode_id}",
                                                    "post",
                                                )
                                            else:
                                                logger(msg, 6)

                                            log_marked(
                                                self.server_type,
                                                self.server_name,
                                                user_name,
                                                library_name,
                                                jellyfin_episode.get("SeriesName"),
                                                jellyfin_episode.get("Name"),
                                            )
                                        elif update_partial:
                                            msg = (
                                                f"{self.server_type}: {jellyfin_episode['SeriesName']} {jellyfin_episode['SeasonName']} Episode {jellyfin_episode.get('IndexNumber')} {jellyfin_episode.get('Name')}"
                                                + f" as partially watched for {floor(stored_ep.status.time / 60_000)} minutes for {user_name} in {library_name}"
                                            )

                                            if not dryrun:
                                                logger(msg, 5)
                                                playback_position_payload = {
                                                    "PlaybackPositionTicks": stored_ep.status.time
                                                    * 10_000,
                                                }
                                                self.query(
                                                    f"/Users/{user_id}/Items/{jellyfin_episode_id}/UserData",
                                                    "post",
                                                    json=playback_position_payload,
                                                )
                                            else:
                                                logger(msg, 6)

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
                                            )
                                    else:
                                        logger(
                                            f"{self.server_type}: Skipping episode {jellyfin_episode.get('Name')} as it is not in mark list for {user_name}",
                                            3,
                                        )
                        else:
                            logger(
                                f"{self.server_type}: Skipping show {jellyfin_show.get('Name')} as it is not in mark list for {user_name}",
                                3,
                            )

        except Exception as e:
            logger(
                f"{self.server_type}: Error updating watched for {user_name} in library {library_name}, {e}",
                2,
            )
            logger(traceback.format_exc(), 2)
            raise Exception(e)

    def update_watched(
        self,
        watched_list: dict[str, UserData],
        user_mapping=None,
        library_mapping=None,
        dryrun=False,
    ):
        try:
            server_version = self.info(version_only=True)
            update_partial = self.is_partial_update_supported(server_version)

            if not update_partial:
                logger(
                    f"{self.server_type}: Server version {server_version} does not support updating playback position.",
                    2,
                )

            for user, user_data in watched_list.items():
                user_other = None
                user_name = None
                if user_mapping:
                    if user in user_mapping.keys():
                        user_other = user_mapping[user]
                    elif user in user_mapping.values():
                        user_other = search_mapping(user_mapping, user)

                user_id = None
                for key in self.users:
                    if user.lower() == key.lower():
                        user_id = self.users[key]
                        user_name = key
                        break
                    elif user_other and user_other.lower() == key.lower():
                        user_id = self.users[key]
                        user_name = key
                        break

                if not user_id:
                    logger(f"{user} {user_other} not found in Jellyfin", 2)
                    continue

                jellyfin_libraries = self.query(
                    f"/Users/{user_id}/Views",
                    "get",
                )
                jellyfin_libraries = [x for x in jellyfin_libraries["Items"]]

                for library_name in user_data.libraries:
                    if library_name == "Custom TV Shows":
                        print("test")
                    library_data = user_data.libraries[library_name]
                    library_other = None
                    if library_mapping:
                        if library_name in library_mapping.keys():
                            library_other = library_mapping[library_name]
                        elif library_name in library_mapping.values():
                            library_other = search_mapping(
                                library_mapping, library_name
                            )

                    if library_name.lower() not in [
                        x["Name"].lower() for x in jellyfin_libraries
                    ]:
                        if library_other:
                            if library_other.lower() in [
                                x["Name"].lower() for x in jellyfin_libraries
                            ]:
                                logger(
                                    f"{self.server_type}: Library {library_name} not found, but {library_other} found, using {library_other}",
                                    1,
                                )
                                library_name = library_other
                            else:
                                logger(
                                    f"{self.server_type}: Library {library_name} or {library_other} not found in library list",
                                    1,
                                )
                                continue
                        else:
                            logger(
                                f"{self.server_type}: Library {library_name} not found in library list",
                                1,
                            )
                            continue

                    library_id = None
                    for jellyfin_library in jellyfin_libraries:
                        if jellyfin_library["Name"] == library_name:
                            library_id = jellyfin_library["Id"]
                            continue

                    if library_id:
                        self.update_user_watched(
                            user_name,
                            user_id,
                            library_data,
                            library_name,
                            library_id,
                            update_partial,
                            dryrun,
                        )

        except Exception as e:
            logger(f"{self.server_type}: Error updating watched, {e}", 2)
            raise Exception(e)
