import re, os
from dotenv import load_dotenv

from src.functions import logger, search_mapping
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount

load_dotenv(override=True)

plex_baseurl = os.getenv("PLEX_BASEURL")
plex_token = os.getenv("PLEX_TOKEN")
username = os.getenv("PLEX_USERNAME")
password = os.getenv("PLEX_PASSWORD")

# class plex accept base url and token and username and password but default with none
class Plex:
    def __init__(self):
        self.baseurl = plex_baseurl
        self.token = plex_token
        self.username = username
        self.password = password
        self.plex = self.plex_login()
        self.admin_user = self.plex.myPlexAccount()
        self.users = self.get_plex_users()

    def plex_login(self):
        if self.baseurl:
            if self.token:
                # Login via token
                plex = PlexServer(self.baseurl, self.token)
            elif self.username and self.password:
                # Login via plex account
                account = MyPlexAccount(self.username, self.password)
                plex = account.resource(self.baseurl).connect()
            else:
                raise Exception("No plex credentials provided")
        else:
            raise Exception("No plex baseurl provided")

        return plex

    def get_plex_users(self):
        users = self.plex.myPlexAccount().users()
        
        # append self to users
        users.append(self.plex.myPlexAccount())
        
        return users

    def get_plex_user_watched(self, user, library):
        if self.admin_user == user:
            user_plex = self.plex
        else:
            user_plex = PlexServer(self.baseurl, user.get_token(self.plex.machineIdentifier))
        
        watched = None
        
        if library.type == "movie":
            watched = []
            library_videos = user_plex.library.section(library.title)
            for video in library_videos.search(unmatched=False, unwatched=False):
                guids = {}
                for guid in video.guids:
                    guid_source = re.search(r'(.*)://', guid.id).group(1).lower()
                    guid_id = re.search(r'://(.*)', guid.id).group(1)
                    guids[guid_source] = guid_id
                watched.append(guids)

        elif library.type == "show":
            watched = {}
            library_videos = user_plex.library.section(library.title)
            for show in library_videos.search(unmatched=False, unwatched=False):
                for season in show.seasons():
                    guids = []
                    for episode in season.episodes():
                        if episode.viewCount > 0:     
                            guids_temp = {}                
                            for guid in episode.guids:
                                # Extract after :// from guid.id
                                guid_source = re.search(r'(.*)://', guid.id).group(1).lower()
                                guid_id = re.search(r'://(.*)', guid.id).group(1)
                                guids_temp[guid_source] = guid_id
                                
                            guids.append(guids_temp)        
                        
                    if guids:
                        # append show, season, episode
                        if show.title not in watched:
                            watched[show.title] = {}
                        if season.title not in watched[show.title]:
                            watched[show.title][season.title] = {}   
                        watched[show.title][season.title] = guids

        return watched

    def get_plex_watched(self, users, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, library_mapping):
        # Get all libraries
        libraries = self.plex.library.sections()
        users_watched = {}

        # for not in blacklist
        for library in libraries:
            library_title = library.title
            library_type = library.type

            if library_type.lower() in blacklist_library_type:
                logger(f"Plex: Library type {library_type} is blacklist_library_type", 1)
                continue

            if library_title.lower() in [x.lower() for x in blacklist_library]:
                logger(f"Plex: Library {library_title} is blacklist_library", 1)
                continue

            library_other = None
            if library_mapping:
                library_other = search_mapping(library_mapping, library_title)
            if library_other:
                library_other.lower()
                if library_other not in [x.lower() for x in blacklist_library]:
                    logger(f"Plex: Library {library_other} is blacklist_library", 1)
                    continue

            if len(whitelist_library_type) > 0:
                if library_type.lower() not in whitelist_library_type:
                    logger(f"Plex: Library type {library_type} is not whitelist_library_type", 1)
                    continue

            # if whitelist is not empty and library is not in whitelist
            if len(whitelist_library) > 0:
                if library_title.lower() not in [x.lower() for x in whitelist_library]:
                    logger(f"Plex: Library {library_title} is not whitelist_library", 1)
                    continue
                
                if library_other:
                    if library_other not in [x.lower() for x in whitelist_library]:
                        logger(f"Plex: Library {library_other} is not whitelist_library", 1)
                        continue
            
            for user in users:
                logger(f"Plex: Generating watched for {user.title} in library {library_title}", 0)
                user_name = user.title.lower()
                watched = self.get_plex_user_watched(user, library)
                if watched:
                    if user_name not in users_watched:
                        users_watched[user_name] = {}
                    if library_title not in users_watched[user_name]:
                        users_watched[user_name][library_title] = []
                    users_watched[user_name][library_title] = watched
                        
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

            for index, value in enumerate(self.users):
                if user.lower() == value.title.lower():
                    user = self.users[index]
                    break

            if self.admin_user == user:
                user_plex = self.plex
            else:
                user_plex = PlexServer(self.baseurl, user.get_token(self.plex.machineIdentifier))

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

                # if library in plex library list
                library_list = user_plex.library.sections()
                if library.lower() not in [x.title.lower() for x in library_list]:
                    logger(f"Library {library} not found in Plex library list", 2)
                    continue

                logger(f"Plex: Updating watched for {user.title} in library {library}", 1)
                library_videos = user_plex.library.section(library)

                if library_videos.type == "movie":
                    for movies_search in library_videos.search(unmatched=False, unwatched=True):
                        for guid in movies_search.guids:
                            guid_source = re.search(r'(.*)://', guid.id).group(1).lower()
                            guid_id = re.search(r'://(.*)', guid.id).group(1)
                            for video in videos:
                                for video_keys, video_id in video.items():
                                    if video_keys == guid_source and video_id == guid_id:
                                        if movies_search.viewCount == 0:
                                            msg = f"{movies_search.title} as watched for {user.title} in {library} for Plex"
                                            if not dryrun:
                                                logger(f"Marked {msg}", 0)
                                                movies_search.markWatched()
                                            else:
                                                logger(f"Dryrun {msg}", 0)
                                            break
                
                elif library_videos.type == "show":
                    for show_search in library_videos.search(unmatched=False, unwatched=True):
                        if show_search.title in videos:
                            for season_search in show_search.seasons():
                                for episode_search in season_search.episodes():
                                    for guid in episode_search.guids:
                                        guid_source = re.search(r'(.*)://', guid.id).group(1).lower()
                                        guid_id = re.search(r'://(.*)', guid.id).group(1)
                                        for show, seasons in videos.items():
                                            for season, episodes in seasons.items():
                                                for episode in episodes:
                                                    for episode_keys, episode_id in episode.items():
                                                        if episode_keys == guid_source and episode_id == guid_id:
                                                            if episode_search.viewCount == 0:
                                                                msg = f"{show_search.title} {season_search.title} {episode_search.title} as watched for {user.title} in {library} for Plex"
                                                                if not dryrun:
                                                                    logger(f"Marked {msg}", 0)
                                                                    episode_search.markWatched()
                                                                else:
                                                                    logger(f"Dryrun {msg}", 0)
                                                                break
