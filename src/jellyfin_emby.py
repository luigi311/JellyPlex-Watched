# Functions for Jellyfin and Emby

import traceback, os
from math import floor
from typing import Union
from dotenv import load_dotenv
import requests
from packaging.version import (parse, Version)

from src.functions import (
    logger,
    search_mapping,
    contains_nested,
    log_marked,
    str_to_bool,
)
from src.library import generate_library_guids_dict

load_dotenv(override=True)

generate_guids = str_to_bool(os.getenv("GENERATE_GUIDS", "True"))
generate_locations = str_to_bool(os.getenv("GENERATE_LOCATIONS", "True"))


def get_guids(server_type, item):
    if item.get("Name"):
        guids = {"title": item.get("Name")}
    else:
        logger(f"{server_type}: Name not found in {item.get('Id')}", 1)
        guids = {"title": None}

    if "ProviderIds" in item:
        guids.update({k.lower(): v for k, v in item["ProviderIds"].items()})
    else:
        logger(f"{server_type}: ProviderIds not found in {item.get('Name')}", 1)

    if "MediaSources" in item:
        guids["locations"] = tuple(
            [x["Path"].split("/")[-1] for x in item["MediaSources"] if "Path" in x]
        )
    else:
        logger(f"{server_type}: MediaSources not found in {item.get('Name')}", 1)
        guids["locations"] = tuple()

    if "UserData" in item:
        guids["status"] = {
            "completed": item["UserData"]["Played"],
            # Convert ticks to milliseconds to match Plex
            "time": floor(item["UserData"]["PlaybackPositionTicks"] / 10000),
        }
    else:
        logger(f"{server_type}: UserData not found in {item.get('Name')}", 1)
        guids["status"] = {}

    return guids


def get_video_status(server_video, videos_ids, videos):
    video_status = None

    if generate_locations:
        if "MediaSources" in server_video:
            for video_location in server_video["MediaSources"]:
                if "Path" in video_location:
                    if (
                        contains_nested(
                            video_location["Path"].split("/")[-1],
                            videos_ids["locations"],
                        )
                        is not None
                    ):
                        for video in videos:
                            if (
                                contains_nested(
                                    video_location["Path"].split("/")[-1],
                                    video["locations"],
                                )
                                is not None
                            ):
                                video_status = video["status"]
                                break
                        break

    if generate_guids:
        if not video_status:
            for (
                video_provider_source,
                video_provider_id,
            ) in server_video["ProviderIds"].items():
                if video_provider_source.lower() in videos_ids:
                    if (
                        video_provider_id.lower()
                        in videos_ids[video_provider_source.lower()]
                    ):
                        for video in videos:
                            if video_provider_id.lower() in video.get(
                                video_provider_source.lower(), []
                            ):
                                video_status = video["status"]
                                break
                        break

    return video_status


