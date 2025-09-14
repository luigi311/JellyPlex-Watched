from datetime import datetime, timezone
import requests
from loguru import logger
from typing import Any

from urllib3.poolmanager import PoolManager
from math import floor

from requests.adapters import HTTPAdapter as RequestsHTTPAdapter

from plexapi.video import Show, Episode, Movie
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount, MyPlexUser
from plexapi.library import MovieSection, ShowSection

from src.functions import (
    filename_from_any_path,
    search_mapping,
    log_marked,
    str_to_bool,
    get_env_value,
)
from src.watched import (
    LibraryData,
    MediaIdentifiers,
    MediaItem,
    WatchedStatus,
    Series,
    UserData,
    check_same_identifiers,
)


# Bypass hostname validation for ssl. Taken from https://github.com/pkkid/python-plexapi/issues/143#issuecomment-775485186
class HostNameIgnoringAdapter(RequestsHTTPAdapter):
    def init_poolmanager(
        self, connections: int, maxsize: int | None, block=..., **pool_kwargs
    ) -> None:
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            assert_hostname=False,
            **pool_kwargs,
        )


def extract_guids_from_item(
    item: Movie | Show | Episode, generate_guids: bool
) -> dict[str, str]:
    # If GENERATE_GUIDS is set to False, then return an empty dict
    if not generate_guids:
        return {}

    guids: dict[str, str] = dict(
        guid.id.split("://")
        for guid in item.guids
        if guid.id and len(guid.id.strip()) > 0
    )

    return guids


def extract_identifiers_from_item(
    server: Any,
    user_id: str,
    item: Movie | Show | Episode,
    generate_guids: bool,
    generate_locations: bool,
) -> MediaIdentifiers:
    guids = extract_guids_from_item(item, generate_guids)
    locations = (
        tuple([filename_from_any_path(loc) for loc in item.locations])
        if generate_locations
        else tuple()
    )

    if generate_guids:
        if not guids:
            logger.debug(
                f"Plex: {item.title} has no guids{f', locations: {" ".join(item.locations)}' if generate_locations else ''}",
            )

    if generate_locations:
        if not locations:
            logger.debug(
                f"Plex: {item.title} has no locations{f', guids: {guids}' if generate_guids else ''}",
            )

    return MediaIdentifiers(
        title=item.title,
        locations=locations,
        imdb_id=guids.get("imdb"),
        tvdb_id=guids.get("tvdb"),
        tmdb_id=guids.get("tmdb"),
        id=item.ratingKey,
        server=server,
        user_id=user_id,
    )


def get_mediaitem(
    server: Any,
    user_id: str,
    item: Movie | Episode,
    completed: bool,
    generate_guids: bool = True,
    generate_locations: bool = True,
) -> MediaItem:
    last_viewed_at = item.lastViewedAt
    viewed_date = datetime.today()

    if last_viewed_at:
        viewed_date = last_viewed_at.replace(tzinfo=timezone.utc)

    # updatedAt is a datetime object
    last_updated_at = item.updatedAt.replace(tzinfo=timezone.utc)

    return MediaItem(
        identifiers=extract_identifiers_from_item(
            server, user_id, item, generate_guids, generate_locations
        ),
        status=WatchedStatus(
            completed=completed,
            time=item.viewOffset,
            viewed_date=viewed_date,
            last_updated_at=last_updated_at,
        ),
    )


