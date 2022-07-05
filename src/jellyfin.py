import requests
from src.functions import logger, search_mapping, str_to_bool, check_skip_logic, generate_library_guids_dict, future_thread_executor

class Jellyfin():
    def __init__(self, baseurl, token):
        self.baseurl = baseurl
        self.token = token
        self.session = requests.Session()

        if not self.baseurl:
            raise Exception("Jellyfin baseurl not set")

        if not self.token:
            raise Exception("Jellyfin token not set")

        self.users = self.get_users()


    def query(self, query, query_type):
        try:
            response = None

            headers = {
                "Accept": "application/json",
                "X-Emby-Token": self.token
            }
            if query_type == "get":
                response = self.session.get(self.baseurl + query, headers=headers)

            elif query_type == "post":
                authorization = (
                    'MediaBrowser , '
                    'Client="other", '
                    'Device="script", '
                    'DeviceId="script", '
                    'Version="0.0.0"'
                )
                headers["X-Emby-Authorization"] = authorization
                response = self.session.post(self.baseurl + query, headers=headers)

            return response.json()

        except Exception as e:
            logger(f"Jellyfin: Query failed {e}", 2)
            raise Exception(e)

    def get_users(self):
        try:
            users = {}

            query = "/Users"
            response = self.query(query, "get")

            # If reponse is not empty
            if response:
                for user in response:
                    users[user["Name"]] = user["Id"]

            return users
        except Exception as e:
            logger(f"Jellyfin: Get users failed {e}", 2)
            raise Exception(e)

    def get_user_watched(self, user_name, user_id, library_type, library_id, library_title):
        try:
            user_name = user_name.lower()
            user_watched = {}
            user_watched[user_name] = {}

            logger(f"Jellyfin: Generating watched for {user_name} in library {library_title}", 0)
            # Movies
            if library_type == "Movie":
                user_watched[user_name][library_title] = []
                watched = self.query(f"/Users/{user_id}/Items?SortBy=SortName&SortOrder=Ascending&Recursive=true&ParentId={library_id}&Filters=IsPlayed&Fields=ItemCounts,ProviderIds,MediaSources", "get")
                for movie in watched["Items"]:
                    if movie["UserData"]["Played"] == True:
                        movie_guids = {}
                        movie_guids["title"] = movie["Name"]
                        if movie["ProviderIds"]:
                            # Lowercase movie["ProviderIds"] keys
                            movie_guids = {k.lower(): v for k, v in movie["ProviderIds"].items()}
                        if movie["MediaSources"]:
                            movie_guids["locations"] = tuple([x["Path"].split("/")[-1] for x in movie["MediaSources"]])
                        user_watched[user_name][library_title].append(movie_guids)

            # TV Shows
            if library_type == "Episode":
                user_watched[user_name][library_title] = {}
                watched = self.query(f"/Users/{user_id}/Items?SortBy=SortName&SortOrder=Ascending&Recursive=true&ParentId={library_id}&Fields=ItemCounts,ProviderIds,Path", "get")
                watched_shows = [x for x in watched["Items"] if x["Type"] == "Series"]

                for show in watched_shows:
                    show_guids = {k.lower(): v for k, v in show["ProviderIds"].items()}
                    show_guids["title"] = show["Name"]
                    show_guids["locations"] = tuple([show["Path"].split("/")[-1]])
                    show_guids = frozenset(show_guids.items())
                    seasons = self.query(f"/Shows/{show['Id']}/Seasons?userId={user_id}&Fields=ItemCounts,ProviderIds", "get")
                    if len(seasons["Items"]) > 0:
                        for season in seasons["Items"]:
                            episodes = self.query(f"/Shows/{show['Id']}/Episodes?seasonId={season['Id']}&userId={user_id}&Fields=ItemCounts,ProviderIds,MediaSources", "get")
                            if len(episodes["Items"]) > 0:
                                for episode in episodes["Items"]:
                                    if episode["UserData"]["Played"] == True:
                                        if episode["ProviderIds"] or episode["MediaSources"]:
                                            if show_guids not in user_watched[user_name][library_title]:
                                                user_watched[user_name][library_title][show_guids] = {}
                                            if season["Name"] not in user_watched[user_name][library_title][show_guids]:
                                                user_watched[user_name][library_title][show_guids][season["Name"]] = []

                                            # Lowercase episode["ProviderIds"] keys
                                            episode_guids = {}
                                            if episode["ProviderIds"]:
                                                episode_guids = {k.lower(): v for k, v in episode["ProviderIds"].items()}
                                            if episode["MediaSources"]:
                                                episode_guids["locations"] = tuple([x["Path"].split("/")[-1] for x in episode["MediaSources"]])
                                            user_watched[user_name][library_title][show_guids][season["Name"]].append(episode_guids)

            return user_watched
        except Exception as e:
            logger(f"Jellyfin: Failed to get watched for {user_name} in library {library_title}, Error: {e}", 2)
            raise Exception(e)


    def get_watched(self, users, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, library_mapping=None):
        try:
            users_watched = {}
            args = []

            for user_name, user_id in users.items():
                # Get all libraries
                user_name = user_name.lower()

                libraries = self.query(f"/Users/{user_id}/Views", "get")["Items"]

                for library in libraries:
                    library_title = library["Name"]
                    library_id = library["Id"]
                    watched = self.query(f"/Users/{user_id}/Items?SortBy=SortName&SortOrder=Ascending&Recursive=true&ParentId={library_id}&Filters=IsPlayed&limit=1", "get")

                    if len(watched["Items"]) == 0:
                        logger(f"Jellyfin: No watched items found in library {library_title}", 1)
                        continue
                    else:
                        library_type = watched["Items"][0]["Type"]

                    skip_reason = check_skip_logic(library_title, library_type, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, library_mapping)

                    if skip_reason:
                        logger(f"Jellyfin: Skipping library {library_title} {skip_reason}", 1)
                        continue

                    args.append([self.get_user_watched, user_name, user_id, library_type, library_id, library_title])

            for user_watched in future_thread_executor(args):
                for user, user_watched_temp in user_watched.items():
                    if user not in users_watched:
                        users_watched[user] = {}
                    users_watched[user].update(user_watched_temp)

            return users_watched
        except Exception as e:
            logger(f"Jellyfin: Failed to get watched, Error: {e}", 2)
            raise Exception(e)

    def update_user_watched(self, user_name, user_id, library, library_id, videos, dryrun):
        try:
            logger(f"Jellyfin: Updating watched for {user_name} in library {library}", 1)
            library_search = self.query(f"/Users/{user_id}/Items?SortBy=SortName&SortOrder=Ascending&Recursive=true&ParentId={library_id}&limit=1", "get")
            library_type = library_search["Items"][0]["Type"]

            # Movies
            if library_type == "Movie":
                _, _, videos_movies_ids = generate_library_guids_dict(videos, 2)

                jellyfin_search = self.query(f"/Users/{user_id}/Items?SortBy=SortName&SortOrder=Ascending&Recursive=false&ParentId={library_id}&isPlayed=false&Fields=ItemCounts,ProviderIds,MediaSources", "get")
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
                                self.query(f"/Users/{user_id}/PlayedItems/{jellyfin_video_id}", "post")
                            else:
                                logger(f"Dryrun {msg}", 0)


            # TV Shows
            if library_type == "Episode":
                videos_shows_ids, videos_episode_ids, _ = generate_library_guids_dict(videos, 3)

                logger(f"Jellyfin: shows to mark {videos_shows_ids}\nepisodes to mark {videos_episode_ids}", 1)

                jellyfin_search = self.query(f"/Users/{user_id}/Items?SortBy=SortName&SortOrder=Ascending&Recursive=false&ParentId={library_id}&isPlayed=false&Fields=ItemCounts,ProviderIds,Path", "get")
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
                        jellyfin_episodes = self.query(f"/Shows/{jellyfin_show_id}/Episodes?userId={user_id}&Fields=ItemCounts,ProviderIds,MediaSources", "get")

                        for jellyfin_episode in jellyfin_episodes["Items"]:
                            episode_found = False

                            if "MediaSources" in jellyfin_episode:
                                for episode_location in jellyfin_episode["MediaSources"]:
                                    if episode_location["Path"].split("/")[-1] in videos_episode_ids["locations"]:
                                        episode_found = True
                                        break

                            if not episode_found:
                                for episode_provider_source, episode_provider_id in jellyfin_episode["ProviderIds"].items():
                                    if episode_provider_source.lower() in videos_episode_ids:
                                        if episode_provider_id.lower() in videos_episode_ids[episode_provider_source.lower()]:
                                            episode_found = True
                                            break

                            if episode_found:
                                jellyfin_episode_id = jellyfin_episode["Id"]
                                msg = f"{jellyfin_episode['SeriesName']} {jellyfin_episode['SeasonName']} Episode {jellyfin_episode['IndexNumber']} {jellyfin_episode['Name']} as watched for {user_name} in {library} for Jellyfin"
                                if not dryrun:
                                    logger(f"Marked {msg}", 0)
                                    self.query(f"/Users/{user_id}/PlayedItems/{jellyfin_episode_id}", "post")
                                else:
                                    logger(f"Dryrun {msg}", 0)
                            else:
                                logger(f"Jellyfin: Skipping episode {jellyfin_episode['SeriesName']} {jellyfin_episode['SeasonName']} Episode {jellyfin_episode['IndexNumber']} {jellyfin_episode['Name']} as it is not in mark list for {user_name}", 1)
                    else:
                        logger(f"Jellyfin: Skipping show {jellyfin_show['Name']} as it is not in mark list for {user_name}", 1)
            else:
                logger(f"Jellyfin: Library {library} is not a TV Show or Movie, skipping", 2)

        except Exception as e:
            logger(f"Jellyfin: Error updating watched for {user_name} in library {library}", 2)
            raise Exception(e)


    def update_watched(self, watched_list, user_mapping=None, library_mapping=None, dryrun=False):
        try:
            args = []
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

                jellyfin_libraries = self.query(f"/Users/{user_id}/Views", "get")["Items"]

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
                        args.append([self.update_user_watched, user_name, user_id, library, library_id, videos, dryrun])

            future_thread_executor(args)
        except Exception as e:
            logger(f"Jellyfin: Error updating watched", 2)
            raise Exception(e)
