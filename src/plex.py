import os, requests
from dotenv import load_dotenv

from urllib3.poolmanager import PoolManager
from math import floor

from requests.adapters import HTTPAdapter as RequestsHTTPAdapter

from plexapi.video import Show, Episode, Movie
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount

from src.functions import (
    logger,
    search_mapping,
    log_marked,
    str_to_bool,
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


def extract_guids_from_item(item: Movie | Show | Episode) -> dict[str, str]:
    # If GENERATE_GUIDS is set to False, then return an empty dict
    if not generate_guids:
        return {}

    guids: dict[str, str] = dict(
        guid.id.split("://")
        for guid in item.guids
        if guid.id is not None and len(guid.id.strip()) > 0
    )

    return guids


def extract_identifiers_from_item(item: Movie | Show | Episode) -> MediaIdentifiers:
    guids = extract_guids_from_item(item)

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

    return MediaIdentifiers(
        title=item.title,
        locations=(
            tuple([location.split("/")[-1] for location in item.locations])
            if generate_locations
            else tuple()
        ),
        imdb_id=guids.get("imdb", None),
        tvdb_id=guids.get("tvdb", None),
        tmdb_id=guids.get("tmdb", None),
    )


def get_mediaitem(item: Movie | Episode, completed=True) -> MediaItem:
    return MediaItem(
        identifiers=extract_identifiers_from_item(item),
        status=WatchedStatus(completed=completed, time=item.viewOffset),
    )


def update_user_watched(
    user: MyPlexAccount,
    user_plex: PlexServer,
    library_data: LibraryData,
    library_name: str,
    dryrun: bool,
):
    try:
        # If there are no movies or shows to update, exit early.
        if not library_data.series and not library_data.movies:
            return

        logger(f"Plex: Updating watched for {user.title} in library {library_name}", 1)
        library_section = user_plex.library.section(library_name)

        # Update movies.
        if library_data.movies:
            # Search for Plex movies that are currently marked as unwatched.
            for plex_movie in library_section.search(unwatched=True):
                plex_identifiers = extract_identifiers_from_item(plex_movie)
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
                                logger(msg, 5)
                                plex_movie.markWatched()
                            else:
                                logger(msg, 6)

                            log_marked(
                                "Plex",
                                user_plex.friendlyName,
                                user.title,
                                library_name,
                                plex_movie.title,
                                None,
                                None,
                            )
                        else:
                            msg = f"Plex: {plex_movie.title} as partially watched for {floor(stored_movie.status.time / 60_000)} minutes for {user.title} in {library_name}"
                            if not dryrun:
                                logger(msg, 5)
                                plex_movie.updateTimeline(stored_movie.status.time)
                            else:
                                logger(msg, 6)

                            log_marked(
                                "Plex",
                                user_plex.friendlyName,
                                user.title,
                                library_name,
                                plex_movie.title,
                                duration=stored_movie.status.time,
                            )
                        # Once matched, no need to check further.
                        break

        # Update TV Shows (series/episodes).
        if library_data.series:
            # For each Plex show in the library section:
            plex_shows = library_section.search(unwatched=True)
            for plex_show in plex_shows:
                # Extract identifiers from the Plex show.
                plex_show_identifiers = extract_identifiers_from_item(plex_show)
                # Try to find a matching series in your stored library.
                for stored_series in library_data.series:
                    if check_same_identifiers(
                        plex_show_identifiers, stored_series.identifiers
                    ):
                        logger(f"Found matching show for '{plex_show.title}'", 1)
                        # Now update episodes.
                        # Get the list of Plex episodes for this show.
                        plex_episodes = plex_show.episodes()
                        for plex_episode in plex_episodes:
                            plex_episode_identifiers = extract_identifiers_from_item(
                                plex_episode
                            )
                            for stored_ep in stored_series.episodes:
                                if check_same_identifiers(
                                    plex_episode_identifiers, stored_ep.identifiers
                                ):
                                    if stored_ep.status.completed:
                                        msg = f"Plex: {plex_show.title} {plex_episode.title} as watched for {user.title} in {library_name}"
                                        if not dryrun:
                                            logger(msg, 5)
                                            plex_episode.markWatched()
                                        else:
                                            logger(msg, 6)

                                        log_marked(
                                            "Plex",
                                            user_plex.friendlyName,
                                            user.title,
                                            library_name,
                                            plex_show.title,
                                            plex_episode.title,
                                        )
                                    else:
                                        msg = f"Plex: {plex_show.title} {plex_episode.title} as partially watched for {floor(stored_ep.status.time / 60_000)} minutes for {user.title} in {library_name}"
                                        if not dryrun:
                                            logger(msg, 5)
                                            plex_episode.updateTimeline(
                                                stored_ep.status.time
                                            )
                                        else:
                                            logger(msg, 6)

                                        log_marked(
                                            "Plex",
                                            user_plex.friendlyName,
                                            user.title,
                                            library_name,
                                            plex_show.title,
                                            plex_episode.title,
                                            stored_ep.status.time,
                                        )
                                    break  # Found a matching episode.
                        break  # Found a matching show.
    except Exception as e:
        logger(
            f"Plex: Failed to update watched for {user.title} in library {library_name}, Error: {e}",
            2,
        )
        raise e


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

    def get_libraries(self) -> dict[str, str]:
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

    def get_user_library_watched(self, user, user_plex, library) -> LibraryData:
        user_name: str = user.username.lower() if user.username else user.title.lower()
        try:
            logger(
                f"Plex: Generating watched for {user_name} in library {library.title}",
                0,
            )
            watched = LibraryData(title=library.title)

            library_videos = user_plex.library.section(library.title)

            if library.type == "movie":
                for video in library_videos.search(
                    unwatched=False
                ) + library_videos.search(inProgress=True):
                    if video.isWatched or video.viewOffset >= 60000:
                        watched.movies.append(get_mediaitem(video, video.isWatched))

            elif library.type == "show":
                # Keep track of processed shows to reduce duplicate shows
                processed_shows = []
                for show in library_videos.search(
                    unwatched=False
                ) + library_videos.search(inProgress=True):
                    if show.key in processed_shows:
                        continue
                    processed_shows.append(show.key)
                    show_guids = extract_guids_from_item(show)
                    episode_mediaitem = []
                    for episode in show.episodes():
                        if episode.isWatched or episode.viewOffset >= 60000:

                            episode_mediaitem.append(
                                get_mediaitem(episode, episode.isWatched)
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
                                        if generate_locations
                                        else tuple()
                                    ),
                                    imdb_id=show_guids.get("imdb", None),
                                    tvdb_id=show_guids.get("tvdb", None),
                                    tmdb_id=show_guids.get("tmdb", None),
                                ),
                                episodes=episode_mediaitem,
                            )
                        )

            return watched

        except Exception as e:
            logger(
                f"Plex: Failed to get watched for {user_name} in library {library.title}, Error: {e}",
                2,
            )
            return LibraryData(title=library.title)

    def get_watched(self, users, sync_libraries) -> dict[str, UserData]:
        try:
            users_watched: dict[str, UserData] = {}

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
                        continue

                libraries = user_plex.library.sections()

                for library in libraries:
                    if library.title not in sync_libraries:
                        continue

                    library_data = self.get_user_library_watched(
                        user, user_plex, library
                    )

                    if user.title.lower() not in users_watched:
                        users_watched[user.title.lower()] = UserData()

                    users_watched[user.title.lower()].libraries[
                        library.title
                    ] = library_data

            return users_watched
        except Exception as e:
            logger(f"Plex: Failed to get watched, Error: {e}", 2)
            raise Exception(e)

    def update_watched(
        self,
        watched_list: dict[str, UserData],
        user_mapping=None,
        library_mapping=None,
        dryrun=False,
    ):
        try:
            for user, user_data in watched_list.items():
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

                for library_name in user_data.libraries:
                    library_data = user_data.libraries[library_name]
                    library_other = None
                    if library_mapping:
                        library_other = search_mapping(library_mapping, library_name)
                    # if library in plex library list
                    library_list = user_plex.library.sections()
                    if library_name.lower() not in [
                        x.title.lower() for x in library_list
                    ]:
                        if library_other:
                            if library_other.lower() in [
                                x.title.lower() for x in library_list
                            ]:
                                logger(
                                    f"Plex: Library {library_name} not found, but {library_other} found, using {library_other}",
                                    1,
                                )
                                library_name = library_other
                            else:
                                logger(
                                    f"Plex: Library {library_name} or {library_other} not found in library list",
                                    1,
                                )
                                continue
                        else:
                            logger(
                                f"Plex: Library {library_name} not found in library list",
                                1,
                            )
                            continue

                    update_user_watched(
                        user,
                        user_plex,
                        library_data,
                        library_name,
                        dryrun,
                    )

        except Exception as e:
            logger(f"Plex: Failed to update watched, Error: {e}", 2)
            raise Exception(e)
