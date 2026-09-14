"""Select the per-user libraries needed for the watched-data fetch phase."""

from dataclasses import dataclass
from typing import cast

from loguru import logger
from plexapi.myplex import MyPlexAccount, MyPlexUser

from src.emby import Emby
from src.functions import normalize_name
from src.jellyfin import Jellyfin
from src.library import combine_library_lists
from src.plex import Plex
from src.settings import AppSettings
from src.users import combine_user_lists
from src.watched import UserData


type Server = Plex | Jellyfin | Emby
type ServerUser = MyPlexAccount | MyPlexUser | tuple[str, str]


@dataclass
class UserLibraries:
    user: ServerUser
    libraries: dict[str, str]  # Original library name -> server-native type.

    @property
    def username(self) -> str:
        if isinstance(self.user, tuple):
            return normalize_name(cast(tuple[str, str], self.user)[0])
        return normalize_name(self.user.username or self.user.title)


def generate_sync_inventory(
    server_users: dict[Server, list[ServerUser]],
    settings: AppSettings,
) -> dict[Server, list[UserLibraries]]:
    """Fetch each selected user's libraries once and retain both sync ends.

    Omit empty users and servers. This inventory specifies what to fetch;
    updates must still apply directional user and library policy.
    """
    inventory: dict[Server, dict[str, UserLibraries]] = {}
    for server, users in server_users.items():
        inventory[server] = {}
        for user in users:
            try:
                if isinstance(server, Plex) and not isinstance(user, tuple):
                    libraries = server.get_user_libraries(user)
                elif isinstance(server, (Jellyfin, Emby)) and isinstance(user, tuple):
                    libraries = server.get_user_libraries(cast(tuple[str, str], user))
                else:
                    raise TypeError("User representation does not match server")
            except Exception as error:
                # Adapter errors may contain credentials; log only the error type.
                logger.warning(
                    "Skipping library discovery for user {} on {} ({})",
                    UserLibraries(user, {}).username,
                    server.server_settings.name,
                    type(error).__name__,
                )
                continue
            entry = UserLibraries(user, libraries)
            inventory[server][entry.username] = entry

    selected: dict[Server, dict[str, set[str]]] = {
        server: {} for server in server_users
    }

    def permits(
        source: str,
        target: str,
        source_user: str,
        target_user: str,
        source_library: str,
        target_library: str,
    ) -> bool:
        return (
            settings.should_sync_user(source_user, source, target)
            and target_user
            in {
                normalize_name(name)
                for name in settings.sync_targets_for_user(source, source_user, target)
            }
            and settings.should_sync_library(source_library, source, target)
            and normalize_name(target_library)
            in {
                normalize_name(name)
                for name in settings.sync_targets_for_library(
                    source, source_library, target
                )
            }
        )

    servers = list(server_users)
    for index, source in enumerate(servers):
        for target in servers[index + 1 :]:
            source_name = source.server_settings.name
            target_name = target.server_settings.name
            user_pairs = combine_user_lists(
                source_name,
                target_name,
                list(inventory[source]),
                list(inventory[target]),
                settings,
            )
            for source_user, target_users in user_pairs.items():
                for target_user in target_users:
                    library_pairs = combine_library_lists(
                        source_name,
                        target_name,
                        inventory[source][source_user].libraries,
                        inventory[target][target_user].libraries,
                        settings,
                    )
                    for source_library, target_libraries in library_pairs.items():
                        for target_library in target_libraries:
                            if not (
                                permits(
                                    source_name,
                                    target_name,
                                    source_user,
                                    target_user,
                                    source_library,
                                    target_library,
                                )
                                or permits(
                                    target_name,
                                    source_name,
                                    target_user,
                                    source_user,
                                    target_library,
                                    source_library,
                                )
                            ):
                                continue
                            selected[source].setdefault(source_user, set()).add(
                                source_library
                            )
                            selected[target].setdefault(target_user, set()).add(
                                target_library
                            )

    return {
        server: [
            UserLibraries(
                entry.user,
                {
                    name: kind
                    for name, kind in entry.libraries.items()
                    if name in selected[server].get(username, set())
                },
            )
            for username, entry in users.items()
            if username in selected[server]
        ]
        for server, users in inventory.items()
        if selected[server]
    }


def fetch_watched_inventory(
    inventory: dict[Server, list[UserLibraries]],
) -> dict[Server, dict[str, UserData]]:
    """Fetch watched data once per selected user, with their own library filter.

    Fetch each user independently so an adapter failure returning an empty
    result cannot discard data already fetched for other users on that server.
    """
    servers_watched: dict[Server, dict[str, UserData]] = {}
    for server, entries in inventory.items():
        watched: dict[str, UserData] = {}
        for entry in entries:
            if not entry.libraries:
                continue
            user = entry.user
            try:
                if isinstance(server, Plex) and not isinstance(user, tuple):
                    user_watched = server.get_watched([user], list(entry.libraries))
                elif isinstance(server, (Jellyfin, Emby)) and isinstance(user, tuple):
                    username, user_id = cast(tuple[str, str], user)
                    user_watched = server.get_watched(
                        {username: user_id},
                        list(entry.libraries),
                        library_types=entry.libraries,
                    )
                else:
                    raise TypeError("User representation does not match server")
            except Exception as error:
                logger.warning(
                    "Skipping watched fetch for {} ({})",
                    entry.username,
                    type(error).__name__,
                )
                continue
            # Missing data is unknown, not a successfully fetched empty history.
            user_data = user_watched.get(entry.username)
            if user_data is None or not {
                normalize_name(name) for name in entry.libraries
            }.issubset({normalize_name(name) for name in user_data.libraries}):
                logger.warning(
                    "Skipping incomplete watched fetch for {}", entry.username
                )
                continue
            watched.update(user_watched)
        servers_watched[server] = watched
    return servers_watched
