from __future__ import annotations

from datetime import datetime, timezone
from math import floor

import requests
from loguru import logger
from plexapi.library import MovieSection, ShowSection
from plexapi.myplex import MyPlexAccount, MyPlexUser
from plexapi.server import PlexServer
from plexapi.video import Episode, Movie, Show
from requests.adapters import HTTPAdapter as RequestsHTTPAdapter
from urllib3.poolmanager import PoolManager

from src.functions import (
    filename_from_any_path,
    log_marked,
)
from src.settings import AppSettings, PlexSettings
from src.watched import (
    LibraryData,
    MediaIdentifiers,
    MediaItem,
    Series,
    UserData,
    WatchedStatus,
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
        # PlexAPI returns naive datetime in local system timezone
        # Get the local timezone and convert to UTC for consistent comparison
        local_tz = datetime.now().astimezone().tzinfo
        viewed_date = last_viewed_at.replace(tzinfo=local_tz).astimezone(timezone.utc)

    # Plex does not remove completion status if a user has watched it before but then rewatches but does not finish.
    # So if the item is marked as complete but the view status is not less than 60 seconds, we will consider it as not completed.
    # Viewoffset gets set to 0 when a video is marked as watched
    actually_completed = completed and item.viewOffset < 60_000

    return MediaItem(
        identifiers=extract_identifiers_from_item(
            item, generate_guids, generate_locations
        ),
        status=WatchedStatus(
            completed=actually_completed, time=item.viewOffset, viewed_date=viewed_date
        ),
    )


# class plex accept base url and token and username and password but default with none
class Plex:
    def __init__(
        self,
        app_settings: AppSettings,
        server_settings: PlexSettings,
        base_url: str | None = None,
        token: str | None = None,
        user_name: str | None = None,
        password: str | None = None,
        server_name: str | None = None,
        ssl_bypass: bool = False,
        session: requests.Session | None = None,
    ) -> None:
        self.app_settings: AppSettings = app_settings
        self.server_settings = server_settings

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
                                self.app_settings.generate_guids,
                                self.app_settings.generate_locations,
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
                    show_guids = extract_guids_from_item(
                        show, self.app_settings.generate_guids
                    )
                    episode_mediaitem = []

                    # Fetch watched or partially watched episodes
                    for episode in show.watched() + show.episodes(
                        viewOffset__gte=60_000
                    ):
                        episode_mediaitem.append(
                            get_mediaitem(
                                episode,
                                episode.isWatched,
                                self.app_settings.generate_guids,
                                self.app_settings.generate_locations,
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
                                                filename_from_any_path(location)
                                                for location in show.locations
                                            ]
                                        )
                                        if self.app_settings.generate_locations
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
        users_watched: dict[str, UserData] | None = None,
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
        user: MyPlexAccount | MyPlexUser,
        plex_server: PlexServer,
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
        library_section = plex_server.library.section(library_name)
        if not library_section:
            logger.error(
                f"Plex: Library {library_name} not found for {user.title}, skipping",
            )
            return

        # Update movies.
        if library_data.movies:
            # Search for Plex movies that are currently marked as unwatched.
            for plex_movie in library_section.search():
                plex_identifiers = extract_identifiers_from_item(
                    plex_movie,
                    self.app_settings.generate_guids,
                    self.app_settings.generate_locations,
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
                                plex_server.friendlyName,
                                user.title,
                                library_name,
                                plex_movie.title,
                                None,
                                None,
                                mark_file=self.app_settings.mark_file,
                            )
                        else:
                            msg = f"Plex: {plex_movie.title} as partially watched for {floor(stored_movie.status.time / 60_000)} minutes for {user.title} in {library_name}"
                            if not dryrun:
                                try:
                                    plex_movie.markUnwatched()  # Unmark as watched first so completed status is set to false
                                    plex_movie.updateTimeline(stored_movie.status.time)
                                except Exception as e:
                                    logger.error(
                                        f"Plex: Failed to update {plex_movie.title} timeline, Error: {e}"
                                    )
                                    continue

                            logger.success(f"{'[DRYRUN] ' if dryrun else ''}{msg}")
                            log_marked(
                                "Plex",
                                plex_server.friendlyName,
                                user.title,
                                library_name,
                                plex_movie.title,
                                duration=stored_movie.status.time,
                                mark_file=self.app_settings.mark_file,
                            )
                        # Once matched, no need to check further.
                        break

        # Update TV Shows (series/episodes).
        if library_data.series:
            # For each Plex show in the library section:
            plex_shows = library_section.search()
            for plex_show in plex_shows:
                # Extract identifiers from the Plex show.
                plex_show_identifiers = extract_identifiers_from_item(
                    plex_show,
                    self.app_settings.generate_guids,
                    self.app_settings.generate_locations,
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
                                self.app_settings.generate_guids,
                                self.app_settings.generate_locations,
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
                                            plex_server.friendlyName,
                                            user.title,
                                            library_name,
                                            plex_show.title,
                                            plex_episode.title,
                                            mark_file=self.app_settings.mark_file,
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
                                            plex_server.friendlyName,
                                            user.title,
                                            library_name,
                                            plex_show.title,
                                            plex_episode.title,
                                            stored_ep.status.time,
                                            mark_file=self.app_settings.mark_file,
                                        )
                                    break  # Found a matching episode.
                        break  # Found a matching show.

    def _resolve_local_user(
        self, source_server: str, source_user: str
    ) -> MyPlexUser | MyPlexAccount | None:
        """
        Resolve a source-server username to the matching Plex user object on
        this server.

        Candidate names on this Plex server are produced by the settings
        model (sync_targets_for_user — explicit user_mappings aliases plus the
        implicit same-username fallback). The first candidate that matches one
        of this server's actual users (by username or title, case-insensitive)
        is returned. Returns None if no candidate matches.
        """
        this_server = self.server_settings.name
        candidates = self.app_settings.sync_targets_for_user(
            source_server, source_user, this_server
        )
        candidates_lc = {c.lower() for c in candidates}

        for plex_user in self.users:
            username_title = (
                plex_user.username.lower()
                if plex_user.username
                else plex_user.title.lower()
            )
            if username_title in candidates_lc:
                return plex_user

        return None

    def _resolve_local_library(
        self,
        source_server: str,
        source_library: str,
        available_titles: list[str],
    ) -> str | None:
        """
        Resolve a source-server library name to the matching library title on
        this Plex server.

        Mirrors _resolve_local_user: candidates come from
        sync_targets_for_library, and the first one present in
        `available_titles` (case-insensitive) is returned, preserving the
        actual title casing as this server reports it.
        """
        this_server = self.server_settings.name
        candidates = self.app_settings.sync_targets_for_library(
            source_server, source_library, this_server
        )

        titles_by_lc = {title.lower(): title for title in available_titles}
        for candidate in candidates:
            actual = titles_by_lc.get(candidate.lower())
            if actual is not None:
                return actual

        return None

    def update_watched(
        self,
        watched_list: dict[str, UserData],
        source_server_name: str,
    ) -> None:
        """
        Apply watch state from `watched_list` (keyed by names as reported on
        `source_server`) onto this Plex server.

        User and library correspondence is resolved through the settings model
        via source_server's configured name, so explicit mappings and the
        implicit same-name fallback are both honored. Fan-out is resolved
        upstream; each key here maps to a single user/library on this server.
        """
        dryrun = self.app_settings.dryrun

        for source_user, user_data in watched_list.items():
            # Resolve the source-server user to a Plex user object on this server.
            plex_user = self._resolve_local_user(source_server_name, source_user)
            if plex_user is None:
                logger.info(
                    f"Plex: {source_user} (from {source_server_name}) not found on this server, skipping",
                )
                continue

            if self.admin_user == plex_user:
                plex_server = self.plex
            else:
                if not isinstance(plex_user, MyPlexUser):
                    logger.error(f"Plex: {plex_user} failed to get PlexUser")
                    continue

                token = plex_user.get_token(self.plex.machineIdentifier)
                if token:
                    plex_server = PlexServer(
                        self.base_url,
                        token,
                        session=self.session,
                    )
                else:
                    logger.error(
                        f"Plex: Failed to get token for {plex_user.title}, skipping",
                    )
                    continue

            if not plex_server:
                logger.error(f"Plex: {plex_user} Failed to get PlexServer")
                continue

            library_list = plex_server.library.sections()
            available_titles = [x.title for x in library_list]

            for library_name in user_data.libraries:
                library_data = user_data.libraries[library_name]

                # Resolve the source-server library name to a title on this server.
                resolved_library = self._resolve_local_library(
                    source_server_name, library_name, available_titles
                )
                if resolved_library is None:
                    logger.info(
                        f"Plex: Library {library_name} (from {source_server_name}) not found in library list",
                    )
                    continue

                try:
                    self.update_user_watched(
                        plex_user,
                        plex_server,
                        library_data,
                        resolved_library,
                        dryrun,
                    )
                except Exception as e:
                    logger.error(
                        f"Plex: Failed to update watched for {plex_user.title} in {resolved_library}, Error: {e}",
                    )
                    continue
