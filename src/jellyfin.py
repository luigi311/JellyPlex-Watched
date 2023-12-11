import asyncio, aiohttp, traceback, os
from math import floor
from dotenv import load_dotenv

from src.functions import (
    logger,
    search_mapping,
    contains_nested,
    log_marked,
)
from src.library import (
    check_skip_logic,
    generate_library_guids_dict,
)
from src.watched import (
    combine_watched_dicts,
)

load_dotenv(override=True)


def get_media_guids(media_item):
    # Create a dictionary for the media item with its title and provider IDs
    media_guids = {k.lower(): v for k, v in media_item["ProviderIds"].items()}
    media_guids["title"] = media_item["Name"]

    media_guids["locations"] = tuple()
    if "MediaSources" in media_item:
        for x in media_item["MediaSources"]:
            if "Path" in x:
                media_guids["locations"] += (x["Path"].split("/")[-1],)

    media_guids["status"] = {
        "completed": media_item["UserData"]["Played"],
        "time": floor(media_item["UserData"]["PlaybackPositionTicks"] / 10000),
    }

    return media_guids


class Jellyfin:
    def __init__(self, baseurl, token):
        self.baseurl = baseurl
        self.token = token
        self.timeout = aiohttp.ClientTimeout(
            total=int(os.getenv("REQUEST_TIMEOUT", 300)),
            connect=None,
            sock_connect=None,
            sock_read=None,
        )

        if not self.baseurl:
            raise Exception("Jellyfin baseurl not set")

        if not self.token:
            raise Exception("Jellyfin token not set")

        self.users = asyncio.run(self.get_users())

    async def query(self, query, query_type, session=None, identifiers=None):
        try:
            if not session:
                async with aiohttp.ClientSession(timeout=self.timeout) as session:
                    return await self.query(query, query_type, session, identifiers)

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
                async with session.get(
                    self.baseurl + query, headers=headers
                ) as response:
                    if response.status != 200:
                        raise Exception(
                            f"Query failed with status {response.status} {response.reason}"
                        )
                    results = await response.json()

            elif query_type == "post":
                async with session.post(
                    self.baseurl + query, headers=headers
                ) as response:
                    if response.status != 200:
                        raise Exception(
                            f"Query failed with status {response.status} {response.reason}"
                        )
                    results = await response.json()

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

            response = asyncio.run(self.query(query_string, "get"))

            if response:
                return f"{response['ServerName']}: {response['Version']}"
            else:
                return None

        except Exception as e:
            logger(f"Jellyfin: Get server name failed {e}", 2)
            raise Exception(e)

    async def get_users(self):
        try:
            users = {}

            query_string = "/Users"
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                response = await self.query(query_string, "get", session)

            # If response is not empty
            if response:
                for user in response:
                    users[user["Name"]] = user["Id"]

            return users
        except Exception as e:
            logger(f"Jellyfin: Get users failed {e}", 2)
            raise Exception(e)

    async def process_movie_library(
        self, user_watched, user_id, library_id, library_title, session, user_name
    ):
        # Initialize the user's movie library in the user_watched dictionary
        user_watched[user_name][library_title] = []

        # Get the list of watched movies
        watched = await self.query(
            f"/Users/{user_id}/Items"
            + f"?ParentId={library_id}&Filters=IsPlayed&IncludeItemTypes=Movie&Recursive=True&Fields=ItemCounts,ProviderIds,MediaSources",
            "get",
            session,
        )
        # Get the list of in-progress movies
        in_progress = await self.query(
            f"/Users/{user_id}/Items"
            + f"?ParentId={library_id}&Filters=IsResumable&IncludeItemTypes=Movie&Recursive=True&Fields=ItemCounts,ProviderIds,MediaSources",
            "get",
            session,
        )

        # Process the watched movies
        await self.process_movies(
            user_watched,
            library_title,
            watched["Items"],
            user_name,
            in_progress=False,
        )
        # Process the in-progress movies
        await self.process_movies(
            user_watched,
            library_title,
            in_progress["Items"],
            user_name,
            in_progress=True,
        )

    async def process_movies(
        self, user_watched, library_title, movies, user_name, in_progress=False
    ):
        # Iterate through the list of movies
        for movie in movies:
            # Check if the movie has media sources
            if "MediaSources" in movie and movie["MediaSources"]:
                logger(
                    f"Jellyfin: Adding {movie.get('Name')} to {user_name} watched list",
                    3,
                )
                # Get the movie's GUIDs
                movie_guids = get_media_guids(movie)
                # Check if the movie is in progress or fully watched
                if (
                    not in_progress
                    or movie["UserData"]["PlaybackPositionTicks"] >= 600000000
                ):
                    # Append the movie dictionary to the user's watched list
                    user_watched[user_name][library_title].append(movie_guids)
                logger(f"Jellyfin: Added {movie_guids} to {user_name} watched list", 3)

    async def process_tv_library(
        self, user_watched, user_id, library_id, library_title, session, user_name
    ):
        # Initialize the user's TV library in the user_watched dictionary
        user_watched[user_name][library_title] = {}

        # Get the list of watched TV shows
        watched_shows = await self.query(
            f"/Users/{user_id}/Items"
            + f"?ParentId={library_id}&isPlaceHolder=false&IncludeItemTypes=Series&Recursive=True&Fields=ProviderIds,Path,RecursiveItemCount",
            "get",
            session,
        )

        # Filter the list of shows to only include those that have been partially or fully watched
        watched_shows_filtered = [
            show
            for show in watched_shows["Items"]
            if "PlayedPercentage" in show["UserData"]
            and show["UserData"]["PlayedPercentage"] > 0
        ]

        # Process each watched show
        seasons_tasks = [
            self.process_watched_show(
                user_watched, library_title, show, user_id, session, user_name
            )
            for show in watched_shows_filtered
        ]
        await asyncio.gather(*seasons_tasks)

    async def process_watched_show(
        self, user_watched, library_title, show, user_id, session, user_name
    ):
        # Log the show being processed
        logger(f"Jellyfin: Adding {show.get('Name')} to {user_name} watched list", 3)
        # Get the show's provider IDs and create identifiers
        show_guids = {k.lower(): v for k, v in show["ProviderIds"].items()}
        show_guids["title"] = show["Name"]
        show_guids["locations"] = (
            (show["Path"].split("/")[-1],) if "Path" in show else tuple()
        )
        show_identifiers = {
            "show_guids": frozenset(show_guids.items()),
            "show_id": show["Id"],
        }
        # Query the server for the show's seasons
        season_task = asyncio.ensure_future(
            self.query(
                f"/Shows/{show['Id']}/Seasons"
                + f"?userId={user_id}&isPlaceHolder=false&Fields=ProviderIds,RecursiveItemCount",
                "get",
                session,
                frozenset(show_identifiers.items()),
            )
        )
        seasons = await season_task
        # Process each season
        await self.process_watched_seasons(
            user_watched,
            library_title,
            show_identifiers,
            seasons,
            session,
            user_name,
            user_id,
        )

    async def process_watched_seasons(
        self,
        user_watched,
        library_title,
        show_identifiers,
        seasons,
        session,
        user_name,
        user_id,
    ):
        watched_task = []
        # Iterate through the seasons
        for season in seasons["Items"]:
            # Check if the season has been partially or fully watched
            if (
                "PlayedPercentage" in season["UserData"]
                and season["UserData"]["PlayedPercentage"] > 0
            ):
                # Log the season being processed
                logger(
                    f"Jellyfin: Adding {season.get('Name')} to {user_name} watched list",
                    3,
                )
                watched_task.append(
                    self.query(
                        f"/Shows/{show_identifiers['show_id']}/Episodes"
                        + f"?seasonId={season['Id']}&userId={user_id}&isPlaceHolder=false&Filters=IsPlayed&Fields=ProviderIds,MediaSources",
                        "get",
                        session,
                        frozenset(show_identifiers.items()),
                    )
                )
                watched_task.append(
                    self.query(
                        f"/Shows/{show_identifiers['show_id']}/Episodes"
                        + f"?seasonId={season['Id']}&userId={user_id}&isPlaceHolder=false&Filters=IsResumable&Fields=ProviderIds,MediaSources",
                        "get",
                        session,
                        frozenset(show_identifiers.items()),
                    )
                )

        watched_episodes = await asyncio.gather(*watched_task)

        process_task = []

        # Process the watched episodes
        for episodes in watched_episodes:
            process_task.append(
                self.process_watched_episodes(
                    user_watched,
                    library_title,
                    episodes,
                    user_name,
                )
            )

        await asyncio.gather(*process_task)

    async def process_watched_episodes(
        self,
        user_watched,
        library_title,
        episodes,
        user_name,
    ):
        show_identifiers = episodes["Identifiers"]
        # Check if the season has any watched episodes
        if episodes["Items"]:
            # Create a dictionary for the season with its identifier and episodes
            show_dict = {"Identifiers": dict(show_identifiers), "Episodes": []}
            # Iterate through the episodes
            for episode in episodes["Items"]:
                # Check if the episode has media sources
                if "MediaSources" in episode and episode["MediaSources"]:
                    # Check if the episode is in progress or fully watched
                    if (
                        episode["UserData"]["Played"]
                        or episode["UserData"]["PlaybackPositionTicks"] > 600000000
                    ):
                        # Get the episode's GUIDs
                        episode_dict = get_media_guids(episode)
                        # Add the episode dictionary to the season's list of episodes
                        show_dict["Episodes"].append(episode_dict)

            # Check if the season has any watched episodes
            if show_dict["Episodes"]:
                # Add the season dictionary to the show's list of seasons
                user_watched[user_name][library_title].setdefault(
                    show_dict["Identifiers"]["show_guids"], {}
                ).setdefault(episode["ParentIndexNumber"], []).extend(
                    show_dict["Episodes"]
                )
                logger(
                    f"Jellyfin: Added {show_dict['Episodes']} to {user_name} {show_dict['Identifiers']['show_guids']} watched list",
                    1,
                )

    async def get_user_library_watched(
        self, user_name, user_id, library_type, library_id, library_title
    ):
        try:
            process_task = []
            # Convert the username to lowercase for consistency
            user_name = user_name.lower()
            # Initialize the user_watched dictionary for the user
            user_watched = {user_name: {}}

            # Log the start of generating watched content
            logger(
                f"Jellyfin: Generating watched for {user_name} in library {library_title}",
                0,
            )

            # Create an asynchronous HTTP session
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # Check the type of library (Movie or TV)
                if library_type == "Movie":
                    # Process the user's movie library
                    process_task.append(
                        self.process_movie_library(
                            user_watched,
                            user_id,
                            library_id,
                            library_title,
                            session,
                            user_name=user_name,
                        )
                    )
                elif library_type in ["Series", "Episode"]:
                    # Process the user's TV library
                    process_task.append(
                        self.process_tv_library(
                            user_watched,
                            user_id,
                            library_id,
                            library_title,
                            session,
                            user_name=user_name,
                        )
                    )

                await asyncio.gather(*process_task)
            # Log the completion of generating watched content
            logger(
                f"Jellyfin: Got watched for {user_name} in library {library_title}", 1
            )
            # Log the watched content for the user and library
            if library_title in user_watched[user_name]:
                logger(f"Jellyfin: {user_watched[user_name][library_title]}", 3)

            # Return the generated watched content for the user
            return user_watched

        except Exception as e:
            # Log an error if there's a failure in getting watched content
            logger(
                f"Jellyfin: Failed to get watched for {user_name} in library {library_title}, Error: {e}",
                2,
            )
            # Log the traceback for debugging purposes
            logger(traceback.format_exc(), 2)
            # Return an empty dictionary in case of an error
            return {}

    async def get_users_watched(
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
            tasks_watched = []

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                libraries = await self.query(f"/Users/{user_id}/Views", "get", session)

                tasks_libraries = [
                    asyncio.ensure_future(
                        self.query(
                            f"/Users/{user_id}/Items"
                            f"?ParentId={library['Id']}&Filters=IsPlayed&Recursive=True&excludeItemTypes=Folder&limit=100",
                            "get",
                            session,
                            identifiers={
                                "library_id": library["Id"],
                                "library_title": library["Name"],
                            },
                        )
                    )
                    for library in libraries["Items"]
                ]

                libraries_results = await asyncio.gather(
                    *tasks_libraries, return_exceptions=True
                )

                for watched in libraries_results:
                    if not watched["Items"]:
                        continue

                    library_id = watched["Identifiers"]["library_id"]
                    library_title = watched["Identifiers"]["library_title"]

                    # Get all library types excluding "Folder"
                    types = {
                        x["Type"]
                        for x in watched["Items"]
                        if x["Type"] in {"Movie", "Series", "Episode"}
                    }

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

                    # If there are multiple types in the library, raise an error
                    if not types:
                        all_types = {x["Type"] for x in watched["Items"]}
                        logger(
                            f"Jellyfin: Skipping Library {library_title} found types: {types}, all types: {all_types}",
                            1,
                        )
                        continue

                    for library_type in types:
                        # Get watched for the user
                        task = asyncio.ensure_future(
                            self.get_user_library_watched(
                                user_name,
                                user_id,
                                library_type,
                                library_id,
                                library_title,
                            )
                        )
                        tasks_watched.append(task)

            watched = await asyncio.gather(*tasks_watched, return_exceptions=True)

            return watched

        except Exception as e:
            logger(f"Jellyfin: Failed to get users watched, Error: {e}", 2)
            raise Exception(e)

    async def get_watched(
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

            watched = await asyncio.gather(*watched, return_exceptions=True)
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

    async def update_user_watched_movies(
        self,
        videos,
        videos_movies_ids,
        user_name,
        user_id,
        library,
        library_id,
        session,
        dryrun,
    ):
        try:
            # Fetch movies from Jellyfin
            jellyfin_search = await self.query(
                f"/Users/{user_id}/Items"
                + f"?SortBy=SortName&SortOrder=Ascending&Recursive=True&ParentId={library_id}"
                + "&isPlayed=false&Fields=ItemCounts,ProviderIds,MediaSources&IncludeItemTypes=Movie",
                "get",
                session,
            )

            # Iterate through each movie in Jellyfin
            for jellyfin_video in jellyfin_search["Items"]:
                movie_status = None

                # Get status based on movie locations
                if "MediaSources" in jellyfin_video:
                    for movie_location in jellyfin_video["MediaSources"]:
                        # Check if the movie location is in the mark list
                        if "Path" in movie_location:
                            if (
                                contains_nested(
                                    movie_location["Path"].split("/")[-1],
                                    videos_movies_ids["locations"],
                                )
                                is not None
                            ):
                                # Set the movie status based on videos status
                                for video in videos:
                                    if (
                                        contains_nested(
                                            movie_location["Path"].split("/")[-1],
                                            video["locations"],
                                        )
                                        is not None
                                    ):
                                        movie_status = video["status"]
                                        break

                # If the movie status is still not found, check ProviderIds
                if not movie_status:
                    for (
                        movie_provider_source,
                        movie_provider_id,
                    ) in jellyfin_video["ProviderIds"].items():
                        if movie_provider_source.lower() in videos_movies_ids:
                            if (
                                movie_provider_id.lower()
                                in videos_movies_ids[movie_provider_source.lower()]
                            ):
                                # Iterate through user-provided videos to find a match
                                for video in videos:
                                    if movie_provider_id.lower() in video.get(
                                        movie_provider_source.lower(), []
                                    ):
                                        # Get the status of the matched video
                                        movie_status = video["status"]
                                        break
                                # Exit the loop if a match is found
                                break

                # If a movie status is found, process it
                if movie_status:
                    jellyfin_video_id = jellyfin_video["Id"]
                    if movie_status["completed"]:
                        msg = f"Jellyfin: {jellyfin_video.get('Name')} as watched for {user_name} in {library}"
                        if not dryrun:
                            logger(msg, 5)
                            await self.query(
                                f"/Users/{user_id}/PlayedItems/{jellyfin_video_id}",
                                "post",
                                session,
                            )
                        else:
                            logger(msg, 6)

                        log_marked(user_name, library, jellyfin_video.get("Name"))
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
                    # Log that the movie is not in the mark list
                    logger(
                        f"Jellyfin: Skipping movie {jellyfin_video.get('Name')} as it is not in mark list for {user_name}",
                        1,
                    )

        except Exception as e:
            # Log any errors that occur during the process
            logger(
                f"Jellyfin: Error updating watched for {user_name} in library {library}, {e}",
                2,
            )
            logger(traceback.format_exc(), 2)
            raise Exception(e)

    async def update_user_watched_shows(
        self,
        user_id,
        user_name,
        library_id,
        library,
        videos,
        videos_shows_ids,
        videos_episodes_ids,
        dryrun,
        session,
    ):
        jellyfin_search = await self.query(
            f"/Users/{user_id}/Items"
            + f"?SortBy=SortName&SortOrder=Ascending&Recursive=True&ParentId={library_id}"
            + "&Fields=ItemCounts,ProviderIds,Path&IncludeItemTypes=Series",
            "get",
            session,
        )
        jellyfin_shows = [x for x in jellyfin_search["Items"]]

        for jellyfin_show in jellyfin_shows:
            show_found = False

            if "Path" in jellyfin_show:
                if (
                    contains_nested(
                        jellyfin_show["Path"].split("/")[-1],
                        videos_shows_ids["locations"],
                    )
                    is not None
                ):
                    show_found = True
                    episode_videos = []

                    for show, seasons in videos.items():
                        show = {k: v for k, v in show}
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

            if not show_found:
                for show_provider_source, show_provider_id in jellyfin_show[
                    "ProviderIds"
                ].items():
                    if show_provider_source.lower() in videos_shows_ids:
                        if (
                            show_provider_id.lower()
                            in videos_shows_ids[show_provider_source.lower()]
                        ):
                            show_found = True
                            episode_videos = []
                            for show, seasons in videos.items():
                                show = {k: v for k, v in show}
                                if show_provider_id.lower() in show.get(
                                    show_provider_source.lower(), []
                                ):
                                    for season in seasons.values():
                                        for episode in season:
                                            episode_videos.append(episode)

            if show_found:
                logger(
                    f"Jellyfin: Updating watched for {user_name} in library {library} for show {jellyfin_show.get('Name')}",
                    1,
                )
                jellyfin_show_id = jellyfin_show["Id"]
                jellyfin_episodes = await self.query(
                    f"/Shows/{jellyfin_show_id}/Episodes"
                    + f"?userId={user_id}&Fields=ItemCounts,ProviderIds,MediaSources",
                    "get",
                    session,
                )

                for jellyfin_episode in jellyfin_episodes["Items"]:
                    episode_status = None

                    if "MediaSources" in jellyfin_episode:
                        for episode_location in jellyfin_episode["MediaSources"]:
                            if "Path" in episode_location:
                                if (
                                    contains_nested(
                                        episode_location["Path"].split("/")[-1],
                                        videos_episodes_ids["locations"],
                                    )
                                    is not None
                                ):
                                    for episode in episode_videos:
                                        if (
                                            contains_nested(
                                                episode_location["Path"].split("/")[-1],
                                                episode["locations"],
                                            )
                                            is not None
                                        ):
                                            episode_status = episode["status"]
                                            break
                                    break

                    if not episode_status:
                        for (
                            episode_provider_source,
                            episode_provider_id,
                        ) in jellyfin_episode["ProviderIds"].items():
                            if episode_provider_source.lower() in videos_episodes_ids:
                                if (
                                    episode_provider_id.lower()
                                    in videos_episodes_ids[
                                        episode_provider_source.lower()
                                    ]
                                ):
                                    for episode in episode_videos:
                                        if episode_provider_source.lower() in episode:
                                            if (
                                                episode_provider_id.lower()
                                                in episode[
                                                    episode_provider_source.lower()
                                                ]
                                            ):
                                                episode_status = episode["status"]
                                                break
                                    break

                    if episode_status:
                        jellyfin_episode_id = jellyfin_episode["Id"]
                        if episode_status["completed"]:
                            msg = (
                                f"Jellyfin: {jellyfin_episode['SeriesName']} {jellyfin_episode['SeasonName']} Episode {jellyfin_episode.get('IndexNumber')} {jellyfin_episode.get('Name')}"
                                + f" as watched for {user_name} in {library}"
                            )
                            if not dryrun:
                                logger(msg, 5)
                                await self.query(
                                    f"/Users/{user_id}/PlayedItems/{jellyfin_episode_id}",
                                    "post",
                                    session,
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

    async def update_user_watched(
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

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                tasks = []
                if videos_movies_ids:
                    tasks.append(
                        self.update_user_watched_movies(
                            videos,
                            videos_movies_ids,
                            user_name,
                            user_id,
                            library,
                            library_id,
                            session,
                            dryrun,
                        )
                    )

                # TV Shows
                if videos_shows_ids and videos_episodes_ids:
                    tasks.append(
                        self.update_user_watched_shows(
                            user_id,
                            user_name,
                            library_id,
                            library,
                            videos,
                            videos_shows_ids,
                            videos_episodes_ids,
                            dryrun,
                            session,
                        )
                    )

                await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger(
                f"Jellyfin: Error updating watched for {user_name} in library {library}, {e}",
                2,
            )
            logger(traceback.format_exc(), 2)
            raise Exception(e)

    async def update_watched(
        self, watched_list, user_mapping=None, library_mapping=None, dryrun=False
    ):
        try:
            tasks = []
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
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
                    for key in self.users.keys():
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

                    jellyfin_libraries = await self.query(
                        f"/Users/{user_id}/Views", "get", session
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
                            task = self.update_user_watched(
                                user_name, user_id, library, library_id, videos, dryrun
                            )
                            tasks.append(task)

            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger(f"Jellyfin: Error updating watched, {e}", 2)
            raise Exception(e)
