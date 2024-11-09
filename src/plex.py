import os, requests, traceback
from dotenv import load_dotenv
from typing import Dict, Union, FrozenSet

from urllib3.poolmanager import PoolManager
from math import floor

from requests.adapters import HTTPAdapter as RequestsHTTPAdapter

from plexapi.video import Show, Episode, Movie
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount

from src.functions import (
    logger,
    search_mapping,
    future_thread_executor,
    contains_nested,
    log_marked,
    str_to_bool,
)
from src.library import generate_library_guids_dict


load_dotenv(override=True)

generate_guids = str_to_bool(os.getenv("GENERATE_GUIDS", "True"))
generate_locations = str_to_bool(os.getenv("GENERATE_LOCATIONS", "True"))


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


def extract_guids_from_item(item: Union[Movie, Show, Episode]) -> Dict[str, str]:
    # If GENERATE_GUIDS is set to False, then return an empty dict
    if not generate_guids:
        return {}

    guids: Dict[str, str] = dict(
        guid.id.split("://")
        for guid in item.guids
        if guid.id is not None and len(guid.id.strip()) > 0
    )

    if len(guids) == 0:
        logger(
            f"Plex: Failed to get any guids for {item.title}",
            1,
        )

    return guids


def get_guids(item: Union[Movie, Episode], completed=True):
    if not item.locations:
        logger(
            f"Plex: {item.title} has no locations",
            1,
        )

    if not item.guids:
        logger(
            f"Plex: {item.title} has no guids",
            1,
        )

    return {
        "title": item.title,
        "locations": (
            tuple([location.split("/")[-1] for location in item.locations])
            if generate_locations
            else tuple()
        ),
        "status": {
            "completed": completed,
            "time": item.viewOffset,
        },
    } | extract_guids_from_item(
        item
    )  # Merge the metadata and guid dictionaries


def get_user_library_watched_show(show, process_episodes, threads=None):
    try:
        show_guids: FrozenSet = frozenset(
            (
                {
                    "title": show.title,
                    "locations": (
                        tuple([location.split("/")[-1] for location in show.locations])
                        if generate_locations
                        else tuple()
                    ),
                }
                | extract_guids_from_item(show)
            ).items()  # Merge the metadata and guid dictionaries
        )

        episode_guids_args = []

        for episode in process_episodes:
            episode_guids_args.append([get_guids, episode, episode.isWatched])

        episode_guids_results = future_thread_executor(
            episode_guids_args, threads=threads
        )

        episode_guids = []
        for index, episode in enumerate(process_episodes):
            episode_guids.append(episode_guids_results[index])

        return show_guids, episode_guids
    except Exception:
        return {}, {}


def get_user_library_watched(user, user_plex, library):
    user_name: str = user.username.lower() if user.username else user.title.lower()
    try:
        logger(
            f"Plex: Generating watched for {user_name} in library {library.title}",
            0,
        )

        library_videos = user_plex.library.section(library.title)

        if library.type == "movie":
            watched = []

            args = [
                [get_guids, video, video.isWatched]
                for video in library_videos.search(unwatched=False)
                + library_videos.search(inProgress=True)
                if video.isWatched or video.viewOffset >= 60000
            ]

            for guid in future_thread_executor(args, threads=len(args)):
                logger(f"Plex: Adding {guid['title']} to {user_name} watched list", 3)
                watched.append(guid)
        elif library.type == "show":
            watched = {}

            # Get all watched shows and partially watched shows
            parallel_show_task = []
            parallel_episodes_task = []

            for show in library_videos.search(unwatched=False) + library_videos.search(
                inProgress=True
            ):
                process_episodes = []
                for episode in show.episodes():
                    if episode.isWatched or episode.viewOffset >= 60000:
                        process_episodes.append(episode)

                # Shows with more than 24 episodes has its episodes processed in parallel
                # Shows with less than 24 episodes has its episodes processed in serial but the shows are processed in parallel
                if len(process_episodes) >= 24:
                    parallel_episodes_task.append(
                        [
                            get_user_library_watched_show,
                            show,
                            process_episodes,
                            len(process_episodes),
                        ]
                    )
                else:
                    parallel_show_task.append(
                        [get_user_library_watched_show, show, process_episodes, 1]
                    )

            for show_guids, episode_guids in future_thread_executor(
                parallel_show_task, threads=len(parallel_show_task)
            ) + future_thread_executor(parallel_episodes_task, threads=1):
                if show_guids and episode_guids:
                    watched[show_guids] = episode_guids
                    logger(
                        f"Plex: Added {episode_guids} to {user_name} watched list",
                        3,
                    )

        else:
            watched = None

        logger(f"Plex: Got watched for {user_name} in library {library.title}", 1)
        logger(f"Plex: {watched}", 3)

        return {user_name: {library.title: watched} if watched is not None else {}}
    except Exception as e:
        logger(
            f"Plex: Failed to get watched for {user_name} in library {library.title}, Error: {e}",
            2,
        )
        return {}


