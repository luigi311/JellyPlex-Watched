import requests, os
from dotenv import load_dotenv
from src.functions import logger, search_mapping, str_to_bool, check_skip_logic

load_dotenv(override=True)

jellyfin_baseurl = os.getenv("JELLYFIN_BASEURL")
jellyfin_token = os.getenv("JELLYFIN_TOKEN")

class Jellyfin():
    def __init__(self):
        self.baseurl = jellyfin_baseurl
        self.token = jellyfin_token

        if not self.baseurl:
            raise Exception("Jellyfin baseurl not set")
        
        if not self.token:
            raise Exception("Jellyfin token not set")

        self.users = self.get_users()


    def query(self, query, query_type):
        try:
            response = None

            if query_type == "get":
                response = requests.get(self.baseurl + query, headers={"accept":"application/json", "X-Emby-Token": self.token})
            
            elif query_type == "post":
                authorization = (
                    'MediaBrowser , '
                    'Client="other", '
                    'Device="script", '
                    'DeviceId="script", '
                    'Version="0.0.0"'
                )
                response = requests.post(self.baseurl + query, headers={"accept":"application/json", "X-Emby-Authorization": authorization, "X-Emby-Token": self.token})

            return response.json()
        except Exception as e:
            logger(e, 2)
            logger(response, 2)
            
    def get_users(self):
        users = {}

        query = "/Users"
        response = self.query(query, "get")
        
        # If reponse is not empty
        if response:
            for user in response:
                users[user["Name"]] = user["Id"]

        return users  

    def get_jellyfin_watched(self, users, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, library_mapping=None):
        users_watched = {}

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

                logger(f"Jellyfin: Generating watched for {user_name} in library {library_title}", 0)
                # Movies
                if library_type == "Movie":
                    watched = self.query(f"/Users/{user_id}/Items?SortBy=SortName&SortOrder=Ascending&Recursive=true&ParentId={library_id}&Filters=IsPlayed&Fields=ItemCounts,ProviderIds", "get")
                    for movie in watched["Items"]:
                        if movie["UserData"]["Played"] == True:
                            if movie["ProviderIds"]:
                                if user_name not in users_watched:
                                    users_watched[user_name] = {}
                                if library_title not in users_watched[user_name]:
                                    users_watched[user_name][library_title] = []
                                # Lowercase movie["ProviderIds"] keys
                                movie["ProviderIds"] = {k.lower(): v for k, v in movie["ProviderIds"].items()}
                                users_watched[user_name][library_title].append(movie["ProviderIds"])

                # TV Shows
                if library_type == "Episode":
                    watched = self.query(f"/Users/{user_id}/Items?SortBy=SortName&SortOrder=Ascending&Recursive=true&ParentId={library_id}", "get")
                    watched_shows = [x for x in watched["Items"] if x["Type"] == "Series"]

                    for show in watched_shows:
                        seasons = self.query(f"/Shows/{show['Id']}/Seasons?userId={user_id}&Fields=ItemCounts", "get")
                        if len(seasons["Items"]) > 0:
                            for season in seasons["Items"]:
                                episodes = self.query(f"/Shows/{show['Id']}/Episodes?seasonId={season['Id']}&userId={user_id}&Fields=ItemCounts,ProviderIds", "get")
                                if len(episodes["Items"]) > 0:
                                    for episode in episodes["Items"]:
                                        if episode["UserData"]["Played"] == True:
                                            if episode["ProviderIds"]:
                                                if user_name not in users_watched:
                                                    users_watched[user_name] = {}
                                                if library_title not in users_watched[user_name]:
                                                    users_watched[user_name][library_title] = {}
                                                if show["Name"] not in users_watched[user_name][library_title]:
                                                    users_watched[user_name][library_title][show["Name"]] = {}
                                                if season["Name"] not in users_watched[user_name][library_title][show["Name"]]:
                                                    users_watched[user_name][library_title][show["Name"]][season["Name"]] = []

                                                # Lowercase episode["ProviderIds"] keys
                                                episode["ProviderIds"] = {k.lower(): v for k, v in episode["ProviderIds"].items()}
                                                users_watched[user_name][library_title][show["Name"]][season["Name"]].append(episode["ProviderIds"])
                            
        return users_watched

    def update_watched(self, watched_list, user_mapping=None, library_mapping=None, dryrun=False):
        for user, libraries in watched_list.items():
            if user_mapping:
                user_other = None

                if user in user_mapping.keys():
                    user_other = user_mapping[user]
                elif user in user_mapping.values():
                    user_other = search_mapping(user_mapping, user)
                
                if user_other:
                    logger(f"Swapping user {user} with {user_other}", 1)
                    user = user_other

            user_id = None
            for key, value in self.users.items():
                if user.lower() == key.lower():
                    user_id = self.users[key]
                    break
            
            if not user_id:
                logger(f"{user} not found in Jellyfin", 2)
                break
            
            jellyfin_libraries = self.query(f"/Users/{user_id}/Views", "get")["Items"]
            
            for library, videos in libraries.items():
                if library_mapping:
                    library_other = None

                    if library in library_mapping.keys():
                        library_other = library_mapping[library]
                    elif library in library_mapping.values():
                        library_other = search_mapping(library_mapping, library)
                    
                    if library_other:
                        logger(f"Swapping library {library} with {library_other}", 1)
                        library = library_other

                if library not in [x["Name"] for x in jellyfin_libraries]:
                    logger(f"{library} not found in Jellyfin", 2)
                    continue

                library_id = None
                for jellyfin_library in jellyfin_libraries:
                    if jellyfin_library["Name"] == library:
                        library_id = jellyfin_library["Id"]
                        continue
                
                if library_id:
                    logger(f"Jellyfin: Updating watched for {user} in library {library}", 1)
                    library_search = self.query(f"/Users/{user_id}/Items?SortBy=SortName&SortOrder=Ascending&Recursive=true&ParentId={library_id}&limit=1", "get")
                    library_type = library_search["Items"][0]["Type"]

                    # Movies
                    if library_type == "Movie":
                        jellyfin_search = self.query(f"/Users/{user_id}/Items?SortBy=SortName&SortOrder=Ascending&Recursive=true&ParentId={library_id}&isPlayed=false&Fields=ItemCounts,ProviderIds", "get")
                        for jellyfin_video in jellyfin_search["Items"]:
                            if str_to_bool(jellyfin_video["UserData"]["Played"]) == False:
                                jellyfin_video_id = jellyfin_video["Id"]
                                for video in videos:
                                    for key, value in jellyfin_video["ProviderIds"].items():
                                        if key.lower() in video.keys() and value.lower() == video[key.lower()].lower():
                                            msg = f"{jellyfin_video['Name']} as watched for {user} in {library} for Jellyfin"
                                            if not dryrun:
                                                logger(f"Marking {msg}", 0)
                                                self.query(f"/Users/{user_id}/PlayedItems/{jellyfin_video_id}", "post")
                                            else:
                                                logger(f"Dryrun {msg}", 0)
                                            break
                    
                    # TV Shows
                    if library_type == "Episode":
                        jellyfin_search = self.query(f"/Users/{user_id}/Items?SortBy=SortName&SortOrder=Ascending&Recursive=true&ParentId={library_id}&isPlayed=false", "get")
                        jellyfin_shows = [x for x in jellyfin_search["Items"] if x["Type"] == "Series"]

                        for jellyfin_show in jellyfin_shows:
                            if jellyfin_show["Name"] in videos.keys():
                                jellyfin_show_id = jellyfin_show["Id"]
                                jellyfin_episodes = self.query(f"/Shows/{jellyfin_show_id}/Episodes?userId={user_id}&Fields=ItemCounts,ProviderIds", "get")
                                for jellyfin_episode in jellyfin_episodes["Items"]:
                                    if str_to_bool(jellyfin_episode["UserData"]["Played"]) == False:
                                        jellyfin_episode_id = jellyfin_episode["Id"]
                                        for show in videos:
                                            for season in videos[show]:
                                                for episode in videos[show][season]:
                                                    for key, value in jellyfin_episode["ProviderIds"].items():
                                                        if key.lower() in episode.keys() and value.lower() == episode[key.lower()].lower():
                                                            msg = f"{jellyfin_episode['SeriesName']} {jellyfin_episode['SeasonName']} {jellyfin_episode['Name']} as watched for {user} in {library} for Jellyfin"
                                                            if not dryrun:
                                                                logger(f"Marked {msg}", 0)
                                                                self.query(f"/Users/{user_id}/PlayedItems/{jellyfin_episode_id}", "post")
                                                            else:
                                                                logger(f"Dryrun {msg}", 0)
                                                            break
