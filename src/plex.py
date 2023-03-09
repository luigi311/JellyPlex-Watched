import re, requests, os, traceback
from urllib3.poolmanager import PoolManager

from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount

from src.functions import (
    logger,
    search_mapping,
    future_thread_executor,
)
from src.library import (
    check_skip_logic,
    generate_library_guids_dict,
)


# Bypass hostname validation for ssl. Taken from https://github.com/pkkid/python-plexapi/issues/143#issuecomment-775485186
class HostNameIgnoringAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=..., **pool_kwargs):
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            assert_hostname=False,
            **pool_kwargs,
        )


def get_user_library_watched_show(show):
    try:
        show_guids = {}
        for show_guid in show.guids:
            # Extract source and id from guid.id
            m = re.match(r"(.*)://(.*)", show_guid.id)
            show_guid_source, show_guid_id = m.group(1).lower(), m.group(2)
            show_guids[show_guid_source] = show_guid_id

        show_guids["title"] = show.title
        show_guids["locations"] = tuple([x.split("/")[-1] for x in show.locations])
        show_guids = frozenset(show_guids.items())

        # Get all watched episodes for show
        episode_guids = {}
        watched_episodes = show.watched()
        for episode in watched_episodes:
            episode_guids_temp = {}
            try:
                if len(episode.guids) > 0:
                    for guid in episode.guids:
                        # Extract after :// from guid.id
                        m = re.match(r"(.*)://(.*)", guid.id)
                        guid_source, guid_id = m.group(1).lower(), m.group(2)
                        episode_guids_temp[guid_source] = guid_id
            except Exception:
                logger(
                    f"Plex: Failed to get guids for {episode.title} in {show.title}, Using location only",
                    1,
                )

            episode_guids_temp["locations"] = tuple(
                [x.split("/")[-1] for x in episode.locations]
            )

            if episode.parentTitle not in episode_guids:
                episode_guids[episode.parentTitle] = []

            episode_guids[episode.parentTitle].append(episode_guids_temp)

        return show_guids, episode_guids

    except Exception:
        return {}, {}


def get_user_library_watched(user, user_plex, library):
    try:
        user_name = user.title.lower()
        user_watched = {}
        user_watched[user_name] = {}

        logger(
            f"Plex: Generating watched for {user_name} in library {library.title}",
            0,
        )

        library_videos = user_plex.library.section(library.title)

        if library.type == "movie":
            user_watched[user_name][library.title] = []

            for video in library_videos.search(unwatched=False):
                logger(f"Plex: Adding {video.title} to {user_name} watched list", 3)
                logger(f"Plex: {video.title} {video.guids} {video.locations}", 3)

                movie_guids = {}
                for guid in video.guids:
                    # Extract source and id from guid.id
                    m = re.match(r"(.*)://(.*)", guid.id)
                    guid_source, guid_id = m.group(1).lower(), m.group(2)
                    movie_guids[guid_source] = guid_id

                movie_guids["title"] = video.title
                movie_guids["locations"] = tuple(
                    [x.split("/")[-1] for x in video.locations]
                )

                user_watched[user_name][library.title].append(movie_guids)
                logger(f"Plex: Added {movie_guids} to {user_name} watched list", 3)

        elif library.type == "show":
            user_watched[user_name][library.title] = {}
            shows = library_videos.search(unwatched=False)

            # Parallelize show processing
            args = []
            for show in shows:
                args.append([get_user_library_watched_show, show])

            for show_guids, episode_guids in future_thread_executor(
                args, workers=min(os.cpu_count(), 4)
            ):
                if show_guids and episode_guids:
                    # append show, season, episode
                    if show_guids not in user_watched[user_name][library.title]:
                        user_watched[user_name][library.title][show_guids] = {}

                    user_watched[user_name][library.title][show_guids] = episode_guids
                    logger(
                        f"Plex: Added {episode_guids} to {user_name} {show_guids} watched list",
                        3,
                    )

        logger(f"Plex: Got watched for {user_name} in library {library.title}", 1)
        if library.title in user_watched[user_name]:
            logger(f"Plex: {user_watched[user_name][library.title]}", 3)

        return user_watched
    except Exception as e:
        logger(
            f"Plex: Failed to get watched for {user_name} in library {library.title}, Error: {e}",
            2,
        )
        return {}


def find_video(plex_search, video_ids):
    try:
        for location in plex_search.locations:
            if location.split("/")[-1] in video_ids["locations"]:
                return True

        for guid in plex_search.guids:
            guid_source = re.search(r"(.*)://", guid.id).group(1).lower()
            guid_id = re.search(r"://(.*)", guid.id).group(1)

            # If show provider source and show provider id are in videos_shows_ids exactly, then the show is in the list
            if guid_source in video_ids.keys():
                if guid_id in video_ids[guid_source]:
                    return True

        return False
    except Exception:
        return False