def find_video(plex_search, video_ids, videos=None):
    try:
        if not generate_guids and not generate_locations:
            return None

        if generate_locations:
            for location in plex_search.locations:
                if (
                    contains_nested(location.split("/")[-1], video_ids["locations"])
                    is not None
                ):
                    episode_videos = []
                    if videos:
                        for show, episodes in videos.items():
                            show = {k: v for k, v in show}
                            if (
                                contains_nested(
                                    location.split("/")[-1], show["locations"]
                                )
                                is not None
                            ):
                                for episode in episodes:
                                    episode_videos.append(episode)

                    return episode_videos

        if generate_guids:
            for guid in plex_search.guids:
                guid_source, guid_id = guid.id.split("://")

                # If show provider source and show provider id are in videos_shows_ids exactly, then the show is in the list
                if guid_source in video_ids.keys():
                    if guid_id in video_ids[guid_source]:
                        episode_videos = []
                        if videos:
                            for show, episodes in videos.items():
                                show = {k: v for k, v in show}
                                if guid_source in show.keys():
                                    if guid_id == show[guid_source]:
                                        for episode in episodes:
                                            episode_videos.append(episode)

                        return episode_videos

        return None
    except Exception:
        return None


def get_video_status(plex_search, video_ids, videos):
    try:
        if not generate_guids and not generate_locations:
            return None

        if generate_locations:
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

        if generate_guids:
            for guid in plex_search.guids:
                guid_source, guid_id = guid.id.split("://")

                # If show provider source and show provider id are in videos_shows_ids exactly, then the show is in the list
                if guid_source in video_ids.keys():
                    if guid_id in video_ids[guid_source]:
                        for video in videos:
                            if guid_source in video.keys():
                                if guid_id == video[guid_source]:
                                    return video["status"]

        return None
    except Exception:
        return None


