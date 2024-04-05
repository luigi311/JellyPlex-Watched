import traceback, os
from math import floor
from dotenv import load_dotenv
import requests

from src.functions import (
    logger,
    search_mapping,
    contains_nested,
    log_marked,
    str_to_bool,
)
from src.library import (
    check_skip_logic,
    generate_library_guids_dict,
)
from src.watched import (
    combine_watched_dicts,
)

load_dotenv(override=True)

generate_guids = str_to_bool(os.getenv("GENERATE_GUIDS", "True"))
generate_locations = str_to_bool(os.getenv("GENERATE_LOCATIONS", "True"))


def get_guids(item):
    guids = {"title": item["Name"]}

    if "ProviderIds" in item:
        guids.update({k.lower(): v for k, v in item["ProviderIds"].items()})

    if "MediaSources" in item:
        guids["locations"] = tuple(
            [x["Path"].split("/")[-1] for x in item["MediaSources"] if "Path" in x]
        )
    else:
        guids["locations"] = tuple()

    guids["status"] = {
        "completed": item["UserData"]["Played"],
        # Convert ticks to milliseconds to match Plex
        "time": floor(item["UserData"]["PlaybackPositionTicks"] / 10000),
    }

    return guids


def get_video_status(jellyfin_video, videos_ids, videos):
    video_status = None

    if generate_locations:
        if "MediaSources" in jellyfin_video:
            for video_location in jellyfin_video["MediaSources"]:
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
            ) in jellyfin_video["ProviderIds"].items():
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


