import re, requests, os, traceback
from typing import Dict, Union, FrozenSet
import operator
from itertools import groupby as itertools_groupby

from urllib3.poolmanager import PoolManager
from math import floor

from requests.adapters import HTTPAdapter as RequestsHTTPAdapter

from plexapi.video import Episode, Movie
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount

from src.functions import (
    logger,
    search_mapping,
    future_thread_executor,
    contains_nested,
    log_marked,
)
from src.library import (
    check_skip_logic,
    generate_library_guids_dict,
)


# Bypass hostname validation for ssl. Taken from https://github.com/pkkid/python-plexapi/issues/143#issuecomment-775485186
class HostNameIgnoringAdapter(RequestsHTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=..., **pool_kwargs):
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            assert_hostname=False,
            **pool_kwargs,
        )


def extract_guids_from_item(item: Union[Movie, Episode]) -> Dict[str, str]:
    guids: Dict[str, str] = dict(
        guid.id.split('://')
        for guid
        in item.guids
        if guid.id is not None and len(guid.id.strip()) > 0
    )

    if len(guids) == 0:
        logger(
            f"Plex: Failed to get any guids for {item.title}, Using location only",
            1,
        )

    return guids


def get_guids(item: Union[Movie, Episode], completed=True):
    return {
        'title': item.title,
        'locations': tuple([location.split("/")[-1] for location in item.locations]),
        'status': {
            "completed": completed,
            "time": item.viewOffset,
        }
    } | extract_guids_from_item(item)  # Merge the metadata and guid dictionaries


def get_user_library_watched_show(show):
    try:
        show_guids: FrozenSet = frozenset(
            ({
                'title': show.title,
                'locations': tuple(
                    [location.split("/")[-1] for location in show.locations])
            } | extract_guids_from_item(show)).items()  # Merge the metadata and guid dictionaries
        )

        watched_episodes = show.watched()
        episode_guids = {
            # Offset group data because the first value will be the key
            season: [episode[1] for episode in episodes]
            for season, episodes
            # Group episodes by first element of tuple (episode.parentIndex)
            in itertools_groupby(
                [
                    (
                        episode.parentIndex,
                        get_guids(episode, completed=episode in watched_episodes)
                    )
                    for episode
                    in show.episodes()
                    # Only include watched/partially-watched episodes
                    if episode in watched_episodes or episode.viewOffset > 0
                ],
                operator.itemgetter(0)
            )
        }

        return show_guids, episode_guids
    except Exception:
        return {}, {}


def get_user_library_watched(user, user_plex, library):
    user_name: str = user.title.lower()
    try:
        logger(
            f"Plex: Generating watched for {user_name} in library {library.title}",
            0,
        )

        library_videos = user_plex.library.section(library.title)

        if library.type == "movie":
            watched = []

            args = [
                       [get_guids, video, True]
                       for video
                       # Get all watched movies
                       in library_videos.search(unwatched=False)
                   ] + [
                       [get_guids, video, False]
                       for video
                       # Get all partially watched movies
                       in library_videos.search(inProgress=True)
                       # Ignore all partially watched movies watched under 1 minute
                       if video.viewOffset < 60000
                   ]

            for guid in future_thread_executor(
                args, threads=min(os.cpu_count(), 4)
            ):
                logger(f"Plex: Adding {guid['title']} to {user_name} watched list", 3)
                watched.append(guid)
        elif library.type == "show":
            watched = {}

            # Get all watched shows and partially watched shows
            args = [
                (get_user_library_watched_show, show)
                for show
                in library_videos.search(unwatched=False) + library_videos.search(inProgress=True)
            ]

            for show_guids, episode_guids in future_thread_executor(args, threads=4):
                if show_guids and episode_guids:
                    watched[show_guids] = episode_guids
                    logger(
                        f"Plex: Added {episode_guids} to {user_name} {show_guids} watched list",
                        3,
                    )
        else:
            watched = None

        logger(f"Plex: Got watched for {user_name} in library {library.title}", 1)
        logger(f"Plex: {watched}", 3)

        return {
            user_name: {
                library.title: watched
            } if watched is not None else {}
        }
    except Exception as e:
        logger(
            f"Plex: Failed to get watched for {user_name} in library {library.title}, Error: {e}",
            2,
        )
        return {}