def update_user_watched(user, user_plex, library, videos, dryrun):
    try:
        logger(f"Plex: Updating watched for {user.title} in library {library}", 1)
        (
            videos_shows_ids,
            videos_episodes_ids,
            videos_movies_ids,
        ) = generate_library_guids_dict(videos)
        logger(
            f"Plex: mark list\nShows: {videos_shows_ids}\nEpisodes: {videos_episodes_ids}\nMovies: {videos_movies_ids}",
            1,
        )

        library_videos = user_plex.library.section(library)
        if videos_movies_ids:
            for movies_search in library_videos.search(unwatched=True):
                if find_video(movies_search, videos_movies_ids):
                    msg = f"{movies_search.title} as watched for {user.title} in {library} for Plex"
                    if not dryrun:
                        logger(f"Marked {msg}", 0)
                        movies_search.markWatched()
                    else:
                        logger(f"Dryrun {msg}", 0)
                else:
                    logger(
                        f"Plex: Skipping movie {movies_search.title} as it is not in mark list for {user.title}",
                        1,
                    )

        if videos_shows_ids and videos_episodes_ids:
            for show_search in library_videos.search(unwatched=True):
                if find_video(show_search, videos_shows_ids):
                    for episode_search in show_search.episodes():
                        if find_video(episode_search, videos_episodes_ids):
                            msg = f"{show_search.title} {episode_search.title} as watched for {user.title} in {library} for Plex"
                            if not dryrun:
                                logger(f"Marked {msg}", 0)
                                episode_search.markWatched()
                            else:
                                logger(f"Dryrun {msg}", 0)
                        else:
                            logger(
                                f"Plex: Skipping episode {episode_search.title} as it is not in mark list for {user.title}",
                                3,
                            )
                else:
                    logger(
                        f"Plex: Skipping show {show_search.title} as it is not in mark list for {user.title}",
                        3,
                    )

        if not videos_movies_ids and not videos_shows_ids and not videos_episodes_ids:
            logger(
                f"Jellyfin: No videos to mark as watched for {user.title} in library {library}",
                1,
            )

    except Exception as e:
        logger(
            f"Plex: Failed to update watched for {user.title} in library {library}, Error: {e}",
            2,
        )
        logger(traceback.format_exc(), 2)


# class plex accept base url and token and username and password but default with none
class Plex:
    def __init__(
        self,
        baseurl=None,
        token=None,
        username=None,
        password=None,
        servername=None,
        ssl_bypass=False,
        session=None,
    ):
        self.baseurl = baseurl
        self.token = token
        self.username = username
        self.password = password
        self.servername = servername
        self.ssl_bypass = ssl_bypass
        if ssl_bypass:
            # Session for ssl bypass
            session = requests.Session()
            # By pass ssl hostname check https://github.com/pkkid/python-plexapi/issues/143#issuecomment-775485186
            session.mount("https://", HostNameIgnoringAdapter())
        self.session = session
        self.plex = self.login(self.baseurl, self.token)
        self.admin_user = self.plex.myPlexAccount()
        self.users = self.get_users()

    def login(self, baseurl, token):
        try:
            if baseurl and token:
                plex = PlexServer(baseurl, token, session=self.session)
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
            raise Exception(e)

    def get_users(self):
        try:
            users = self.plex.myPlexAccount().users()

            # append self to users
            users.append(self.plex.myPlexAccount())

            return users
        except Exception as e:
            logger(f"Plex: Failed to get users, Error: {e}", 2)
            raise Exception(e)

    def get_watched(
        self,
        users,
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        library_mapping,
    ):
        try:
            # Get all libraries
            users_watched = {}
            args = []

            for user in users:
                if self.admin_user == user:
                    user_plex = self.plex
                else:
                    user_plex = self.login(
                        self.plex._baseurl,
                        user.get_token(self.plex.machineIdentifier),
                    )

                libraries = user_plex.library.sections()

                for library in libraries:
                    library_title = library.title
                    library_type = library.type

                    skip_reason = check_skip_logic(
                        library_title,
                        library_type,
                        blacklist_library,
                        whitelist_library,
                        blacklist_library_type,
                        whitelist_library_type,
                        library_mapping,
                    )

                    if skip_reason:
                        logger(
                            f"Plex: Skipping library {library_title}: {skip_reason}", 1
                        )
                        continue

                    args.append([get_user_library_watched, user, user_plex, library])

            for user_watched in future_thread_executor(args):
                for user, user_watched_temp in user_watched.items():
                    if user not in users_watched:
                        users_watched[user] = {}
                    users_watched[user].update(user_watched_temp)

            return users_watched
        except Exception as e:
            logger(f"Plex: Failed to get watched, Error: {e}", 2)
            raise Exception(e)

    def update_watched(
        self, watched_list, user_mapping=None, library_mapping=None, dryrun=False
    ):
        try:
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
                    if isinstance(user, str):
                        logger(
                            f"Plex: {user} is not a plex object, attempting to get object for user",
                            4,
                        )
                        user = self.plex.myPlexAccount().user(user)

                    user_plex = PlexServer(
                        self.plex._baseurl,
                        user.get_token(self.plex.machineIdentifier),
                        session=self.session,
                    )

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
                        if library_other:
                            if library_other.lower() in [
                                x.title.lower() for x in library_list
                            ]:
                                logger(
                                    f"Plex: Library {library} not found, but {library_other} found, using {library_other}",
                                    1,
                                )
                                library = library_other
                            else:
                                logger(
                                    f"Plex: Library {library} or {library_other} not found in library list",
                                    1,
                                )
                                continue
                        else:
                            logger(
                                f"Plex: Library {library} not found in library list",
                                1,
                            )
                            continue

                    args.append(
                        [
                            update_user_watched,
                            user,
                            user_plex,
                            library,
                            videos,
                            dryrun,
                        ]
                    )

            future_thread_executor(args)
        except Exception as e:
            logger(f"Plex: Failed to update watched, Error: {e}", 2)
            raise Exception(e)
