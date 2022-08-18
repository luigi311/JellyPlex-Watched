import asyncio, aiohttp
from src.functions import logger, search_mapping, check_skip_logic, generate_library_guids_dict, combine_watched_dicts

class Jellyfin():
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
            headers = {
                "Accept": "application/json",
                "X-Emby-Token": self.token
            }
            authorization = (
                'MediaBrowser , '
                'Client="other", '
                'Device="script", '
                'DeviceId="script", '
                'Version="0.0.0"'
            )
            headers["X-Emby-Authorization"] = authorization

            if query_type == "get":
                async with session.get(self.baseurl + query, headers=headers) as response:
                    results = await response.json()

            elif query_type == "post":
                async with session.post(self.baseurl + query, headers=headers) as response:
                    results = await response.json()

            # append identifiers to results
            if identifiers:
                results["Identifiers"] = identifiers
            return results

        except Exception as e:
                logger(f"Jellyfin: Query failed {e}", 2)
                raise Exception(e)


    async def get_users(self):
        try:
            users = {}

            query_string = "/Users"
            async with aiohttp.ClientSession() as session:
                response = await self.query(query_string, "get", session)

            # If reponse is not empty
            if response:
                for user in response:
                    users[user["Name"]] = user["Id"]

            return users
        except Exception as e:
            logger(f"Jellyfin: Get users failed {e}", 2)
            raise Exception(e)


    async def get_user_watched(self, user_name, user_id, library_type, library_id, library_title):
        try:
            user_name = user_name.lower()
            user_watched = {}
            user_watched[user_name] = {}

            logger(f"Jellyfin: Generating watched for {user_name} in library {library_title}", 0)
            # Movies
            async with aiohttp.ClientSession() as session:
                if library_type == "Movie":
                    user_watched[user_name][library_title] = []
                    watched = await self.query(f"/Users/{user_id}/Items?ParentId={library_id}&Filters=IsPlayed&Fields=ItemCounts,ProviderIds,MediaSources", "get", session)
                    for movie in watched["Items"]:
                        if movie["UserData"]["Played"] == True:
                            movie_guids = {}
                            movie_guids["title"] = movie["Name"]
                            if "ProviderIds" in movie:
                                # Lowercase movie["ProviderIds"] keys
                                movie_guids = {k.lower(): v for k, v in movie["ProviderIds"].items()}
                            if "MediaSources" in movie:
                                movie_guids["locations"] = tuple([x["Path"].split("/")[-1] for x in movie["MediaSources"]])
                            user_watched[user_name][library_title].append(movie_guids)

                # TV Shows
                if library_type == "Series":
                    user_watched[user_name][library_title] = {}
                    watched_shows = await self.query(f"/Users/{user_id}/Items?ParentId={library_id}&isPlaceHolder=false&Fields=ProviderIds,Path,RecursiveItemCount", "get", session)
                    watched_shows_filtered = []
                    for show in watched_shows["Items"]:
                        if "PlayedPercentage" in  show["UserData"]:
                            if show["UserData"]["PlayedPercentage"] > 0:
                                watched_shows_filtered.append(show)
                    seasons_tasks = []
                    for show in watched_shows_filtered:
                        show_guids = {k.lower(): v for k, v in show["ProviderIds"].items()}
                        show_guids["title"] = show["Name"]
                        show_guids["locations"] = tuple([show["Path"].split("/")[-1]])
                        show_guids = frozenset(show_guids.items())
                        identifiers = {"show_guids": show_guids, "show_id": show["Id"]}
                        task =  asyncio.ensure_future(self.query(f"/Shows/{show['Id']}/Seasons?userId={user_id}&isPlaceHolder=false&Fields=ProviderIds,RecursiveItemCount", "get", session, frozenset(identifiers.items())))
                        seasons_tasks.append(task)

                    seasons_watched = await asyncio.gather(*seasons_tasks)
                    seasons_watched_filtered = []

                    for seasons in seasons_watched:
                        seasons_watched_filtered_dict = {}
                        seasons_watched_filtered_dict["Identifiers"] = seasons["Identifiers"]
                        seasons_watched_filtered_dict["Items"] = []
                        for season in seasons["Items"]:
                            if "PlayedPercentage" in season["UserData"]:
                                if season["UserData"]["PlayedPercentage"] > 0:
                                    seasons_watched_filtered_dict["Items"].append(season)

                        if seasons_watched_filtered_dict["Items"]:
                            seasons_watched_filtered.append(seasons_watched_filtered_dict)

                    episodes_tasks = []
                    for seasons in seasons_watched_filtered:
                        if len(seasons["Items"]) > 0:
                            for season in seasons["Items"]:
                                season_identifiers = dict(seasons["Identifiers"])
                                season_identifiers["season_id"] = season["Id"]
                                season_identifiers["season_name"] = season["Name"]
                                task = asyncio.ensure_future(self.query(f"/Shows/{season_identifiers['show_id']}/Episodes?seasonId={season['Id']}&userId={user_id}&isPlaceHolder=false&isPlayed=true&Fields=ProviderIds,MediaSources", "get", session, frozenset(season_identifiers.items())))
                                episodes_tasks.append(task)

                    watched_episodes = await asyncio.gather(*episodes_tasks)
                    for episodes in watched_episodes:
                        if len(episodes["Items"]) > 0:
                            for episode in episodes["Items"]:
                                if episode["UserData"]["Played"] == True:
                                    if "ProviderIds" in episode or "MediaSources" in episode:
                                        episode_identifiers = dict(episodes["Identifiers"])
                                        show_guids = episode_identifiers["show_guids"]
                                        if show_guids not in user_watched[user_name][library_title]:
                                            user_watched[user_name][library_title][show_guids] = {}
                                        if episode_identifiers["season_name"] not in user_watched[user_name][library_title][show_guids]:
                                            user_watched[user_name][library_title][show_guids][episode_identifiers["season_name"]] = []

                                        episode_guids = {}
                                        if "ProviderIds" in episode:
                                            episode_guids = {k.lower(): v for k, v in episode["ProviderIds"].items()}
                                        if "MediaSources" in episode:
                                            episode_guids["locations"] = tuple([x["Path"].split("/")[-1] for x in episode["MediaSources"]])
                                        user_watched[user_name][library_title][show_guids][episode_identifiers["season_name"]].append(episode_guids)

            return user_watched
        except Exception as e:
            logger(f"Jellyfin: Failed to get watched for {user_name} in library {library_title}, Error: {e}", 2)
            raise Exception(e)


    async def get_users_watched(self, user_name, user_id, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, library_mapping):
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
                    identifiers = {"library_id": library_id, "library_title": library_title}
                    task = asyncio.ensure_future(self.query(f"/Users/{user_id}/Items?ParentId={library_id}&Filters=IsPlayed&limit=1", "get", session, identifiers=identifiers))
                    tasks_libraries.append(task)

                libraries = await asyncio.gather(*tasks_libraries, return_exceptions=True)

                for watched in libraries:
                    if len(watched["Items"]) == 0:
                        continue

                    library_id = watched["Identifiers"]["library_id"]
                    library_title = watched["Identifiers"]["library_title"]
                    library_type = watched["Items"][0]["Type"]

                    skip_reason = check_skip_logic(library_title, library_type, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, library_mapping)

                    if skip_reason:
                        logger(f"Jellyfin: Skipping library {library_title} {skip_reason}", 1)
                        continue

                    # Get watched for user
                    task = asyncio.ensure_future(self.get_user_watched(user_name, user_id, library_type, library_id, library_title))
                    tasks_watched.append(task)

            watched = await asyncio.gather(*tasks_watched, return_exceptions=True)
            return watched
        except Exception as e:
            logger(f"Jellyfin: Failed to get users watched, Error: {e}", 2)
            raise Exception(e)


    async def get_watched(self, users, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, library_mapping=None):
        try:
            users_watched = {}
            watched = []

            for user_name, user_id in users.items():
                watched.append(await self.get_users_watched(user_name, user_id, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, library_mapping))

            for user_watched in watched:
                user_watched_temp = combine_watched_dicts(user_watched)
                for user, user_watched_temp in user_watched_temp.items():
                    if user not in users_watched:
                        users_watched[user] = {}
                    users_watched[user].update(user_watched_temp)

            return users_watched
        except Exception as e:
            logger(f"Jellyfin: Failed to get watched, Error: {e}", 2)
            raise Exception(e)


    async def update_user_watched(self, user_name, user_id, library, library_id, videos, dryrun):
        try:
            logger(f"Jellyfin: Updating watched for {user_name} in library {library}", 1)
            videos_shows_ids, videos_episodes_ids, videos_movies_ids = generate_library_guids_dict(videos)

            logger(f"Jellyfin: mark list\nShows: {videos_shows_ids}\nEpisodes: {videos_episodes_ids}\nMovies: {videos_movies_ids}", 1)
            async with aiohttp.ClientSession() as session:
                if videos_movies_ids:
                    jellyfin_search = await self.query(f"/Users/{user_id}/Items?SortBy=SortName&SortOrder=Ascending&Recursive=false&ParentId={library_id}&isPlayed=false&Fields=ItemCounts,ProviderIds,MediaSources", "get", session)
                    for jellyfin_video in jellyfin_search["Items"]:
                            movie_found = False

                            if "MediaSources" in jellyfin_video:
                                for movie_location in jellyfin_video["MediaSources"]:
                                    if movie_location["Path"].split("/")[-1] in videos_movies_ids["locations"]:
                                        movie_found = True
                                        break

                            if not movie_found:
                                for movie_provider_source, movie_provider_id in jellyfin_video["ProviderIds"].items():
                                    if movie_provider_source.lower() in videos_movies_ids:
                                        if movie_provider_id.lower() in videos_movies_ids[movie_provider_source.lower()]:
                                            movie_found = True
                                            break

                            if movie_found:
                                jellyfin_video_id = jellyfin_video["Id"]
                                msg = f"{jellyfin_video['Name']} as watched for {user_name} in {library} for Jellyfin"
                                if not dryrun:
                                    logger(f"Marking {msg}", 0)
                                    await self.query(f"/Users/{user_id}/PlayedItems/{jellyfin_video_id}", "post", session)
                                else:
                                    logger(f"Dryrun {msg}", 0)
                            else:
                                logger(f"Jellyfin: Skipping movie {jellyfin_video['Name']} as it is not in mark list for {user_name}", 1)



                # TV Shows
                if videos_shows_ids and videos_episodes_ids:
                    jellyfin_search = await self.query(f"/Users/{user_id}/Items?SortBy=SortName&SortOrder=Ascending&Recursive=false&ParentId={library_id}&isPlayed=false&Fields=ItemCounts,ProviderIds,Path", "get", session)
                    jellyfin_shows = [x for x in jellyfin_search["Items"]]

                    for jellyfin_show in jellyfin_shows:
                        show_found = False

                        if "Path" in jellyfin_show:
                            if jellyfin_show["Path"].split("/")[-1] in videos_shows_ids["locations"]:
                                show_found = True

                        if not show_found:
                            for show_provider_source, show_provider_id in jellyfin_show["ProviderIds"].items():
                                if show_provider_source.lower() in videos_shows_ids:
                                    if show_provider_id.lower() in videos_shows_ids[show_provider_source.lower()]:
                                        show_found = True
                                        break

                        if show_found:
                            logger(f"Jellyfin: Updating watched for {user_name} in library {library} for show {jellyfin_show['Name']}", 1)
                            jellyfin_show_id = jellyfin_show["Id"]
                            jellyfin_episodes = await self.query(f"/Shows/{jellyfin_show_id}/Episodes?userId={user_id}&Fields=ItemCounts,ProviderIds,MediaSources", "get", session)

                            for jellyfin_episode in jellyfin_episodes["Items"]:
                                episode_found = False

                                if "MediaSources" in jellyfin_episode:
                                    for episode_location in jellyfin_episode["MediaSources"]:
                                        if episode_location["Path"].split("/")[-1] in videos_episodes_ids["locations"]:
                                            episode_found = True
                                            break

                                if not episode_found:
                                    for episode_provider_source, episode_provider_id in jellyfin_episode["ProviderIds"].items():
                                        if episode_provider_source.lower() in videos_episodes_ids:
                                            if episode_provider_id.lower() in videos_episodes_ids[episode_provider_source.lower()]:
                                                episode_found = True
                                                break

                                if episode_found:
                                    jellyfin_episode_id = jellyfin_episode["Id"]
                                    msg = f"{jellyfin_episode['SeriesName']} {jellyfin_episode['SeasonName']} Episode {jellyfin_episode['Name']} as watched for {user_name} in {library} for Jellyfin"
                                    if not dryrun:
                                        logger(f"Marked {msg}", 0)
                                        await self.query(f"/Users/{user_id}/PlayedItems/{jellyfin_episode_id}", "post", session)
                                    else:
                                        logger(f"Dryrun {msg}", 0)
                                else:
                                    logger(f"Jellyfin: Skipping episode {jellyfin_episode['Name']} as it is not in mark list for {user_name}", 1)
                        else:
                            logger(f"Jellyfin: Skipping show {jellyfin_show['Name']} as it is not in mark list for {user_name}", 1)

            if not videos_movies_ids and not videos_shows_ids and not videos_episodes_ids:
                logger(f"Jellyfin: No videos to mark as watched for {user_name} in library {library}", 1)

        except Exception as e:
            logger(f"Jellyfin: Error updating watched for {user_name} in library {library}", 2)
            raise Exception(e)


    async def update_watched(self, watched_list, user_mapping=None, library_mapping=None, dryrun=False):
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

                    jellyfin_libraries = await self.query(f"/Users/{user_id}/Views", "get", session)
                    jellyfin_libraries = [x for x in jellyfin_libraries["Items"]]

                    for library, videos in libraries.items():
                        library_other = None
                        if library_mapping:
                            if library in library_mapping.keys():
                                library_other = library_mapping[library]
                            elif library in library_mapping.values():
                                library_other = search_mapping(library_mapping, library)


                        if library.lower() not in [x["Name"].lower() for x in jellyfin_libraries]:
                            if library_other:
                                if library_other.lower() in [x["Name"].lower() for x in jellyfin_libraries]:
                                    logger(f"Jellyfin: Library {library} not found, but {library_other} found, using {library_other}", 1)
                                    library = library_other
                                else:
                                    logger(f"Jellyfin: Library {library} or {library_other} not found in library list", 2)
                                    continue
                            else:
                                logger(f"Jellyfin: Library {library} not found in library list", 2)
                                continue

                        library_id = None
                        for jellyfin_library in jellyfin_libraries:
                            if jellyfin_library["Name"] == library:
                                library_id = jellyfin_library["Id"]
                                continue

                        if library_id:
                            task = self.update_user_watched(user_name, user_id, library, library_id, videos, dryrun)
                            tasks.append(task)

            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger(f"Jellyfin: Error updating watched, {e}", 2)
            raise Exception(e)