class Jellyfin:
    def __init__(self, baseurl, token):
        self.baseurl = baseurl
        self.token = token
        self.timeout = int(os.getenv("REQUEST_TIMEOUT", 300))

        if not self.baseurl:
            raise Exception("Jellyfin baseurl not set")

        if not self.token:
            raise Exception("Jellyfin token not set")

        self.session = requests.Session()
        self.users = self.get_users()

    def query(self, query, query_type, session=None, identifiers=None):
        try:
            results = None

            authorization = (
                "MediaBrowser , "
                'Client="other", '
                'Device="script", '
                'DeviceId="script", '
                'Version="0.0.0"'
            )
            headers = {
                "Accept": "application/json",
                "X-Emby-Token": self.token,
                "X-Emby-Authorization": authorization,
            }

            if query_type == "get":
                response = self.session.get(
                    self.baseurl + query, headers=headers, timeout=self.timeout
                )
                if response.status_code != 200:
                    raise Exception(
                        f"Query failed with status {response.status_code} {response.reason}"
                    )
                results = response.json()

            elif query_type == "post":
                response = self.session.post(
                    self.baseurl + query, headers=headers, timeout=self.timeout
                )
                if response.status_code != 200:
                    raise Exception(
                        f"Query failed with status {response.status_code} {response.reason}"
                    )
                results = response.json()

            if not isinstance(results, list) and not isinstance(results, dict):
                raise Exception("Query result is not of type list or dict")

            # append identifiers to results
            if identifiers:
                results["Identifiers"] = identifiers

            return results

        except Exception as e:
            logger(f"Jellyfin: Query {query_type} {query}\nResults {results}\n{e}", 2)
            raise Exception(e)

    def info(self) -> str:
        try:
            query_string = "/System/Info/Public"

            response = self.query(query_string, "get")

            if response:
                return f"{response['ServerName']}: {response['Version']}"
            else:
                return None

        except Exception as e:
            logger(f"Jellyfin: Get server name failed {e}", 2)
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
            logger(f"Jellyfin: Get users failed {e}", 2)
            raise Exception(e)

    def get_user_library_watched(
        self, user_name, user_id, library_type, library_id, library_title
    ):
        try:
            user_name = user_name.lower()
            user_watched = {}
            user_watched[user_name] = {}

            logger(
                f"Jellyfin: Generating watched for {user_name} in library {library_title}",
                0,
            )

            # Movies
            if library_type == "Movie":
                user_watched[user_name][library_title] = []
                watched = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?ParentId={library_id}&Filters=IsPlayed&IncludeItemTypes=Movie&Recursive=True&Fields=ItemCounts,ProviderIds,MediaSources",
                    "get",
                )

                in_progress = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?ParentId={library_id}&Filters=IsResumable&IncludeItemTypes=Movie&Recursive=True&Fields=ItemCounts,ProviderIds,MediaSources",
                    "get",
                )

                for movie in watched["Items"] + in_progress["Items"]:
                    if "MediaSources" in movie and movie["MediaSources"] != {}:
                        if "UserData" not in movie:
                            continue
                        
                        # Skip if not watched or watched less than a minute
                        if (
                            movie["UserData"]["Played"] == True
                            or movie["UserData"]["PlaybackPositionTicks"] > 600000000
                        ):
                            logger(
                                f"Jellyfin: Adding {movie.get('Name')} to {user_name} watched list",
                                3,
                            )

                            # Get the movie's GUIDs
                            movie_guids = get_guids(movie)

                            # Append the movie dictionary to the list for the given user and library
                            user_watched[user_name][library_title].append(movie_guids)
                            logger(
                                f"Jellyfin: Added {movie_guids} to {user_name} watched list",
                                3,
                            )

            # TV Shows
            if library_type in ["Series", "Episode"]:
                # Initialize an empty dictionary for the given user and library
                user_watched[user_name][library_title] = {}

                # Retrieve a list of watched TV shows
                watched_shows = self.query(
                    f"/Users/{user_id}/Items"
                    + f"?ParentId={library_id}&isPlaceHolder=false&IncludeItemTypes=Series&Recursive=True&Fields=ProviderIds,Path,RecursiveItemCount",
                    "get",
                )

                # Filter the list of shows to only include those that have been partially or fully watched
                watched_shows_filtered = []
                for show in watched_shows["Items"]:
                    if not "UserData" in show:
                        continue
                    
                    if "PlayedPercentage" in show["UserData"]:
                        if show["UserData"]["PlayedPercentage"] > 0:
                            watched_shows_filtered.append(show)

                # Retrieve the seasons of each watched show
                seasons_watched = []
                for show in watched_shows_filtered:
                    logger(
                        f"Jellyfin: Adding {show.get('Name')} to {user_name} watched list",
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
                    show_identifiers = {
                        "show_guids": show_guids,
                        "show_id": show["Id"],
                    }

                    seasons_watched.append(
                        self.query(
                            f"/Shows/{show['Id']}/Seasons"
                            + f"?userId={user_id}&isPlaceHolder=false&Fields=ProviderIds,RecursiveItemCount",
                            "get",
                            identifiers=frozenset(show_identifiers.items()),
                        )
                    )

                # Filter the list of seasons to only include those that have been partially or fully watched
                seasons_watched_filtered = []
                for seasons in seasons_watched:
                    seasons_watched_filtered_dict = {}
                    seasons_watched_filtered_dict["Identifiers"] = seasons[
                        "Identifiers"
                    ]
                    seasons_watched_filtered_dict["Items"] = []
                    for season in seasons["Items"]:
                        if "PlayedPercentage" in season["UserData"]:
                            if season["UserData"]["PlayedPercentage"] > 0:
                                seasons_watched_filtered_dict["Items"].append(season)

                    if seasons_watched_filtered_dict["Items"]:
                        seasons_watched_filtered.append(seasons_watched_filtered_dict)

                # Create a list of tasks to retrieve the episodes of each watched season
                watched_episodes = []
                for seasons in seasons_watched_filtered:
                    if len(seasons["Items"]) > 0:
                        for season in seasons["Items"]:
                            if "IndexNumber" not in season:
                                logger(
                                    f"Jellyfin: Skipping show {season.get('SeriesName')} season {season.get('Name')} as it has no index number",
                                    3,
                                )

                                continue
                            season_identifiers = dict(seasons["Identifiers"])
                            season_identifiers["season_index"] = season["IndexNumber"]
                            watched_task = self.query(
                                f"/Shows/{season_identifiers['show_id']}/Episodes"
                                + f"?seasonId={season['Id']}&userId={user_id}&isPlaceHolder=false&Filters=IsPlayed&Fields=ProviderIds,MediaSources",
                                "get",
                                identifiers=frozenset(season_identifiers.items()),
                            )

                            in_progress_task = self.query(
                                f"/Shows/{season_identifiers['show_id']}/Episodes"
                                + f"?seasonId={season['Id']}&userId={user_id}&isPlaceHolder=false&Filters=IsResumable&Fields=ProviderIds,MediaSources",
                                "get",
                                identifiers=frozenset(season_identifiers.items()),
                            )
                            watched_episodes.append(watched_task)
                            watched_episodes.append(in_progress_task)

                # Iterate through the watched episodes
                for episodes in watched_episodes:
                    # If the season has any watched episodes
                    if len(episodes["Items"]) > 0:
                        # Create a dictionary for the season with its identifier and episodes
                        season_dict = {}
                        season_dict["Identifiers"] = dict(episodes["Identifiers"])
                        season_dict["Episodes"] = []
                        for episode in episodes["Items"]:
                            if (
                                "MediaSources" in episode
                                and episode["MediaSources"] != {}
                            ):
                                # If watched or watched more than a minute
                                if (
                                    episode["UserData"]["Played"] == True
                                    or episode["UserData"]["PlaybackPositionTicks"]
                                    > 600000000
                                ):
                                    episode_dict = get_guids(episode)
                                    # Add the episode dictionary to the season's list of episodes
                                    season_dict["Episodes"].append(episode_dict)

                        # Add the season dictionary to the show's list of seasons
                        if (
                            season_dict["Identifiers"]["show_guids"]
                            not in user_watched[user_name][library_title]
                        ):
                            user_watched[user_name][library_title][
                                season_dict["Identifiers"]["show_guids"]
                            ] = {}

                        if (
                            season_dict["Identifiers"]["season_index"]
                            not in user_watched[user_name][library_title][
                                season_dict["Identifiers"]["show_guids"]
                            ]
                        ):
                            user_watched[user_name][library_title][
                                season_dict["Identifiers"]["show_guids"]
                            ][season_dict["Identifiers"]["season_index"]] = []

                        user_watched[user_name][library_title][
                            season_dict["Identifiers"]["show_guids"]
                        ][season_dict["Identifiers"]["season_index"]] = season_dict[
                            "Episodes"
                        ]
                        logger(
                            f"Jellyfin: Added {season_dict['Episodes']} to {user_name} {season_dict['Identifiers']['show_guids']} watched list",
                            1,
                        )

            logger(
                f"Jellyfin: Got watched for {user_name} in library {library_title}", 1
            )
            if library_title in user_watched[user_name]:
                logger(f"Jellyfin: {user_watched[user_name][library_title]}", 3)

            return user_watched
        except Exception as e:
            logger(
                f"Jellyfin: Failed to get watched for {user_name} in library {library_title}, Error: {e}",
                2,
            )

            logger(traceback.format_exc(), 2)
            return {}

    def get_users_watched(
        self,
        user_name,
        user_id,
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        library_mapping,
    ):
        try:
            # Get all libraries
            user_name = user_name.lower()
            watched = []

            libraries = []

            all_libraries = self.query(f"/Users/{user_id}/Views", "get")
            for library in all_libraries["Items"]:
                library_id = library["Id"]
                library_title = library["Name"]
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

                skip_reason = check_skip_logic(
                    library_title,
                    types,
                    blacklist_library,
                    whitelist_library,
                    blacklist_library_type,
                    whitelist_library_type,
                    library_mapping,
                )

                if skip_reason:
                    logger(
                        f"Jellyfin: Skipping library {library_title}: {skip_reason}",
                        1,
                    )
                    continue

                # If there are multiple types in library raise error
                if types is None or len(types) < 1:
                    all_types = set([x["Type"] for x in library["Items"]])
                    logger(
                        f"Jellyfin: Skipping Library {library_title} found types: {types}, all types: {all_types}",
                        1,
                    )
                    continue

                for library_type in types:
                    # Get watched for user
                    watched.append(
                        self.get_user_library_watched(
                            user_name,
                            user_id,
                            library_type,
                            library_id,
                            library_title,
                        )
                    )

            return watched
        except Exception as e:
            logger(f"Jellyfin: Failed to get users watched, Error: {e}", 2)
            raise Exception(e)

    def get_watched(
        self,
        users,
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        library_mapping=None,
    ):
        try:
            users_watched = {}
            watched = []

            for user_name, user_id in users.items():
                watched.append(
                    self.get_users_watched(
                        user_name,
                        user_id,
                        blacklist_library,
                        whitelist_library,
                        blacklist_library_type,
                        whitelist_library_type,
                        library_mapping,
                    )
                )

            for user_watched in watched:
                user_watched_combine = combine_watched_dicts(user_watched)
                for user, user_watched_temp in user_watched_combine.items():
                    if user not in users_watched:
                        users_watched[user] = {}
                    users_watched[user].update(user_watched_temp)

            return users_watched
        except Exception as e:
            logger(f"Jellyfin: Failed to get watched, Error: {e}", 2)
            raise Exception(e)

    def update_user_watched(
        self, user_name, user_id, library, library_id, videos, dryrun
    ):
        try:
            logger(
                f"Jellyfin: Updating watched for {user_name} in library {library}", 1
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
                    f"Jellyfin: No videos to mark as watched for {user_name} in library {library}",
                    1,
                )

                return

            logger(
                f"Jellyfin: mark list\nShows: {videos_shows_ids}\nEpisodes: {videos_episodes_ids}\nMovies: {videos_movies_ids}",
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
                            msg = f"Jellyfin: {jellyfin_video.get('Name')} as watched for {user_name} in {library}"
                            if not dryrun:
                                logger(msg, 5)
                                self.query(
                                    f"/Users/{user_id}/PlayedItems/{jellyfin_video_id}",
                                    "post",
                                )
                            else:
                                logger(msg, 6)

                            log_marked(
                                user_name,
                                library,
                                jellyfin_video.get("Name"),
                            )
                        else:
                            # TODO add support for partially watched movies
                            msg = f"Jellyfin: {jellyfin_video.get('Name')} as partially watched for {floor(movie_status['time'] / 60_000)} minutes for {user_name} in {library}"
                            """
                            if not dryrun:
                                pass
                                # logger(msg, 5)
                            else:
                                pass
                                # logger(msg, 6)

                            log_marked(
                                user_name,
                                library,
                                jellyfin_video.get("Name"),
                                duration=floor(movie_status["time"] / 60_000),
                            )"""
                    else:
                        logger(
                            f"Jellyfin: Skipping movie {jellyfin_video.get('Name')} as it is not in mark list for {user_name}",
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
                                for shows, seasons in videos.items():
                                    show = {k: v for k, v in shows}
                                    if (
                                        contains_nested(
                                            jellyfin_show["Path"].split("/")[-1],
                                            show["locations"],
                                        )
                                        is not None
                                    ):
                                        for season in seasons.values():
                                            for episode in season:
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
                                        for show, seasons in videos.items():
                                            show = {k: v for k, v in show}
                                            if show_provider_id.lower() in show.get(
                                                show_provider_source.lower(), []
                                            ):
                                                for season in seasons.values():
                                                    for episode in season:
                                                        episode_videos.append(episode)

                                                break

                    if show_found:
                        logger(
                            f"Jellyfin: Updating watched for {user_name} in library {library} for show {jellyfin_show.get('Name')}",
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
                                        f"Jellyfin: {jellyfin_episode['SeriesName']} {jellyfin_episode['SeasonName']} Episode {jellyfin_episode.get('IndexNumber')} {jellyfin_episode.get('Name')}"
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
                                        user_name,
                                        library,
                                        jellyfin_episode.get("SeriesName"),
                                        jellyfin_episode.get("Name"),
                                    )
                                else:
                                    # TODO add support for partially watched episodes
                                    msg = (
                                        f"Jellyfin: {jellyfin_episode['SeriesName']} {jellyfin_episode['SeasonName']} Episode {jellyfin_episode.get('IndexNumber')} {jellyfin_episode.get('Name')}"
                                        + f" as partially watched for {floor(episode_status['time'] / 60_000)} minutes for {user_name} in {library}"
                                    )
                                    """
                                    if not dryrun:
                                        pass
                                        # logger(f"Marked {msg}", 0)
                                    else:
                                        pass
                                        # logger(f"Dryrun {msg}", 0)

                                    log_marked(
                                        user_name,
                                        library,
                                        jellyfin_episode.get("SeriesName"),
                                        jellyfin_episode.get('Name'),
                                        duration=floor(episode_status["time"] / 60_000),
                                    )"""
                            else:
                                logger(
                                    f"Jellyfin: Skipping episode {jellyfin_episode.get('Name')} as it is not in mark list for {user_name}",
                                    3,
                                )
                    else:
                        logger(
                            f"Jellyfin: Skipping show {jellyfin_show.get('Name')} as it is not in mark list for {user_name}",
                            3,
                        )

        except Exception as e:
            logger(
                f"Jellyfin: Error updating watched for {user_name} in library {library}, {e}",
                2,
            )
            logger(traceback.format_exc(), 2)
            raise Exception(e)

    def update_watched(
        self, watched_list, user_mapping=None, library_mapping=None, dryrun=False
    ):
        try:
            for user, libraries in watched_list.items():
                logger(f"Jellyfin: Updating for entry {user}, {libraries}", 1)
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
                                    f"Jellyfin: Library {library} not found, but {library_other} found, using {library_other}",
                                    1,
                                )
                                library = library_other
                            else:
                                logger(
                                    f"Jellyfin: Library {library} or {library_other} not found in library list",
                                    1,
                                )
                                continue
                        else:
                            logger(
                                f"Jellyfin: Library {library} not found in library list",
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
                            user_name, user_id, library, library_id, videos, dryrun
                        )

        except Exception as e:
            logger(f"Jellyfin: Error updating watched, {e}", 2)
            raise Exception(e)