def find_video(plex_search, video_ids, videos=None):
    try:
        for location in plex_search.locations:
            if (
                contains_nested(location.split("/")[-1], video_ids["locations"])
                is not None
            ):
                episode_videos = []
                if videos:
                    for show, seasons in videos.items():
                        show = {k: v for k, v in show}
                        if (
                            contains_nested(location.split("/")[-1], show["locations"])
                            is not None
                        ):
                            for season in seasons.values():
                                for episode in season:
                                    episode_videos.append(episode)

                return True, episode_videos

        for guid in plex_search.guids:
            guid_source = re.search(r"(.*)://", guid.id).group(1).lower()
            guid_id = re.search(r"://(.*)", guid.id).group(1)

            # If show provider source and show provider id are in videos_shows_ids exactly, then the show is in the list
            if guid_source in video_ids.keys():
                if guid_id in video_ids[guid_source]:
                    episode_videos = []
                    if videos:
                        for show, seasons in videos.items():
                            show = {k: v for k, v in show}
                            if guid_source in show["ids"].keys():
                                if guid_id in show["ids"][guid_source]:
                                    for season in seasons:
                                        for episode in season:
                                            episode_videos.append(episode)

                    return True, episode_videos

        return False, []
    except Exception:
        return False, []


def get_video_status(plex_search, video_ids, videos):
    try:
        for location in plex_search.locations:
            if (
                contains_nested(location.split("/")[-1], video_ids["locations"])
                is not None
            ):
                for video in videos:
                    if (
                        contains_nested(location.split("/")[-1], video["locations"])
                        is not None
                    ):
                        return video["status"]

        for guid in plex_search.guids:
            guid_source = re.search(r"(.*)://", guid.id).group(1).lower()
            guid_id = re.search(r"://(.*)", guid.id).group(1)

            # If show provider source and show provider id are in videos_shows_ids exactly, then the show is in the list
            if guid_source in video_ids.keys():
                if guid_id in video_ids[guid_source]:
                    for video in videos:
                        if guid_source in video["ids"].keys():
                            if guid_id in video["ids"][guid_source]:
                                return video["status"]

        return None
    except Exception:
        return None


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
                video_status = get_video_status(
                    movies_search, videos_movies_ids, videos
                )
                if video_status:
                    if video_status["completed"]:
                        msg = f"Plex: {movies_search.title} as watched for {user.title} in {library}"
                        if not dryrun:
                            logger(msg, 5)
                            movies_search.markWatched()
                        else:
                            logger(msg, 6)

                        log_marked(user.title, library, movies_search.title, None, None)
                    elif video_status["time"] > 60_000:
                        msg = f"Plex: {movies_search.title} as partially watched for {floor(video_status['time'] / 60_000)} minutes for {user.title} in {library}"
                        if not dryrun:
                            logger(msg, 5)
                            movies_search.updateTimeline(video_status["time"])
                        else:
                            logger(msg, 6)

                        log_marked(
                            user.title,
                            library,
                            movies_search.title,
                            duration=video_status["time"],
                        )
                else:
                    logger(
                        f"Plex: Skipping movie {movies_search.title} as it is not in mark list for {user.title}",
                        1,
                    )

        if videos_shows_ids and videos_episodes_ids:
            for show_search in library_videos.search(unwatched=True):
                show_found, episode_videos = find_video(
                    show_search, videos_shows_ids, videos
                )
                if show_found:
                    for episode_search in show_search.episodes():
                        video_status = get_video_status(
                            episode_search, videos_episodes_ids, episode_videos
                        )
                        if video_status:
                            if video_status["completed"]:
                                msg = f"Plex: {show_search.title} {episode_search.title} as watched for {user.title} in {library}"
                                if not dryrun:
                                    logger(msg, 5)
                                    episode_search.markWatched()
                                else:
                                    logger(msg, 6)

                                log_marked(
                                    user.title,
                                    library,
                                    show_search.title,
                                    episode_search.title,
                                )
                            else:
                                msg = f"Plex: {show_search.title} {episode_search.title} as partially watched for {floor(video_status['time'] / 60_000)} minutes for {user.title} in {library}"
                                if not dryrun:
                                    logger(msg, 5)
                                    episode_search.updateTimeline(video_status["time"])
                                else:
                                    logger(msg, 6)

                                log_marked(
                                    user.title,
                                    library,
                                    show_search.title,
                                    episode_search.title,
                                    video_status["time"],
                                )
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

    def info(self) -> str:
        return f"{self.plex.friendlyName}: {self.plex.version}"

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
                    token = user.get_token(self.plex.machineIdentifier)
                    if token:
                        user_plex = self.login(
                            self.plex._baseurl,
                            token,
                        )
                    else:
                        logger(
                            f"Plex: Failed to get token for {user.title}, skipping",
                            2,
                        )
                        users_watched[user.title] = {}
                        continue

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
                    username_title = (
                        value.username.lower()
                        if value.username
                        else value.title.lower()
                    )

                    if user.lower() == username_title:
                        user = self.users[index]
                        break
                    elif user_other and user_other.lower() == username_title:
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

                    token = user.get_token(self.plex.machineIdentifier)
                    if token:
                        user_plex = PlexServer(
                            self.plex._baseurl,
                            token,
                            session=self.session,
                        )
                    else:
                        logger(
                            f"Plex: Failed to get token for {user.title}, skipping",
                            2,
                        )
                        continue

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
