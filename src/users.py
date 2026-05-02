from loguru import logger
from plexapi.myplex import MyPlexAccount, MyPlexUser

from src.emby import Emby
from src.jellyfin import Jellyfin
from src.plex import Plex
from src.settings import AppSettings


def generate_user_list(server: Plex | Jellyfin | Emby) -> list[str]:
    # generate list of users from a server
    server_users: list[str] = []
    if isinstance(server, Plex):
        for user in server.users:
            server_users.append(
                user.username.lower() if user.username else user.title.lower()
            )

    elif isinstance(server, (Jellyfin, Emby)):
        server_users = [key.lower() for key in server.users.keys()]

    return server_users


def combine_user_lists(
    server_1: Plex | Jellyfin | Emby,
    server_2: Plex | Jellyfin | Emby,
    server_1_users: list[str],
    server_2_users: list[str],
    settings: AppSettings,
) -> dict[str, list[str]]:
    """
    Build the map of users that should sync between two servers, using the
    new settings model.

    Returns {source_username_on_server_1: [target_usernames_on_server_2, ...]}.

    A single source identity may fan out to multiple users on the other
    server (e.g. a shared family Plex account mapping to several individual
    Jellyfin users), so every server_1 key maps to a *list* of server_2
    usernames.

    The decision of *whether* a user syncs in a given direction is delegated
    entirely to settings.should_sync_user (blacklist/whitelist, per-user
    sync_rules, and the server-level sync_to fallback). The set of *target*
    usernames on the other server is resolved via
    settings.sync_targets_for_user (explicit user_mappings aliases plus the
    implicit same-username fallback).

    Both directions (1 -> 2 and 2 -> 1) are considered so the map covers
    relationships declared on either side, and targets discovered from each
    direction are merged rather than overwritten.
    """
    s1_name = server_1.server_settings.name
    s2_name = server_2.server_settings.name

    # Accumulate into sets to dedupe targets discovered from both directions.
    accumulator: dict[str, set[str]] = {}

    def add(s1_user: str, s2_user: str) -> None:
        accumulator.setdefault(s1_user, set()).add(s2_user)

    # server_1 -> server_2
    for s1_user in server_1_users:
        if not settings.should_sync_user(s1_user, s1_name, s2_name):
            continue
        for target in settings.sync_targets_for_user(s1_name, s1_user, s2_name):
            target = target.lower()
            if target in server_2_users:
                add(s1_user, target)

    # server_2 -> server_1 (fills in relationships declared the other way)
    for s2_user in server_2_users:
        if not settings.should_sync_user(s2_user, s2_name, s1_name):
            continue
        for target in settings.sync_targets_for_user(s2_name, s2_user, s1_name):
            target = target.lower()
            if target in server_1_users:
                # key is always the server_1-side username
                add(target, s2_user)

    # Freeze to sorted lists for a stable, deterministic result.
    return {s1_user: sorted(targets) for s1_user, targets in accumulator.items()}


def generate_server_users(
    server: Plex | Jellyfin | Emby,
    users: dict[str, list[str]],
) -> list[MyPlexAccount] | dict[str, str] | None:
    # Flatten the fan-out map into the full set of usernames relevant to
    # either side: every server_1-side key and every server_2-side target.
    source_names = set(users.keys())
    target_names = {target for targets in users.values() for target in targets}
    all_names = source_names | target_names

    if isinstance(server, Plex):
        plex_server_users: list[MyPlexAccount] = []
        for plex_user in server.users:
            username_title = (
                plex_user.username if plex_user.username else plex_user.title
            )

            if username_title.lower() in all_names:
                plex_server_users.append(plex_user)

        return plex_server_users
    elif isinstance(server, (Jellyfin, Emby)):
        jelly_emby_server_users: dict[str, str] = {}
        for jellyfin_user, jellyfin_id in server.users.items():
            if jellyfin_user.lower() in all_names:
                jelly_emby_server_users[jellyfin_user] = jellyfin_id

        return jelly_emby_server_users

    return None


def setup_users(
    server_1: Plex | Jellyfin | Emby,
    server_2: Plex | Jellyfin | Emby,
    settings: AppSettings,
) -> tuple[
    list[MyPlexAccount | MyPlexUser] | dict[str, str],
    list[MyPlexAccount | MyPlexUser] | dict[str, str],
]:
    server_1_users = generate_user_list(server_1)
    server_2_users = generate_user_list(server_2)
    logger.debug(f"Server 1 ({server_1.server_settings.name}) users: {server_1_users}")
    logger.debug(f"Server 2 ({server_2.server_settings.name}) users: {server_2_users}")

    # Blacklist/whitelist and per-user sync rules are all resolved inside
    # combine_user_lists via settings.should_sync_user, so there is no longer
    # a separate filtering step.
    users = combine_user_lists(
        server_1, server_2, server_1_users, server_2_users, settings
    )
    logger.debug(f"User list to sync between servers {users}")

    output_server_1_users = generate_server_users(server_1, users)
    output_server_2_users = generate_server_users(server_2, users)

    # Check if users is none or empty
    if output_server_1_users is None or len(output_server_1_users) == 0:
        logger.warning(
            f"No users found for server 1 {server_1.info()}, users: {server_1_users}, sync map {users}, server 1 users {server_1.users}"
        )

    if output_server_2_users is None or len(output_server_2_users) == 0:
        logger.warning(
            f"No users found for server 2 {server_2.info()}, users: {server_2_users}, sync map {users}, server 2 users {server_2.users}"
        )

    if (
        output_server_1_users is None
        or len(output_server_1_users) == 0
        or output_server_2_users is None
        or len(output_server_2_users) == 0
    ):
        raise Exception("No users found for one or both servers")

    logger.info(f"Server 1 users: {output_server_1_users}")
    logger.info(f"Server 2 users: {output_server_2_users}")

    return output_server_1_users, output_server_2_users