# class plex accept base url and token and username and password but default with none
class Plex:
    def __init__(
        self,
        env,
        base_url: str | None = None,
        token: str | None = None,
        user_name: str | None = None,
        password: str | None = None,
        server_name: str | None = None,
        ssl_bypass: bool = False,
        session: requests.Session | None = None,
    ) -> None:
        self.env = env

        self.server_type: str = "Plex"
        self.ssl_bypass: bool = ssl_bypass
        if ssl_bypass:
            # Session for ssl bypass
            session = requests.Session()
            # By pass ssl hostname check https://github.com/pkkid/python-plexapi/issues/143#issuecomment-775485186
            session.mount("https://", HostNameIgnoringAdapter())
        self.session = session
        self.plex: PlexServer = self.login(
            base_url, token, user_name, password, server_name
        )

        self.base_url: str = self.plex._baseurl

        self.admin_user: MyPlexAccount = self.plex.myPlexAccount()
        self.users: list[MyPlexUser | MyPlexAccount] = self.get_users()
        self.generate_guids: bool = str_to_bool(
            get_env_value(self.env, "GENERATE_GUIDS", "True")
        )
        self.generate_locations: bool = str_to_bool(
            get_env_value(self.env, "GENERATE_LOCATIONS", "True")
        )

    def login(
        self,
        base_url: str | None,
        token: str | None,
        user_name: str | None,
        password: str | None,
        server_name: str | None,
    ) -> PlexServer:
        try:
            if base_url and token:
                plex: PlexServer = PlexServer(base_url, token, session=self.session)
            elif user_name and password and server_name:
                # Login via plex account
                account = MyPlexAccount(user_name, password)
                plex = account.resource(server_name).connect()
            else:
                raise Exception("No complete plex credentials provided")

            return plex
        except Exception as e:
            if user_name:
                msg = f"Failed to login via plex account {user_name}"
                logger.error(f"Plex: Failed to login, {msg}, Error: {e}")
            else:
                logger.error(f"Plex: Failed to login, Error: {e}")
            raise Exception(e)

    def info(self) -> str:
        return f"Plex {self.plex.friendlyName}: {self.plex.version}"

    def get_users(self) -> list[MyPlexUser | MyPlexAccount]:
        try:
            users: list[MyPlexUser | MyPlexAccount] = self.plex.myPlexAccount().users()
            users.append(self.plex.myPlexAccount())
            return users
        except Exception as e:
            logger.error(f"Plex: Failed to get users, Error: {e}")
            raise Exception(e)

    def get_libraries(self) -> dict[str, str]:
        try:
            output = {}
            libraries = self.plex.library.sections()
            logger.debug(
                f"Plex: All Libraries {[library.title for library in libraries]}"
            )
            for library in libraries:
                if library.type in ["movie", "show"]:
                    output[library.title] = library.type
                else:
                    logger.debug(
                        f"Plex: Skipping Library {library.title} found type {library.type}",
                    )
            return output
        except Exception as e:
            logger.error(f"Plex: Failed to get libraries, Error: {e}")
            raise Exception(e)

    def get_user_library_watched(
        self, user_id: str, user_plex: PlexServer, library: MovieSection | ShowSection
    ) -> LibraryData:
        try:
            logger.info(
                f"Plex: Generating watched for {user_id} in library {library.title}",
            )
            watched = LibraryData(title=library.title)
            library_videos = user_plex.library.section(library.title)

            if library.type == "movie":
                for video in library_videos.search(unwatched=False) + library_videos.search(inProgress=True):
                    if video.isWatched or video.viewOffset >= 60000:
                        watched.movies.append(
                            get_mediaitem(
                                self, user_id, video, video.isWatched, self.generate_guids, self.generate_locations
                            )
                        )
            elif library.type == "show":
                processed_shows = []
                for show in library_videos.search(unwatched=False) + library_videos.search(inProgress=True):
                    if show.key in processed_shows:
                        continue
                    processed_shows.append(show.key)
                    show_guids = extract_guids_from_item(show, self.generate_guids)
                    episode_mediaitem = []
                    for episode in show.watched() + show.episodes(viewOffset__gte=60_000):
                        episode_mediaitem.append(
                            get_mediaitem(
                                self, user_id, episode, episode.isWatched, self.generate_guids, self.generate_locations
                            )
                        )
                    if episode_mediaitem:
                        watched.series.append(
                            Series(
                                identifiers=extract_identifiers_from_item(self, user_id, show, self.generate_guids, self.generate_locations),
                                episodes=episode_mediaitem,
                            )
                        )
            return watched
        except Exception as e:
            logger.error(
                f"Plex: Failed to get watched for {user_id} in library {library.title}, Error: {e}",
            )
            return LibraryData(title=library.title)

    def get_watched(
        self,
        users: list[MyPlexUser | MyPlexAccount],
        sync_libraries: list[str],
        users_watched: dict[str, UserData] = None,
    ) -> dict[str, UserData]:
        try:
            if not users_watched:
                users_watched = {}

            for user in users:
                user_plex = self.plex if self.admin_user == user else self.login(self.base_url, user.get_token(self.plex.machineIdentifier), None, None, None)
                if not user_plex:
                    logger.error(f"Plex: Failed to get token for {user.title}, skipping")
                    continue

                user_name = user.username.lower() if user.username else user.title.lower()
                if user_name not in users_watched:
                    users_watched[user_name] = UserData()

                for library in user_plex.library.sections():
                    if library.title not in sync_libraries:
                        continue
                    if library.title in users_watched[user_name].libraries:
                        logger.info(f"Plex: {user_name} {library.title} watched history has already been gathered, skipping")
                        continue

                    library_data = self.get_user_library_watched(user_name, user_plex, library)
                    users_watched[user_name].libraries[library.title] = library_data

            return users_watched
        except Exception as e:
            logger.error(f"Plex: Failed to get users watched, Error: {e}")
            return {}

    def get_plex_user_from_id(self, user_id: str) -> MyPlexUser | MyPlexAccount | None:
        for u in self.users:
            username = u.username.lower() if u.username else u.title.lower()
            if username == user_id.lower():
                return u
        return None

    def mark_watched(self, user_id: str, item_id: str):
        user = self.get_plex_user_from_id(user_id)
        if not user:
            logger.error(f"Plex: User {user_id} not found.")
            return

        user_plex = self.plex if self.admin_user == user else self.login(self.base_url, user.get_token(self.plex.machineIdentifier), None, None, None)
        item = user_plex.fetchItem(int(item_id))
        if item:
            item.markWatched()

    def mark_unwatched(self, user_id: str, item_id: str):
        user = self.get_plex_user_from_id(user_id)
        if not user:
            logger.error(f"Plex: User {user_id} not found.")
            return

        user_plex = self.plex if self.admin_user == user else self.login(self.base_url, user.get_token(self.plex.machineIdentifier), None, None, None)
        item = user_plex.fetchItem(int(item_id))
        if item:
            item.markUnwatched()

    def update_watched(
        self,
        watched_list: dict[str, UserData],
        user_mapping: dict[str, str] | None = None,
        library_mapping: dict[str, str] | None = None,
        dryrun: bool = False,
    ) -> None:
        # This function is now deprecated and will be removed.
        # The new sync logic in watched.py will be used instead.
        pass