class JellyfinEmby:
    def __init__(self, server_type, baseurl, token, headers):
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

    def query(self, query, query_type, identifiers=None, json=None):
        try:
            results = None

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
            if identifiers:
                results["Identifiers"] = identifiers

            return results

        except Exception as e:
            logger(
                f"{self.server_type}: Query {query_type} {query}\nResults {results}\n{e}",
                2,
            )
            raise Exception(e)

    def info(self, name_only: bool = False, version_only: bool = False) -> Union[str | Version]:
        try:
            query_string = "/System/Info/Public"

            response = self.query(query_string, "get")

            if response:
                if name_only:
                    return f"{response['ServerName']}"
                elif version_only:
                    return parse(response["Version"])
                
                return f"{self.server_type} {response['ServerName']}: {response['Version']}"
            else:
                return None

        except Exception as e:
            logger(f"{self.server_type}: Get server name failed {e}", 2)
            raise Exception(e)

    def get_users(self):
        try:
            users = {}

            query_string = "/Users"
            response = self.query(query_string, "get")

            # If response is not empty
            if response:
                for user in response:
                    users[user["Name"]] = user["Id"]

            return users
        except Exception as e:
            logger(f"{self.server_type}: Get users failed {e}", 2)
            raise Exception(e)

    def get_libraries(self):
        try:
            libraries = {}

            # Theres no way to get all libraries so individually get list of libraries from all users
            users = self.get_users()

            for _, user_id in users.items():
                user_libraries = self.query(f"/Users/{user_id}/Views", "get")
                for library in user_libraries["Items"]:
                    library_id = library["Id"]
                    library_title = library["Name"]

                    # Get library items to check the type
                    media_info = self.query(
                        f"/Users/{user_id}/Items"
                        + f"?ParentId={library_id}&Filters=IsPlayed&Recursive=True&excludeItemTypes=Folder&limit=100",
                        "get",
                    )

                    types = set(
                        [
                            x["Type"]
                            for x in media_info["Items"]
                            if x["Type"] in ["Movie", "Series", "Episode"]
                        ]
                    )
                    all_types = set([x["Type"] for x in media_info["Items"]])

                    if not types:
                        logger(
                            f"{self.server_type}: Skipping Library {library_title} found wanted types: {all_types}",
                            1,
                        )
                    else:
                        libraries[library_title] = str(types)

            return libraries
        except Exception as e:
            logger(f"{self.server_type}: Get libraries failed {e}", 2)
            raise Exception(e)

    def get_user_library_watched(
        self, user_name, user_id, library_type, library_id, library_title
    ):
        try:
            user_name = user_name.lower()
            user_watched = {}

            logger(
                f"{self.server_type}: Generating watched for {user_name} in library {library_title}",
                0,
            )

            # Movies
            if library_type == "Movie":
                user_watched[library_title] = []
                watched = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?ParentId={library_id}&Filters=IsPlayed&IncludeItemTypes=Movie&Recursive=True&Fields=ItemCounts,ProviderIds,MediaSources",
                    "get",
                ).get("Items", [])

                in_progress = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?ParentId={library_id}&Filters=IsResumable&IncludeItemTypes=Movie&Recursive=True&Fields=ItemCounts,ProviderIds,MediaSources",
                    "get",
                ).get("Items", [])

                for movie in watched + in_progress:
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
                        logger(
                            f"{self.server_type}: Adding {movie.get('Name')} to {user_name} watched list",
                            3,
                        )

                        # Get the movie's GUIDs
                        movie_guids = get_guids(self.server_type, movie)

                        # Append the movie dictionary to the list for the given user and library
                        user_watched[library_title].append(movie_guids)
                        logger(
                            f"{self.server_type}: Added {movie_guids} to {user_name} watched list",
                            3,
                        )

            # TV Shows
            if library_type in ["Series", "Episode"]:
                # Initialize an empty dictionary for the given user and library
                user_watched[library_title] = {}

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
                    logger(
                        f"{self.server_type}: Adding {show.get('Name')} to {user_name} watched list",
                        3,
                    )
                    show_guids = {k.lower(): v for k, v in show["ProviderIds"].items()}
                    show_guids["title"] = show["Name"]
                    show_guids["locations"] = (
                        tuple([show["Path"].split("/")[-1]])
                        if "Path" in show
                        else tuple()
                    )

                    show_guids = frozenset(show_guids.items())

                    show_episodes = self.query(
                        f"/Shows/{show['Id']}/Episodes"
                        + f"?userId={user_id}&isPlaceHolder=false&Fields=ProviderIds,MediaSources",
                        "get",
                    ).get("Items", [])

                    # Iterate through the episodes
                    # Create a list to store the episodes
                    mark_episodes_list = []
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
                            episode_guids = get_guids(self.server_type, episode)
                            mark_episodes_list.append(episode_guids)

                    if mark_episodes_list:
                        # Add the show dictionary to the user's watched list
                        if show_guids not in user_watched[library_title]:
                            user_watched[library_title][show_guids] = []

                        user_watched[library_title][show_guids] = mark_episodes_list
                        for episode in mark_episodes_list:
                            logger(
                                f"{self.server_type}: Added {episode} to {user_name} watched list",
                                3,
                            )

            logger(
                f"{self.server_type}: Got watched for {user_name} in library {library_title}",
                1,
            )
            if library_title in user_watched:
                logger(f"{self.server_type}: {user_watched[library_title]}", 3)

            return user_watched
        except Exception as e:
            logger(
                f"{self.server_type}: Failed to get watched for {user_name} in library {library_title}, Error: {e}",
                2,
            )

            logger(traceback.format_exc(), 2)
            return {}

    def get_watched(self, users, sync_libraries):
        try:
            users_watched = {}
            watched = []

            for user_name, user_id in users.items():
                libraries = []

                all_libraries = self.query(f"/Users/{user_id}/Views", "get")
                for library in all_libraries["Items"]:
                    library_id = library["Id"]
                    library_title = library["Name"]

                    if library_title not in sync_libraries:
                        continue

                    identifiers = {
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

                    library_id = library["Identifiers"]["library_id"]
                    library_title = library["Identifiers"]["library_title"]

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
                        watched = self.get_user_library_watched(
                            user_name,
                            user_id,
                            library_type,
                            library_id,
                            library_title,
                        )

                        if user_name.lower() not in users_watched:
                            users_watched[user_name.lower()] = {}
                        users_watched[user_name.lower()].update(watched)

            return users_watched
        except Exception as e:
            logger(f"{self.server_type}: Failed to get watched, Error: {e}", 2)
            raise Exception(e)

    def update_user_watched(
        self, user_name, user_id, library, library_id, videos, update_partial, dryrun
    ):
        try:
            logger(
                f"{self.server_type}: Updating watched for {user_name} in library {library}",
                1,
            )
            (
                videos_shows_ids,
                videos_episodes_ids,
                videos_movies_ids,
            ) = generate_library_guids_dict(videos)

            if (
                not videos_movies_ids
                and not videos_shows_ids
                and not videos_episodes_ids
            ):
                logger(
                    f"{self.server_type}: No videos to mark as watched for {user_name} in library {library}",
                    1,
                )

                return

            logger(
                f"{self.server_type}: mark list\nShows: {videos_shows_ids}\nEpisodes: {videos_episodes_ids}\nMovies: {videos_movies_ids}",
                1,
            )

            if videos_movies_ids:
                jellyfin_search = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?SortBy=SortName&SortOrder=Ascending&Recursive=True&ParentId={library_id}"
                    + "&isPlayed=false&Fields=ItemCounts,ProviderIds,MediaSources&IncludeItemTypes=Movie",
                    "get",
                )
                for jellyfin_video in jellyfin_search["Items"]:
                    movie_status = get_video_status(
                        jellyfin_video, videos_movies_ids, videos
                    )

                    if movie_status:
                        jellyfin_video_id = jellyfin_video["Id"]
                        if movie_status["completed"]:
                            msg = f"{self.server_type}: {jellyfin_video.get('Name')} as watched for {user_name} in {library}"
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
                                library,
                                jellyfin_video.get("Name"),
                            )
                        elif update_partial:
                            msg = f"{self.server_type}: {jellyfin_video.get('Name')} as partially watched for {floor(movie_status['time'] / 60_000)} minutes for {user_name} in {library}"

                            if not dryrun:
                                logger(msg, 5)
                                playback_position_payload = {
                                    "PlaybackPositionTicks": movie_status["time"]
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
                                library,
                                jellyfin_video.get("Name"),
                                duration=floor(movie_status["time"] / 60_000),
                            )
                    else:
                        logger(
                            f"{self.server_type}: Skipping movie {jellyfin_video.get('Name')} as it is not in mark list for {user_name}",
                            3,
                        )

            # TV Shows
            if videos_shows_ids and videos_episodes_ids:
                jellyfin_search = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?SortBy=SortName&SortOrder=Ascending&Recursive=True&ParentId={library_id}"
                    + "&Fields=ItemCounts,ProviderIds,Path&IncludeItemTypes=Series",
                    "get",
                )
                jellyfin_shows = [x for x in jellyfin_search["Items"]]

                for jellyfin_show in jellyfin_shows:
                    show_found = False
                    episode_videos = []

                    if generate_locations:
                        if "Path" in jellyfin_show:
                            if (
                                contains_nested(
                                    jellyfin_show["Path"].split("/")[-1],
                                    videos_shows_ids["locations"],
                                )
                                is not None
                            ):
                                show_found = True
                                for shows, episodes in videos.items():
                                    show = {k: v for k, v in shows}
                                    if (
                                        contains_nested(
                                            jellyfin_show["Path"].split("/")[-1],
                                            show["locations"],
                                        )
                                        is not None
                                    ):
                                        for episode in episodes:
                                            episode_videos.append(episode)

                                        break

                    if generate_guids:
                        if not show_found:
                            for show_provider_source, show_provider_id in jellyfin_show[
                                "ProviderIds"
                            ].items():
                                if show_provider_source.lower() in videos_shows_ids:
                                    if (
                                        show_provider_id.lower()
                                        in videos_shows_ids[
                                            show_provider_source.lower()
                                        ]
                                    ):
                                        show_found = True
                                        for show, episodes in videos.items():
                                            show = {k: v for k, v in show}
                                            if show_provider_id.lower() in show.get(
                                                show_provider_source.lower(), []
                                            ):
                                                for episode in episodes:
                                                    episode_videos.append(episode)

                                                break

                    if show_found:
                        logger(
                            f"{self.server_type}: Updating watched for {user_name} in library {library} for show {jellyfin_show.get('Name')}",
                            1,
                        )
                        jellyfin_show_id = jellyfin_show["Id"]
                        jellyfin_episodes = self.query(
                            f"/Shows/{jellyfin_show_id}/Episodes"
                            + f"?userId={user_id}&Fields=ItemCounts,ProviderIds,MediaSources",
                            "get",
                        )

                        for jellyfin_episode in jellyfin_episodes["Items"]:
                            episode_status = get_video_status(
                                jellyfin_episode, videos_episodes_ids, episode_videos
                            )

                            if episode_status:
                                jellyfin_episode_id = jellyfin_episode["Id"]
                                if episode_status["completed"]:
                                    msg = (
                                        f"{self.server_type}: {jellyfin_episode['SeriesName']} {jellyfin_episode['SeasonName']} Episode {jellyfin_episode.get('IndexNumber')} {jellyfin_episode.get('Name')}"
                                        + f" as watched for {user_name} in {library}"
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
                                        library,
                                        jellyfin_episode.get("SeriesName"),
                                        jellyfin_episode.get("Name"),
                                    )
                                elif update_partial:
                                    msg = (
                                        f"{self.server_type}: {jellyfin_episode['SeriesName']} {jellyfin_episode['SeasonName']} Episode {jellyfin_episode.get('IndexNumber')} {jellyfin_episode.get('Name')}"
                                        + f" as partially watched for {floor(episode_status['time'] / 60_000)} minutes for {user_name} in {library}"
                                    )

                                    if not dryrun:
                                        logger(msg, 5)
                                        playback_position_payload = {
                                            "PlaybackPositionTicks": episode_status[
                                                "time"
                                            ]
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
                                        library,
                                        jellyfin_episode.get("SeriesName"),
                                        jellyfin_episode.get("Name"),
                                        duration=floor(episode_status["time"] / 60_000),
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
                f"{self.server_type}: Error updating watched for {user_name} in library {library}, {e}",
                2,
            )
            logger(traceback.format_exc(), 2)
            raise Exception(e)

    def update_watched(
        self, watched_list, user_mapping=None, library_mapping=None, dryrun=False
    ):
        try:
            server_version = self.info(version_only=True)
            update_partial = self.is_partial_update_supported(server_version)

            if not update_partial:
                logger(
                    f"{self.server_type}: Server version {server_version} does not support updating playback position.",
                    2,
                )

            for user, libraries in watched_list.items():
                logger(f"{self.server_type}: Updating for entry {user}, {libraries}", 1)
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

                for library, videos in libraries.items():
                    library_other = None
                    if library_mapping:
                        if library in library_mapping.keys():
                            library_other = library_mapping[library]
                        elif library in library_mapping.values():
                            library_other = search_mapping(library_mapping, library)

                    if library.lower() not in [
                        x["Name"].lower() for x in jellyfin_libraries
                    ]:
                        if library_other:
                            if library_other.lower() in [
                                x["Name"].lower() for x in jellyfin_libraries
                            ]:
                                logger(
                                    f"{self.server_type}: Library {library} not found, but {library_other} found, using {library_other}",
                                    1,
                                )
                                library = library_other
                            else:
                                logger(
                                    f"{self.server_type}: Library {library} or {library_other} not found in library list",
                                    1,
                                )
                                continue
                        else:
                            logger(
                                f"{self.server_type}: Library {library} not found in library list",
                                1,
                            )
                            continue

                    library_id = None
                    for jellyfin_library in jellyfin_libraries:
                        if jellyfin_library["Name"] == library:
                            library_id = jellyfin_library["Id"]
                            continue

                    if library_id:
                        self.update_user_watched(
                            user_name,
                            user_id,
                            library,
                            library_id,
                            videos,
                            update_partial,
                            dryrun,
                        )

        except Exception as e:
            logger(f"{self.server_type}: Error updating watched, {e}", 2)
            raise Exception(e)
