import asyncio, aiohttp, traceback

from src.functions import (
    logger,
    search_mapping,
)
from src.library import (
    check_skip_logic,
    generate_library_guids_dict,
)
from src.watched import (
    combine_watched_dicts,
)


class Jellyfin:
    def __init__(self, baseurl, token):
        self.baseurl = baseurl
        self.token = token

        if not self.baseurl:
            raise Exception("Jellyfin baseurl not set")

        if not self.token:
            raise Exception("Jellyfin token not set")

        self.users = asyncio.run(self.get_users())

    async def query(self, query, query_type, session, identifiers=None):
        try:
            results = None
            headers = {"Accept": "application/json", "X-Emby-Token": self.token}
            authorization = (
                "MediaBrowser , "
                'Client="other", '
                'Device="script", '
                'DeviceId="script", '
                'Version="0.0.0"'
            )
            headers["X-Emby-Authorization"] = authorization

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

    async def get_users(self):
        try:
            users = {}

            query_string = "/Users"
            async with aiohttp.ClientSession() as session:
                response = await self.query(query_string, "get", session)

            # If response is not empty
            if response:
                for user in response:
                    users[user["Name"]] = user["Id"]

            return users
        except Exception as e:
            logger(f"Jellyfin: Get users failed {e}", 2)
            raise Exception(e)

    async def get_user_library_watched(
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

            async with aiohttp.ClientSession() as session:
                # Movies
                if library_type == "Movie":
                    user_watched[user_name][library_title] = []
                    watched = await self.query(
                        f"/Users/{user_id}/Items"
                        + f"?ParentId={library_id}&Filters=IsPlayed&IncludeItemTypes=Movie&Recursive=True&Fields=ItemCounts,ProviderIds,MediaSources",
                        "get",
                        session,
                    )

                    for movie in watched["Items"]:
                        # Check if the movie has been played
                        if (
                            movie["UserData"]["Played"] is True
                            and "MediaSources" in movie
                            and movie["MediaSources"] is not {}
                        ):
                            logger(
                                f"Jellyfin: Adding {movie['Name']} to {user_name} watched list",
                                3,
                            )
                            if "ProviderIds" in movie:
                                logger(
                                    f"Jellyfin: {movie['Name']} {movie['ProviderIds']} {movie['MediaSources']}",
                                    3,
                                )
                            else:
                                logger(
                                    f"Jellyfin: {movie['Name']} {movie['MediaSources']['Path']}",
                                    3,
                                )

                            # Create a dictionary for the movie with its title
                            movie_guids = {"title": movie["Name"]}

                            # If the movie has provider IDs, add them to the dictionary
                            if "ProviderIds" in movie:
                                movie_guids.update(
                                    {
                                        k.lower(): v
                                        for k, v in movie["ProviderIds"].items()
                                    }
                                )

                            # If the movie has media sources, add them to the dictionary
                            if "MediaSources" in movie:
                                movie_guids["locations"] = tuple(
                                    [
                                        x["Path"].split("/")[-1]
                                        for x in movie["MediaSources"]
                                    ]
                                )

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
                    watched_shows = await self.query(
                        f"/Users/{user_id}/Items"
                        + f"?ParentId={library_id}&isPlaceHolder=false&IncludeItemTypes=Series&Recursive=True&Fields=ProviderIds,Path,RecursiveItemCount",
                        "get",
                        session,
                    )

                    # Filter the list of shows to only include those that have been partially or fully watched
                    watched_shows_filtered = []
                    for show in watched_shows["Items"]:
                        if "PlayedPercentage" in show["UserData"]:
                            if show["UserData"]["PlayedPercentage"] > 0:
                                watched_shows_filtered.append(show)

                    # Create a list of tasks to retrieve the seasons of each watched show
                    seasons_tasks = []
                    for show in watched_shows_filtered:
                        logger(
                            f"Jellyfin: Adding {show['Name']} to {user_name} watched list",
                            3,
                        )
                        show_guids = {
                            k.lower(): v for k, v in show["ProviderIds"].items()
                        }
                        show_guids["title"] = show["Name"]
                        show_guids["locations"] = tuple([show["Path"].split("/")[-1]])
                        show_guids = frozenset(show_guids.items())
                        show_identifiers = {
                            "show_guids": show_guids,
                            "show_id": show["Id"],
                        }

                        season_task = asyncio.ensure_future(
                            self.query(
                                f"/Shows/{show['Id']}/Seasons"
                                + f"?userId={user_id}&isPlaceHolder=false&Fields=ProviderIds,RecursiveItemCount",
                                "get",
                                session,
                                frozenset(show_identifiers.items()),
                            )
                        )
                        seasons_tasks.append(season_task)

                    # Retrieve the seasons for each watched show
                    seasons_watched = await asyncio.gather(*seasons_tasks)

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
                                    seasons_watched_filtered_dict["Items"].append(
                                        season
                                    )

                        if seasons_watched_filtered_dict["Items"]:
                            seasons_watched_filtered.append(
                                seasons_watched_filtered_dict
                            )

                    # Create a list of tasks to retrieve the episodes of each watched season
                    episodes_tasks = []
                    for seasons in seasons_watched_filtered:
                        if len(seasons["Items"]) > 0:
                            for season in seasons["Items"]:
                                season_identifiers = dict(seasons["Identifiers"])
                                season_identifiers["season_id"] = season["Id"]
                                season_identifiers["season_name"] = season["Name"]
                                episode_task = asyncio.ensure_future(
                                    self.query(
                                        f"/Shows/{season_identifiers['show_id']}/Episodes"
                                        + f"?seasonId={season['Id']}&userId={user_id}&isPlaceHolder=false&isPlayed=true&Fields=ProviderIds,MediaSources",
                                        "get",
                                        session,
                                        frozenset(season_identifiers.items()),
                                    )
                                )
                                episodes_tasks.append(episode_task)

                    # Retrieve the episodes for each watched season
                    watched_episodes = await asyncio.gather(*episodes_tasks)

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
                                    episode["UserData"]["Played"] is True
                                    and "MediaSources" in episode
                                    and episode["MediaSources"] is not {}
                                ):
                                    # Create a dictionary for the episode with its provider IDs and media sources
                                    episode_dict = {
                                        k.lower(): v
                                        for k, v in episode["ProviderIds"].items()
                                    }
                                    episode_dict["title"] = episode["Name"]
                                    episode_dict["locations"] = tuple(
                                        [
                                            x["Path"].split("/")[-1]
                                            for x in episode["MediaSources"]
                                        ]
                                    )
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
                                season_dict["Identifiers"]["season_name"]
                                not in user_watched[user_name][library_title][
                                    season_dict["Identifiers"]["show_guids"]
                                ]
                            ):
                                user_watched[user_name][library_title][
                                    season_dict["Identifiers"]["show_guids"]
                                ][season_dict["Identifiers"]["season_name"]] = []

                            user_watched[user_name][library_title][
                                season_dict["Identifiers"]["show_guids"]
                            ][season_dict["Identifiers"]["season_name"]] = season_dict[
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

            tasks_libraries = []
            async with aiohttp.ClientSession() as session:
                libraries = await self.query(f"/Users/{user_id}/Views", "get", session)
                for library in libraries["Items"]:
                    library_id = library["Id"]
                    library_title = library["Name"]
                    identifiers = {
                        "library_id": library_id,
                        "library_title": library_title,
                    }
                    task = asyncio.ensure_future(
                        self.query(
                            f"/Users/{user_id}/Items"
                            + f"?ParentId={library_id}&Filters=IsPlayed&Recursive=True&excludeItemTypes=Folder&limit=100",
                            "get",
                            session,
                            identifiers=identifiers,
                        )
                    )
                    tasks_libraries.append(task)

                libraries = await asyncio.gather(
                    *tasks_libraries, return_exceptions=True
                )

                for watched in libraries:
                    if len(watched["Items"]) == 0:
                        continue

                    library_id = watched["Identifiers"]["library_id"]
                    library_title = watched["Identifiers"]["library_title"]
                    # Get all library types excluding "Folder"
                    types = set(
                        [
                            x["Type"]
                            for x in watched["Items"]
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
                        all_types = set([x["Type"] for x in watched["Items"]])
                        logger(
                            f"Jellyfin: Skipping Library {library_title} found types: {types}, all types: {all_types}",
                            1,
                        )
                        continue

                    for library_type in types:
                        # Get watched for user
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

            logger(
                f"Jellyfin: mark list\nShows: {videos_shows_ids}\nEpisodes: {videos_episodes_ids}\nMovies: {videos_movies_ids}",
                1,
            )
            async with aiohttp.ClientSession() as session:
                if videos_movies_ids:
                    jellyfin_search = await self.query(
                        f"/Users/{user_id}/Items"
                        + f"?SortBy=SortName&SortOrder=Ascending&Recursive=True&ParentId={library_id}"
                        + "&isPlayed=false&Fields=ItemCounts,ProviderIds,MediaSources&IncludeItemTypes=Movie",
                        "get",
                        session,
                    )
                    for jellyfin_video in jellyfin_search["Items"]:
                        movie_found = False

                        if "MediaSources" in jellyfin_video:
                            for movie_location in jellyfin_video["MediaSources"]:
                                if (
                                    movie_location["Path"].split("/")[-1]
                                    in videos_movies_ids["locations"]
                                ):
                                    movie_found = True
                                    break

                        if not movie_found:
                            for (
                                movie_provider_source,
                                movie_provider_id,
                            ) in jellyfin_video["ProviderIds"].items():
                                if movie_provider_source.lower() in videos_movies_ids:
                                    if (
                                        movie_provider_id.lower()
                                        in videos_movies_ids[
                                            movie_provider_source.lower()
                                        ]
                                    ):
                                        movie_found = True
                                        break

                        if movie_found:
                            jellyfin_video_id = jellyfin_video["Id"]
                            msg = f"{jellyfin_video['Name']} as watched for {user_name} in {library} for Jellyfin"
                            if not dryrun:
                                logger(f"Marking {msg}", 0)
                                await self.query(
                                    f"/Users/{user_id}/PlayedItems/{jellyfin_video_id}",
                                    "post",
                                    session,
                                )
                            else:
                                logger(f"Dryrun {msg}", 0)
                        else:
                            logger(
                                f"Jellyfin: Skipping movie {jellyfin_video['Name']} as it is not in mark list for {user_name}",
                                1,
                            )

                # TV Shows
                if videos_shows_ids and videos_episodes_ids:
                    jellyfin_search = await self.query(
                        f"/Users/{user_id}/Items"
                        + f"?SortBy=SortName&SortOrder=Ascending&Recursive=True&ParentId={library_id}"
                        + "&isPlayed=false&Fields=ItemCounts,ProviderIds,Path&IncludeItemTypes=Series",
                        "get",
                        session,
                    )
                    jellyfin_shows = [x for x in jellyfin_search["Items"]]

                    for jellyfin_show in jellyfin_shows:
                        show_found = False

                        if "Path" in jellyfin_show:
                            if (
                                jellyfin_show["Path"].split("/")[-1]
                                in videos_shows_ids["locations"]
                            ):
                                show_found = True

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
                                        break

                        if show_found:
                            logger(
                                f"Jellyfin: Updating watched for {user_name} in library {library} for show {jellyfin_show['Name']}",
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
                                episode_found = False

                                if "MediaSources" in jellyfin_episode:
                                    for episode_location in jellyfin_episode[
                                        "MediaSources"
                                    ]:
                                        if (
                                            episode_location["Path"].split("/")[-1]
                                            in videos_episodes_ids["locations"]
                                        ):
                                            episode_found = True
                                            break

                                if not episode_found:
                                    for (
                                        episode_provider_source,
                                        episode_provider_id,
                                    ) in jellyfin_episode["ProviderIds"].items():
                                        if (
                                            episode_provider_source.lower()
                                            in videos_episodes_ids
                                        ):
                                            if (
                                                episode_provider_id.lower()
                                                in videos_episodes_ids[
                                                    episode_provider_source.lower()
                                                ]
                                            ):
                                                episode_found = True
                                                break

                                if episode_found:
                                    jellyfin_episode_id = jellyfin_episode["Id"]
                                    msg = (
                                        f"{jellyfin_episode['SeriesName']} {jellyfin_episode['SeasonName']} Episode {jellyfin_episode['Name']}"
                                        + f" as watched for {user_name} in {library} for Jellyfin"
                                    )
                                    if not dryrun:
                                        logger(f"Marked {msg}", 0)
                                        await self.query(
                                            f"/Users/{user_id}/PlayedItems/{jellyfin_episode_id}",
                                            "post",
                                            session,
                                        )
                                    else:
                                        logger(f"Dryrun {msg}", 0)
                                else:
                                    logger(
                                        f"Jellyfin: Skipping episode {jellyfin_episode['Name']} as it is not in mark list for {user_name}",
                                        3,
                                    )
                        else:
                            logger(
                                f"Jellyfin: Skipping show {jellyfin_show['Name']} as it is not in mark list for {user_name}",
                                3,
                            )

            if (
                not videos_movies_ids
                and not videos_shows_ids
                and not videos_episodes_ids
            ):
                logger(
                    f"Jellyfin: No videos to mark as watched for {user_name} in library {library}",
                    1,
                )

        except Exception as e:
            logger(
                f"Jellyfin: Error updating watched for {user_name} in library {library}, {e}",
                2,
            )
            raise Exception(e)

    async def update_watched(
        self, watched_list, user_mapping=None, library_mapping=None, dryrun=False
    ):
        try:
            tasks = []
            async with aiohttp.ClientSession() as session:
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
