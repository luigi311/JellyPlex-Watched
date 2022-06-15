import re

from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount

from src.functions import logger, search_mapping, check_skip_logic, generate_library_guids_dict, future_thread_executor


# class plex accept base url and token and username and password but default with none
class Plex:
    def __init__(self, baseurl=None, token=None, username=None, password=None, servername=None):
        self.baseurl = baseurl
        self.token = token
        self.username = username
        self.password = password
        self.servername = servername
        self.plex = self.login()
        self.admin_user = self.plex.myPlexAccount()
        self.users = self.get_users()

    def login(self):
        try:
            if self.baseurl and self.token:
                    # Login via token
                    plex = PlexServer(self.baseurl, self.token)
            elif self.username and self.password and self.servername:
                # Login via plex account
                account = MyPlexAccount(self.username, self.password)
                plex = account.resource(self.servername).connect()
            else:
                raise Exception("No complete plex credentials provided")

            return plex
        except Exception as e:
            if self.username or self.password:
                msg = f"Failed to login via plex account {self.username}"
                logger(f"Plex: Failed to login, {msg}, Error: {e}", 2)
            else:
                logger(f"Plex: Failed to login, Error: {e}", 2)
            return None


    def get_users(self):
        users = self.plex.myPlexAccount().users()

        # append self to users
        users.append(self.plex.myPlexAccount())

        return users

    def get_user_watched(self, user, user_plex, library):
        user_watched = {}
        user_watched[user.title] = {}

        logger(f"Plex: Generating watched for {user.title} in library {library.title}", 0)

        if library.type == "movie":
            user_watched[user.title][library.title] = []

            library_videos = user_plex.library.section(library.title)
            for video in library_videos.search(unmatched=False, unwatched=False):
                guids = {}
                for guid in video.guids:
                    guid_source = re.search(r'(.*)://', guid.id).group(1).lower()
                    guid_id = re.search(r'://(.*)', guid.id).group(1)
                    guids[guid_source] = guid_id
                user_watched[user.title][library.title].append(guids)

        elif library.type == "show":
            user_watched[user.title][library.title] = {}

            library_videos = user_plex.library.section(library.title)
            for show in library_videos.search(unmatched=False, unwatched=False):
                show_guids = {}
                for show_guid in show.guids:
                    show_guids["title"] = show.title
                    # Extract after :// from guid.id
                    show_guid_source = re.search(r'(.*)://', show_guid.id).group(1).lower()
                    show_guid_id = re.search(r'://(.*)', show_guid.id).group(1)
                    show_guids[show_guid_source] = show_guid_id
                show_guids = frozenset(show_guids.items())

                for season in show.seasons():
                    episode_guids = []
                    for episode in season.episodes():
                        if episode.viewCount > 0:
                            episode_guids_temp = {}
                            for guid in episode.guids:
                                # Extract after :// from guid.id
                                guid_source = re.search(r'(.*)://', guid.id).group(1).lower()
                                guid_id = re.search(r'://(.*)', guid.id).group(1)
                                episode_guids_temp[guid_source] = guid_id

                            episode_guids.append(episode_guids_temp)

                    if episode_guids:
                        # append show, season, episode
                        if show_guids not in user_watched[user.title][library.title]:
                            user_watched[user.title][library.title][show_guids] = {}
                        if season.title not in user_watched[user.title][library.title][show_guids]:
                            user_watched[user.title][library.title][show_guids][season.title] = {}
                        user_watched[user.title][library.title][show_guids][season.title] = episode_guids


        return user_watched

    def get_watched(self, users, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, library_mapping):
        # Get all libraries
        users_watched = {}
        args = []

        for user in users:
            if self.admin_user == user:
                user_plex = self.plex
            else:
                user_plex = PlexServer(self.plex._baseurl, user.get_token(self.plex.machineIdentifier))

            libraries = user_plex.library.sections()

            for library in libraries:
                library_title = library.title
                library_type = library.type

                skip_reason = check_skip_logic(library_title, library_type, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, library_mapping)

                if skip_reason:
                    logger(f"Plex: Skipping library {library_title} {skip_reason}", 1)
                    continue

                args.append([self.get_user_watched, user, user_plex, library])

        for user_watched in future_thread_executor(args):
            for user, user_watched_temp in user_watched.items():
                if user not in users_watched:
                    users_watched[user] = {}
                users_watched[user].update(user_watched_temp)

        return users_watched

    def update_user_watched (self, user, user_plex, library, videos, dryrun):
        logger(f"Plex: Updating watched for {user.title} in library {library}", 1)
        library_videos = user_plex.library.section(library)

        if library_videos.type == "movie":
            _, _, videos_movies_ids = generate_library_guids_dict(videos, 2)
            for movies_search in library_videos.search(unmatched=False, unwatched=True):
                for movie_guid in movies_search.guids:
                    movie_guid_source = re.search(r'(.*)://', movie_guid.id).group(1).lower()
                    movie_guid_id = re.search(r'://(.*)', movie_guid.id).group(1)

                    # If movie provider source and movie provider id are in videos_movie_ids exactly, then the movie is in the list
                    if movie_guid_source in videos_movies_ids.keys():
                        if movie_guid_id in videos_movies_ids[movie_guid_source]:
                            if movies_search.viewCount == 0:
                                msg = f"{movies_search.title} as watched for {user.title} in {library} for Plex"
                                if not dryrun:
                                    logger(f"Marked {msg}", 0)
                                    movies_search.markWatched()
                                else:
                                    logger(f"Dryrun {msg}", 0)
                            break


        elif library_videos.type == "show":
            videos_shows_ids, videos_episode_ids, _ = generate_library_guids_dict(videos, 3)

            for show_search in library_videos.search(unmatched=False, unwatched=True):
                show_found = False
                for show_guid in show_search.guids:
                    show_guid_source = re.search(r'(.*)://', show_guid.id).group(1).lower()
                    show_guid_id = re.search(r'://(.*)', show_guid.id).group(1)

                    # If show provider source and show provider id are in videos_shows_ids exactly, then the show is in the list
                    if show_guid_source in videos_shows_ids.keys():
                        if show_guid_id in videos_shows_ids[show_guid_source]:
                            show_found = True
                            for episode_search in show_search.episodes():
                                for episode_guid in episode_search.guids:
                                    episode_guid_source = re.search(r'(.*)://', episode_guid.id).group(1).lower()
                                    episode_guid_id = re.search(r'://(.*)', episode_guid.id).group(1)

                                    # If episode provider source and episode provider id are in videos_episode_ids exactly, then the episode is in the list
                                    if episode_guid_source in videos_episode_ids.keys():
                                        if episode_guid_id in videos_episode_ids[episode_guid_source]:
                                            if episode_search.viewCount == 0:
                                                msg = f"{show_search.title} {episode_search.title} as watched for {user.title} in {library} for Plex"
                                                if not dryrun:
                                                    logger(f"Marked {msg}", 0)
                                                    episode_search.markWatched()
                                                else:
                                                    logger(f"Dryrun {msg}", 0)
                                            break

                    if show_found:
                        break



    def update_watched(self, watched_list, user_mapping=None, library_mapping=None, dryrun=False):
        args = []

        for user, libraries in watched_list.items():
            user_other = None
            # If type of user is dict
            if user_mapping:
                if user in user_mapping.keys():
                    user_other = user_mapping[user]
                elif user in user_mapping.values():
                    user_other = search_mapping(user_mapping, user)

            for index, value in enumerate(self.users):
                if user.lower() == value.title.lower():
                    user = self.users[index]
                    break
                elif user_other and user_other.lower() == value.title.lower():
                    user = self.users[index]
                    break

            if self.admin_user == user:
                user_plex = self.plex
            else:
                user_plex = PlexServer(self.plex._baseurl, user.get_token(self.plex.machineIdentifier))

            for library, videos in libraries.items():
                library_other = None
                if library_mapping:
                    if library in library_mapping.keys():
                        library_other = library_mapping[library]
                    elif library in library_mapping.values():
                        library_other = search_mapping(library_mapping, library)

                # if library in plex library list
                library_list = user_plex.library.sections()
                if library.lower() not in [x.title.lower() for x in library_list]:
                    if library_other and library_other.lower() in [x.title.lower() for x in library_list]:
                        logger(f"Plex: Library {library} not found, but {library_other} found, using {library_other}", 1)
                        library = library_other
                    else:
                        logger(f"Library {library} {library_other} not found in Plex library list", 2)
                        continue


                args.append([self.update_user_watched, user, user_plex, library, videos, dryrun])

        future_thread_executor(args)
