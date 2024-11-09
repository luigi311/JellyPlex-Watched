from typing import Literal
from plexapi.myplex import MyPlexAccount
from src.emby import Emby
from src.jellyfin import Jellyfin
from src.plex import Plex
from src.functions import (
    logger,
    search_mapping,
)


def generate_user_list(
    server: tuple[Literal["plex", "jellyfin", "emby"], Plex | Jellyfin | Emby]
) -> list[str]:
    # generate list of users from server 1 and server 2
    server_type = server[0]
    server_connection = server[1]

    server_users: list[str] = []
    if server_type == "plex":
        for user in server_connection.users:
            server_users.append(
                user.username.lower() if user.username else user.title.lower()
            )

    elif server_type in ["jellyfin", "emby"]:
        server_users = [key.lower() for key in server_connection.users.keys()]

    return server_users


def combine_user_lists(
    server_1_users: list[str],
    server_2_users: list[str],
    user_mapping: dict[str, str] | None,
) -> dict[str, str]:
    # combined list of overlapping users from plex and jellyfin
    users: dict[str, str] = {}

    for server_1_user in server_1_users:
        if user_mapping:
            mapped_user = search_mapping(user_mapping, server_1_user)
            if mapped_user in server_2_users:
                users[server_1_user] = mapped_user
                continue

        if server_1_user in server_2_users:
            users[server_1_user] = server_1_user

    for server_2_user in server_2_users:
        if user_mapping:
            mapped_user = search_mapping(user_mapping, server_2_user)
            if mapped_user in server_1_users:
                users[mapped_user] = server_2_user
                continue

        if server_2_user in server_1_users:
            users[server_2_user] = server_2_user

    return users


def filter_user_lists(
    users: dict[str, str], blacklist_users: list[str], whitelist_users: list[str]
) -> dict[str, str]:
    users_filtered: dict[str, str] = {}
    for user in users:
        # whitelist_user is not empty and user lowercase is not in whitelist lowercase
        if len(whitelist_users) > 0:
            if user not in whitelist_users and users[user] not in whitelist_users:
                logger(f"{user} or {users[user]} is not in whitelist", 1)
                continue

        if user not in blacklist_users and users[user] not in blacklist_users:
            users_filtered[user] = users[user]

    return users_filtered


def generate_server_users(
    server: tuple[Literal["plex", "jellyfin", "emby"], Plex | Jellyfin | Emby],
    users: dict[str, str],
) -> list[MyPlexAccount] | dict[str, str] | None:
    if server[0] == "plex":
        plex_server_users: list[MyPlexAccount] = []
        for plex_user in server[1].users:
            username_title = (
                plex_user.username if plex_user.username else plex_user.title
            )

            if (
                username_title.lower() in users.keys()
                or username_title.lower() in users.values()
            ):
                plex_server_users.append(plex_user)

        return plex_server_users
    elif server[0] in ["jellyfin", "emby"]:
        jelly_emby_server_users: dict[str, str] = {}
        for jellyfin_user, jellyfin_id in server[1].users.items():
            if (
                jellyfin_user.lower() in users.keys()
                or jellyfin_user.lower() in users.values()
            ):
                jelly_emby_server_users[jellyfin_user] = jellyfin_id

        return jelly_emby_server_users

    return None


def setup_users(
    server_1: tuple[Literal["plex", "jellyfin", "emby"], Plex | Jellyfin | Emby],
    server_2: tuple[Literal["plex", "jellyfin", "emby"], Plex | Jellyfin | Emby],
    blacklist_users: list[str],
    whitelist_users: list[str],
    user_mapping: dict[str, str] | None = None,
) -> tuple[list[MyPlexAccount] | dict[str, str], list[MyPlexAccount] | dict[str, str]]:
    server_1_users = generate_user_list(server_1)
    server_2_users = generate_user_list(server_2)
    logger(f"Server 1 users: {server_1_users}", 1)
    logger(f"Server 2 users: {server_2_users}", 1)

    users = combine_user_lists(server_1_users, server_2_users, user_mapping)
    logger(f"User list that exist on both servers {users}", 1)

    users_filtered = filter_user_lists(users, blacklist_users, whitelist_users)
    logger(f"Filtered user list {users_filtered}", 1)

    output_server_1_users = generate_server_users(server_1, users_filtered)
    output_server_2_users = generate_server_users(server_2, users_filtered)

    # Check if users is none or empty
    if output_server_1_users is None or len(output_server_1_users) == 0:
        logger(
            f"No users found for server 1 {server_1[0]}, users: {server_1_users}, overlapping users {users}, filtered users {users_filtered}, server 1 users {server_1[1].users}"
        )

    if output_server_2_users is None or len(output_server_2_users) == 0:
        logger(
            f"No users found for server 2 {server_2[0]}, users: {server_2_users}, overlapping users {users} filtered users {users_filtered}, server 2 users {server_2[1].users}"
        )

    if (
        output_server_1_users is None
        or len(output_server_1_users) == 0
        or output_server_2_users is None
        or len(output_server_2_users) == 0
    ):
        raise Exception("No users found for one or both servers")

    logger(f"Server 1 users: {output_server_1_users}", 1)
    logger(f"Server 2 users: {output_server_2_users}", 1)

    return output_server_1_users, output_server_2_users
