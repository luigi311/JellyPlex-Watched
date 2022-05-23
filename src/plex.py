import re, os
from dotenv import load_dotenv
from time import sleep
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
            # if self.username and self.password are not None or empty strings
            if self.username and self.password:
                # Login via plex account
                account = MyPlexAccount(self.username, self.password)
                plex = account.resource(self.baseurl).connect()
            elif self.token:
                # Login via token
                plex = PlexServer(self.baseurl, self.token)
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

    def get_plex_watched(self, users, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type):
        # Get all libraries
        libraries = self.plex.library.sections()
        users_watched = {}

        # for not in blacklist
        for library in libraries:
            library_title = library.title
            # if whitelist is not empty and library is not in whitelist
            if (len(whitelist_library) > 0 and library_title.lower() not in [x.lower() for x in whitelist_library]) or (len(whitelist_library_type) > 0 and library_title.type() not in [x.lower() for x in whitelist_library_type]):
                pass
            else:
                if library_title.lower() not in [x.lower() for x in blacklist_library] and library.type not in [x.lower() for x in blacklist_library_type]:
                    for user in users:
                        print(f"Plex: Generating watched for {user.title} in library {library_title}")
                        user_name = user.title.lower()
                        watched = self.get_plex_user_watched(user, library)
                        if watched:
                            if user_name not in users_watched:
                                users_watched[user_name] = {}
                            if library_title not in users_watched[user_name]:
                                users_watched[user_name][library_title] = []
                            users_watched[user_name][library_title] = watched
                        
        return users_watched
    
    def update_watched(self, watched_list):
        for user, libraries in watched_list.items():
            for index, value in enumerate(self.users):
                if user.lower() == value.title.lower():
                    user = self.users[index]
                    break

            if self.admin_user == user:
                user_plex = self.plex
            else:
                user_plex = PlexServer(self.baseurl, user.get_token(self.plex.machineIdentifier))

            print(f"Updating watched for {user.title}")
            for library, videos in libraries.items():
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
                                            movies_search.markWatched()
                                            print(f"Marked {movies_search.title} watched")
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
                                                                episode_search.markWatched()
                                                                print(f"Marked {show_search.title} {season_search.title} {episode_search.title} as watched for {user.title} in Plex")
                                                                break
