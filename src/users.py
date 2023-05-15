from src.functions import (
    logger,
    search_mapping,
)


def generate_user_list(server):
    # generate list of users from server 1 and server 2
    server_type = server[0]
    server_connection = server[1]

    server_users = []
    if server_type == "plex":
        for user in server_connection.users:
            if user.username:
                server_users.append(user.username.lower())
            else:
                server_users.append(user.title.lower())

    elif server_type == "jellyfin":
        server_users = [key.lower() for key in server_connection.users.keys()]

    return server_users


def combine_user_lists(server_1_users, server_2_users, user_mapping):
    # combined list of overlapping users from plex and jellyfin
    users = {}

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


def filter_user_lists(users, blacklist_users, whitelist_users):
    users_filtered = {}
    for user in users:
        # whitelist_user is not empty and user lowercase is not in whitelist lowercase
        if len(whitelist_users) > 0:
            if user not in whitelist_users and users[user] not in whitelist_users:
                logger(f"{user} or {users[user]} is not in whitelist", 1)
                continue

        if user not in blacklist_users and users[user] not in blacklist_users:
            users_filtered[user] = users[user]

    return users_filtered


def generate_server_users(server, users):
    server_users = None

    if server[0] == "plex":
        server_users = []
        for plex_user in server[1].users:
            if (
                plex_user.title.lower() in users.keys()
                or plex_user.title.lower() in users.values()
            ):
                server_users.append(plex_user)
    elif server[0] == "jellyfin":
        server_users = {}
        for jellyfin_user, jellyfin_id in server[1].users.items():
            if (
                jellyfin_user.lower() in users.keys()
                or jellyfin_user.lower() in users.values()
            ):
                server_users[jellyfin_user] = jellyfin_id

    return server_users