def update_user_watched(user, user_plex, library, watched_videos, dryrun):
    try:
        logger(f"Plex: Updating watched for {user.title} in library {library}", 1)
        (
            watched_shows_ids,
            watched_episodes_ids,
            watched_movies_ids,
        ) = generate_library_guids_dict(watched_videos)

        if (
            not watched_movies_ids
            and not watched_shows_ids
            and not watched_episodes_ids
        ):
            logger(
                f"Jellyfin: No videos to mark as watched for {user.title} in library {library}",
                1,
            )

            return

        logger(
            f"Plex: mark list\nShows: {watched_shows_ids}\nEpisodes: {watched_episodes_ids}\nMovies: {watched_movies_ids}",
            1,
        )

        library_videos = user_plex.library.section(library)
        if watched_movies_ids:
            for plex_movie in library_videos.search(unwatched=True):
                watched_movie_status = get_video_status(
                    plex_movie, watched_movies_ids, watched_videos
                )
                if watched_movie_status:
                    if watched_movie_status["completed"]:
                        msg = f"Plex: {plex_movie.title} as watched for {user.title} in {library}"
                        if not dryrun:
                            logger(msg, 5)
                            plex_movie.markWatched()
                        else:
                            logger(msg, 6)

                        log_marked(
                            "Plex",
                            user_plex.friendlyName,
                            user.title,
                            library,
                            plex_movie.title,
                            None,
                            None,
                        )
                    elif watched_movie_status["time"] > 60_000:
                        msg = f"Plex: {plex_movie.title} as partially watched for {floor(watched_movie_status['time'] / 60_000)} minutes for {user.title} in {library}"
                        if not dryrun:
                            logger(msg, 5)
                            plex_movie.updateTimeline(watched_movie_status["time"])
                        else:
                            logger(msg, 6)

                        log_marked(
                            "Plex",
                            user_plex.friendlyName,
                            user.title,
                            library,
                            plex_movie.title,
                            duration=watched_movie_status["time"],
                        )
                else:
                    logger(
                        f"Plex: Skipping movie {plex_movie.title} as it is not in mark list for {user.title}",
                        1,
                    )

        if watched_shows_ids and watched_episodes_ids:
            for plex_show in library_videos.search(unwatched=True):
                watched_show_episodes_status = find_video(
                    plex_show, watched_shows_ids, watched_videos
                )
                if watched_show_episodes_status:
                    for plex_episode in plex_show.episodes():
                        watched_episode_status = get_video_status(
                            plex_episode,
                            watched_episodes_ids,
                            watched_show_episodes_status,
                        )
                        if watched_episode_status:
                            if watched_episode_status["completed"]:
                                msg = f"Plex: {plex_show.title} {plex_episode.title} as watched for {user.title} in {library}"
                                if not dryrun:
                                    logger(msg, 5)
                                    plex_episode.markWatched()
                                else:
                                    logger(msg, 6)

                                log_marked(
                                    "Plex",
                                    user_plex.friendlyName,
                                    user.title,
                                    library,
                                    plex_show.title,
                                    plex_episode.title,
                                )
                            else:
                                msg = f"Plex: {plex_show.title} {plex_episode.title} as partially watched for {floor(watched_episode_status['time'] / 60_000)} minutes for {user.title} in {library}"
                                if not dryrun:
                                    logger(msg, 5)
                                    plex_episode.updateTimeline(
                                        watched_episode_status["time"]
                                    )
                                else:
                                    logger(msg, 6)

                                log_marked(
                                    "Plex",
                                    user_plex.friendlyName,
                                    user.title,
                                    library,
                                    plex_show.title,
                                    plex_episode.title,
                                    watched_episode_status["time"],
                                )
                        else:
                            logger(
                                f"Plex: Skipping episode {plex_episode.title} as it is not in mark list for {user.title}",
                                3,
                            )
                else:
                    logger(
                        f"Plex: Skipping show {plex_show.title} as it is not in mark list for {user.title}",
                        3,
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
        return f"Plex {self.plex.friendlyName}: {self.plex.version}"

    def get_users(self):
        try:
            users = self.plex.myPlexAccount().users()

            # append self to users
            users.append(self.plex.myPlexAccount())

            return users
        except Exception as e:
            logger(f"Plex: Failed to get users, Error: {e}", 2)
            raise Exception(e)

    def get_libraries(self):
        try:
            output = {}

            libraries = self.plex.library.sections()

            for library in libraries:
                library_title = library.title
                library_type = library.type

                output[library_title] = library_type

            return output
        except Exception as e:
            logger(f"Plex: Failed to get libraries, Error: {e}", 2)
            raise Exception(e)

    def get_watched(self, users, sync_libraries):
        try:
            # Get all libraries
            users_watched = {}

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
                    if library.title not in sync_libraries:
                        continue

                    user_watched = get_user_library_watched(user, user_plex, library)

                    for user_watched, user_watched_temp in user_watched.items():
                        if user_watched not in users_watched:
                            users_watched[user_watched] = {}
                        users_watched[user_watched].update(user_watched_temp)

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

                for library, watched_videos in libraries.items():
                    library_other = None
                    if library_mapping:
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
                            watched_videos,
                            dryrun,
                        ]
                    )

            future_thread_executor(args)
        except Exception as e:
            logger(f"Plex: Failed to update watched, Error: {e}", 2)
            raise Exception(e)
