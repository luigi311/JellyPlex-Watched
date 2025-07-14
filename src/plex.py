from datetime import datetime, timezone
import requests
from loguru import logger

from urllib3.poolmanager import PoolManager
from math import floor

from requests.adapters import HTTPAdapter as RequestsHTTPAdapter

from plexapi.video import Show, Episode, Movie
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount, MyPlexUser
from plexapi.library import MovieSection, ShowSection

from src.functions import (
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
    item: Movie | Show | Episode,
    generate_guids: bool,
    generate_locations: bool,
) -> MediaIdentifiers:
    guids = extract_guids_from_item(item, generate_guids)
    locations = (
        tuple([location.split("/")[-1] for location in item.locations])
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
    )


def get_mediaitem(
    item: Movie | Episode,
    completed: bool,
    generate_guids: bool = True,
    generate_locations: bool = True,
) -> MediaItem:
    last_viewed_at = item.lastViewedAt
    viewed_date = datetime.today()

    if last_viewed_at:
        viewed_date = last_viewed_at.replace(tzinfo=timezone.utc)

    return MediaItem(
        identifiers=extract_identifiers_from_item(
            item, generate_guids, generate_locations
        ),
        status=WatchedStatus(
            completed=completed, time=item.viewOffset, viewed_date=viewed_date
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

            # append self to users
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
                library_title = library.title
                library_type = library.type

                if library_type not in ["movie", "show"]:
                    logger.debug(
                        f"Plex: Skipping Library {library_title} found type {library_type}",
                    )
                    continue

                output[library_title] = library_type

            return output
        except Exception as e:
            logger.error(f"Plex: Failed to get libraries, Error: {e}")
            raise Exception(e)

    def get_user_library_watched(
        self, user_name: str, user_plex: PlexServer, library: MovieSection | ShowSection
    ) -> LibraryData:
        try:
            logger.info(
                f"Plex: Generating watched for {user_name} in library {library.title}",
            )
            watched = LibraryData(title=library.title)

            library_videos = user_plex.library.section(library.title)

            if library.type == "movie":
                for video in library_videos.search(
                    unwatched=False
                ) + library_videos.search(inProgress=True):
                    if video.isWatched or video.viewOffset >= 60000:
                        watched.movies.append(
                            get_mediaitem(
                                video,
                                video.isWatched,
                                self.generate_guids,
                                self.generate_locations,
                            )
                        )

            elif library.type == "show":
                # Keep track of processed shows to reduce duplicate shows
                processed_shows = []
                for show in library_videos.search(
                    unwatched=False
                ) + library_videos.search(inProgress=True):
                    if show.key in processed_shows:
                        continue
                    processed_shows.append(show.key)
                    show_guids = extract_guids_from_item(show, self.generate_guids)
                    episode_mediaitem = []

                    # Fetch watched or partially watched episodes
                    for episode in show.watched() + show.episodes(
                        viewOffset__gte=60_000
                    ):
                        episode_mediaitem.append(
                            get_mediaitem(
                                episode,
                                episode.isWatched,
                                self.generate_guids,
                                self.generate_locations,
                            )
                        )

                    if episode_mediaitem:
                        watched.series.append(
                            Series(
                                identifiers=MediaIdentifiers(
                                    title=show.title,
                                    locations=(
                                        tuple(
                                            [
                                                location.split("/")[-1]
                                                for location in show.locations
                                            ]
                                        )
                                        if self.generate_locations
                                        else tuple()
                                    ),
                                    imdb_id=show_guids.get("imdb"),
                                    tvdb_id=show_guids.get("tvdb"),
                                    tmdb_id=show_guids.get("tmdb"),
                                ),
                                episodes=episode_mediaitem,
                            )
                        )

            return watched

        except Exception as e:
            logger.error(
                f"Plex: Failed to get watched for {user_name} in library {library.title}, Error: {e}",
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
                users_watched: dict[str, UserData] = {}

            for user in users:
                if self.admin_user == user:
                    user_plex = self.plex
                else:
                    token = user.get_token(self.plex.machineIdentifier)
                    if token:
                        user_plex = self.login(self.base_url, token, None, None, None)
                    else:
                        logger.error(
                            f"Plex: Failed to get token for {user.title}, skipping",
                        )
                        continue

                user_name: str = (
                    user.username.lower() if user.username else user.title.lower()
                )

                libraries = user_plex.library.sections()

                for library in libraries:
                    if library.title not in sync_libraries:
                        continue

                    if user_name not in users_watched:
                        users_watched[user_name] = UserData()

                    if library.title in users_watched[user_name].libraries:
                        logger.info(
                            f"Plex: {user_name} {library.title} watched history has already been gathered, skipping"
                        )
                        continue

                    library_data = self.get_user_library_watched(
                        user_name, user_plex, library
                    )

                    users_watched[user_name].libraries[library.title] = library_data

            return users_watched
        except Exception as e:
            logger.error(f"Plex: Failed to get users watched, Error: {e}")
            return {}

    def update_user_watched(
        self,
        user: MyPlexAccount,
        user_plex: PlexServer,
        library_data: LibraryData,
        library_name: str,
        dryrun: bool,
    ) -> None:
        # If there are no movies or shows to update, exit early.
        if not library_data.series and not library_data.movies:
            return

        logger.info(
            f"Plex: Updating watched for {user.title} in library {library_name}"
        )
        library_section = user_plex.library.section(library_name)
        if not library_section:
            logger.error(
                f"Plex: Library {library_name} not found for {user.title}, skipping",
            )
            return

        # Update movies.
        if library_data.movies:
            # Search for Plex movies that are currently marked as unwatched.
            for plex_movie in library_section.search(unwatched=True):
                plex_identifiers = extract_identifiers_from_item(
                    plex_movie, self.generate_guids, self.generate_locations
                )
                # Check each stored movie for a match.
                for stored_movie in library_data.movies:
                    if check_same_identifiers(
                        plex_identifiers, stored_movie.identifiers
                    ):
                        # If the stored movie is marked as watched (or has enough progress),
                        # update the Plex movie accordingly.
                        if stored_movie.status.completed:
                            msg = f"Plex: {plex_movie.title} as watched for {user.title} in {library_name}"
                            if not dryrun:
                                try:
                                    plex_movie.markWatched()
                                except Exception as e:
                                    logger.error(
                                        f"Plex: Failed to mark {plex_movie.title} as watched, Error: {e}"
                                    )
                                    continue

                            logger.success(f"{'[DRYRUN] ' if dryrun else ''}{msg}")
                            log_marked(
                                "Plex",
                                user_plex.friendlyName,
                                user.title,
                                library_name,
                                plex_movie.title,
                                None,
                                None,
                                mark_file=get_env_value(
                                    self.env, "MARK_FILE", "mark.log"
                                ),
                            )
                        else:
                            msg = f"Plex: {plex_movie.title} as partially watched for {floor(stored_movie.status.time / 60_000)} minutes for {user.title} in {library_name}"
                            if not dryrun:
                                try:
                                    plex_movie.updateTimeline(stored_movie.status.time)
                                except Exception as e:
                                    logger.error(
                                        f"Plex: Failed to update {plex_movie.title} timeline, Error: {e}"
                                    )
                                    continue

                            logger.success(f"{'[DRYRUN] ' if dryrun else ''}{msg}")
                            log_marked(
                                "Plex",
                                user_plex.friendlyName,
                                user.title,
                                library_name,
                                plex_movie.title,
                                duration=stored_movie.status.time,
                                mark_file=get_env_value(
                                    self.env, "MARK_FILE", "mark.log"
                                ),
                            )
                        # Once matched, no need to check further.
                        break

        # Update TV Shows (series/episodes).
        if library_data.series:
            # For each Plex show in the library section:
            plex_shows = library_section.search(unwatched=True)
            for plex_show in plex_shows:
                # Extract identifiers from the Plex show.
                plex_show_identifiers = extract_identifiers_from_item(
                    plex_show, self.generate_guids, self.generate_locations
                )
                # Try to find a matching series in your stored library.
                for stored_series in library_data.series:
                    if check_same_identifiers(
                        plex_show_identifiers, stored_series.identifiers
                    ):
                        logger.trace(f"Found matching show for '{plex_show.title}'")
                        # Now update episodes.
                        # Get the list of Plex episodes for this show.
                        plex_episodes = plex_show.episodes()
                        for plex_episode in plex_episodes:
                            plex_episode_identifiers = extract_identifiers_from_item(
                                plex_episode,
                                self.generate_guids,
                                self.generate_locations,
                            )
                            for stored_ep in stored_series.episodes:
                                if check_same_identifiers(
                                    plex_episode_identifiers, stored_ep.identifiers
                                ):
                                    if stored_ep.status.completed:
                                        msg = f"Plex: {plex_show.title} {plex_episode.title} as watched for {user.title} in {library_name}"
                                        if not dryrun:
                                            try:
                                                plex_episode.markWatched()
                                            except Exception as e:
                                                logger.error(
                                                    f"Plex: Failed to mark {plex_show.title} {plex_episode.title} as watched, Error: {e}"
                                                )
                                                continue

                                        logger.success(
                                            f"{'[DRYRUN] ' if dryrun else ''}{msg}"
                                        )
                                        log_marked(
                                            "Plex",
                                            user_plex.friendlyName,
                                            user.title,
                                            library_name,
                                            plex_show.title,
                                            plex_episode.title,
                                            mark_file=get_env_value(
                                                self.env, "MARK_FILE", "mark.log"
                                            ),
                                        )
                                    else:
                                        msg = f"Plex: {plex_show.title} {plex_episode.title} as partially watched for {floor(stored_ep.status.time / 60_000)} minutes for {user.title} in {library_name}"
                                        if not dryrun:
                                            try:
                                                plex_episode.updateTimeline(
                                                    stored_ep.status.time
                                                )
                                            except Exception as e:
                                                logger.error(
                                                    f"Plex: Failed to update {plex_show.title} {plex_episode.title} timeline, Error: {e}"
                                                )
                                                continue

                                        logger.success(
                                            f"{'[DRYRUN] ' if dryrun else ''}{msg}"
                                        )
                                        log_marked(
                                            "Plex",
                                            user_plex.friendlyName,
                                            user.title,
                                            library_name,
                                            plex_show.title,
                                            plex_episode.title,
                                            stored_ep.status.time,
                                            mark_file=get_env_value(
                                                self.env, "MARK_FILE", "mark.log"
                                            ),
                                        )
                                    break  # Found a matching episode.
                        break  # Found a matching show.

    def update_watched(
        self,
        watched_list: dict[str, UserData],
        user_mapping: dict[str, str] | None = None,
        library_mapping: dict[str, str] | None = None,
        dryrun: bool = False,
    ) -> None:
        for user, user_data in watched_list.items():
            user_other = None
            # If type of user is dict
            if user_mapping:
                user_other = search_mapping(user_mapping, user)

            for index, value in enumerate(self.users):
                username_title = (
                    value.username.lower() if value.username else value.title.lower()
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
                    logger.debug(
                        f"Plex: {user} is not a plex object, attempting to get object for user",
                    )
                    user = self.plex.myPlexAccount().user(user)

                if not isinstance(user, MyPlexUser):
                    logger.error(f"Plex: {user} failed to get PlexUser")
                    continue

                token = user.get_token(self.plex.machineIdentifier)
                if token:
                    user_plex = PlexServer(
                        self.base_url,
                        token,
                        session=self.session,
                    )
                else:
                    logger.error(
                        f"Plex: Failed to get token for {user.title}, skipping",
                    )
                    continue

            if not user_plex:
                logger.error(f"Plex: {user} Failed to get PlexServer")
                continue

            for library_name in user_data.libraries:
                library_data = user_data.libraries[library_name]
                library_other = None
                if library_mapping:
                    library_other = search_mapping(library_mapping, library_name)
                # if library in plex library list
                library_list = user_plex.library.sections()
                if library_name.lower() not in [x.title.lower() for x in library_list]:
                    if library_other:
                        if library_other.lower() in [
                            x.title.lower() for x in library_list
                        ]:
                            logger.info(
                                f"Plex: Library {library_name} not found, but {library_other} found, using {library_other}",
                            )
                            library_name = library_other
                        else:
                            logger.info(
                                f"Plex: Library {library_name} or {library_other} not found in library list",
                            )
                            continue
                    else:
                        logger.info(
                            f"Plex: Library {library_name} not found in library list",
                        )
                        continue

                try:
                    self.update_user_watched(
                        user,
                        user_plex,
                        library_data,
                        library_name,
                        dryrun,
                    )
                except Exception as e:
                    logger.error(
                        f"Plex: Failed to update watched for {user.title} in {library_name}, Error: {e}",
                    )
                    continue
