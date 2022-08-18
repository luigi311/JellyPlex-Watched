import copy, os, traceback, json, asyncio
from dotenv import load_dotenv
from time import sleep, perf_counter

from src.functions import (
    logger,
    str_to_bool,
    search_mapping,
    generate_library_guids_dict,
)
from src.plex import Plex
from src.jellyfin import Jellyfin

load_dotenv(override=True)


def cleanup_watched(
    watched_list_1, watched_list_2, user_mapping=None, library_mapping=None
):
    modified_watched_list_1 = copy.deepcopy(watched_list_1)

    # remove entries from plex_watched that are in jellyfin_watched
    for user_1 in watched_list_1:
        user_other = None
        if user_mapping:
            user_other = search_mapping(user_mapping, user_1)
        if user_1 in modified_watched_list_1:
            if user_1 in watched_list_2:
                user_2 = user_1
            elif user_other in watched_list_2:
                user_2 = user_other
            else:
                logger(f"User {user_1} and {user_other} not found in watched list 2", 1)
                continue

            for library_1 in watched_list_1[user_1]:
                library_other = None
                if library_mapping:
                    library_other = search_mapping(library_mapping, library_1)
                if library_1 in modified_watched_list_1[user_1]:
                    if library_1 in watched_list_2[user_2]:
                        library_2 = library_1
                    elif library_other in watched_list_2[user_2]:
                        library_2 = library_other
                    else:
                        logger(
                            f"library {library_1} and {library_other} not found in watched list 2",
                            1,
                        )
                        continue

                    (
                        _,
                        episode_watched_list_2_keys_dict,
                        movies_watched_list_2_keys_dict,
                    ) = generate_library_guids_dict(watched_list_2[user_2][library_2])

                    # Movies
                    if isinstance(watched_list_1[user_1][library_1], list):
                        for movie in watched_list_1[user_1][library_1]:
                            movie_found = False
                            for movie_key, movie_value in movie.items():
                                if movie_key == "locations":
                                    if (
                                        "locations"
                                        in movies_watched_list_2_keys_dict.keys()
                                    ):
                                        for location in movie_value:
                                            if (
                                                location
                                                in movies_watched_list_2_keys_dict[
                                                    "locations"
                                                ]
                                            ):
                                                movie_found = True
                                                break
                                else:
                                    if (
                                        movie_key
                                        in movies_watched_list_2_keys_dict.keys()
                                    ):
                                        if (
                                            movie_value
                                            in movies_watched_list_2_keys_dict[
                                                movie_key
                                            ]
                                        ):
                                            movie_found = True

                                if movie_found:
                                    logger(f"Removing {movie} from {library_1}", 3)
                                    modified_watched_list_1[user_1][library_1].remove(
                                        movie
                                    )
                                    break

                    # TV Shows
                    elif isinstance(watched_list_1[user_1][library_1], dict):
                        # Generate full list of provider ids for episodes in watch_list_2 to easily compare if they exist in watch_list_1

                        for show_key_1 in watched_list_1[user_1][library_1].keys():
                            show_key_dict = dict(show_key_1)
                            for season in watched_list_1[user_1][library_1][show_key_1]:
                                for episode in watched_list_1[user_1][library_1][
                                    show_key_1
                                ][season]:
                                    episode_found = False
                                    for episode_key, episode_value in episode.items():
                                        # If episode_key and episode_value are in episode_watched_list_2_keys_dict exactly, then remove from watch_list_1
                                        if episode_key == "locations":
                                            if (
                                                "locations"
                                                in episode_watched_list_2_keys_dict.keys()
                                            ):
                                                for location in episode_value:
                                                    if (
                                                        location
                                                        in episode_watched_list_2_keys_dict[
                                                            "locations"
                                                        ]
                                                    ):
                                                        episode_found = True
                                                        break

                                        else:
                                            if (
                                                episode_key
                                                in episode_watched_list_2_keys_dict.keys()
                                            ):
                                                if (
                                                    episode_value
                                                    in episode_watched_list_2_keys_dict[
                                                        episode_key
                                                    ]
                                                ):
                                                    episode_found = True

                                        if episode_found:
                                            if (
                                                episode
                                                in modified_watched_list_1[user_1][
                                                    library_1
                                                ][show_key_1][season]
                                            ):
                                                logger(
                                                    f"Removing {episode} from {show_key_dict['title']}",
                                                    3,
                                                )
                                                modified_watched_list_1[user_1][
                                                    library_1
                                                ][show_key_1][season].remove(episode)
                                                break

                                # Remove empty seasons
                                if (
                                    len(
                                        modified_watched_list_1[user_1][library_1][
                                            show_key_1
                                        ][season]
                                    )
                                    == 0
                                ):
                                    if (
                                        season
                                        in modified_watched_list_1[user_1][library_1][
                                            show_key_1
                                        ]
                                    ):
                                        logger(
                                            f"Removing {season} from {show_key_dict['title']} because it is empty",
                                            3,
                                        )
                                        del modified_watched_list_1[user_1][library_1][
                                            show_key_1
                                        ][season]

                            # If the show is empty, remove the show
                            if (
                                len(
                                    modified_watched_list_1[user_1][library_1][
                                        show_key_1
                                    ]
                                )
                                == 0
                            ):
                                if (
                                    show_key_1
                                    in modified_watched_list_1[user_1][library_1]
                                ):
                                    logger(
                                        f"Removing {show_key_dict['title']} from {library_1} because it is empty",
                                        1,
                                    )
                                    del modified_watched_list_1[user_1][library_1][
                                        show_key_1
                                    ]

    for user_1 in watched_list_1:
        for library_1 in watched_list_1[user_1]:
            if library_1 in modified_watched_list_1[user_1]:
                # If library is empty then remove it
                if len(modified_watched_list_1[user_1][library_1]) == 0:
                    logger(f"Removing {library_1} from {user_1} because it is empty", 1)
                    del modified_watched_list_1[user_1][library_1]

        if user_1 in modified_watched_list_1:
            # If user is empty delete user
            if len(modified_watched_list_1[user_1]) == 0:
                logger(f"Removing {user_1} from watched list 1 because it is empty", 1)
                del modified_watched_list_1[user_1]

    return modified_watched_list_1


def setup_black_white_lists(
    blacklist_library: str,
    whitelist_library: str,
    blacklist_library_type: str,
    whitelist_library_type: str,
    blacklist_users: str,
    whitelist_users: str,
    library_mapping=None,
    user_mapping=None,
):
    if blacklist_library:
        if len(blacklist_library) > 0:
            blacklist_library = blacklist_library.split(",")
            blacklist_library = [x.strip() for x in blacklist_library]
            if library_mapping:
                temp_library = []
                for library in blacklist_library:
                    library_other = search_mapping(library_mapping, library)
                    if library_other:
                        temp_library.append(library_other)

                blacklist_library = blacklist_library + temp_library
    else:
        blacklist_library = []
    logger(f"Blacklist Library: {blacklist_library}", 1)

    if whitelist_library:
        if len(whitelist_library) > 0:
            whitelist_library = whitelist_library.split(",")
            whitelist_library = [x.strip() for x in whitelist_library]
            if library_mapping:
                temp_library = []
                for library in whitelist_library:
                    library_other = search_mapping(library_mapping, library)
                    if library_other:
                        temp_library.append(library_other)

                whitelist_library = whitelist_library + temp_library
    else:
        whitelist_library = []
    logger(f"Whitelist Library: {whitelist_library}", 1)

    if blacklist_library_type:
        if len(blacklist_library_type) > 0:
            blacklist_library_type = blacklist_library_type.split(",")
            blacklist_library_type = [x.lower().strip() for x in blacklist_library_type]
    else:
        blacklist_library_type = []
    logger(f"Blacklist Library Type: {blacklist_library_type}", 1)

    if whitelist_library_type:
        if len(whitelist_library_type) > 0:
            whitelist_library_type = whitelist_library_type.split(",")
            whitelist_library_type = [x.lower().strip() for x in whitelist_library_type]
    else:
        whitelist_library_type = []
    logger(f"Whitelist Library Type: {whitelist_library_type}", 1)

    if blacklist_users:
        if len(blacklist_users) > 0:
            blacklist_users = blacklist_users.split(",")
            blacklist_users = [x.lower().strip() for x in blacklist_users]
            if user_mapping:
                temp_users = []
                for user in blacklist_users:
                    user_other = search_mapping(user_mapping, user)
                    if user_other:
                        temp_users.append(user_other)

                blacklist_users = blacklist_users + temp_users
    else:
        blacklist_users = []
    logger(f"Blacklist Users: {blacklist_users}", 1)

    if whitelist_users:
        if len(whitelist_users) > 0:
            whitelist_users = whitelist_users.split(",")
            whitelist_users = [x.lower().strip() for x in whitelist_users]
            if user_mapping:
                temp_users = []
                for user in whitelist_users:
                    user_other = search_mapping(user_mapping, user)
                    if user_other:
                        temp_users.append(user_other)

                whitelist_users = whitelist_users + temp_users
        else:
            whitelist_users = []
    else:
        whitelist_users = []
    logger(f"Whitelist Users: {whitelist_users}", 1)

    return (
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        blacklist_users,
        whitelist_users,
    )


def setup_users(
    server_1, server_2, blacklist_users, whitelist_users, user_mapping=None
):

    # generate list of users from server 1 and server 2
    server_1_type = server_1[0]
    server_1_connection = server_1[1]
    server_2_type = server_2[0]
    server_2_connection = server_2[1]
    print(f"Server 1: {server_1_type} {server_1_connection}")
    print(f"Server 2: {server_2_type} {server_2_connection}")

    server_1_users = []
    if server_1_type == "plex":
        server_1_users = [x.title.lower() for x in server_1_connection.users]
    elif server_1_type == "jellyfin":
        server_1_users = [key.lower() for key in server_1_connection.users.keys()]

    server_2_users = []
    if server_2_type == "plex":
        server_2_users = [x.title.lower() for x in server_2_connection.users]
    elif server_2_type == "jellyfin":
        server_2_users = [key.lower() for key in server_2_connection.users.keys()]

    # combined list of overlapping users from plex and jellyfin
    users = {}

    for server_1_user in server_1_users:
        if user_mapping:
            jellyfin_plex_mapped_user = search_mapping(user_mapping, server_1_user)
            if jellyfin_plex_mapped_user:
                users[server_1_user] = jellyfin_plex_mapped_user
                continue

        if server_1_user in server_2_users:
            users[server_1_user] = server_1_user

    for server_2_user in server_2_users:
        if user_mapping:
            plex_jellyfin_mapped_user = search_mapping(user_mapping, server_2_user)
            if plex_jellyfin_mapped_user:
                users[plex_jellyfin_mapped_user] = server_2_user
                continue

        if server_2_user in server_1_users:
            users[server_2_user] = server_2_user

    logger(f"User list that exist on both servers {users}", 1)

    users_filtered = {}
    for user in users:
        # whitelist_user is not empty and user lowercase is not in whitelist lowercase
        if len(whitelist_users) > 0:
            if user not in whitelist_users and users[user] not in whitelist_users:
                logger(f"{user} or {users[user]} is not in whitelist", 1)
                continue

        if user not in blacklist_users and users[user] not in blacklist_users:
            users_filtered[user] = users[user]

    logger(f"Filtered user list {users_filtered}", 1)

    if server_1_type == "plex":
        output_server_1_users = []
        for plex_user in server_1_connection.users:
            if (
                plex_user.title.lower() in users_filtered.keys()
                or plex_user.title.lower() in users_filtered.values()
            ):
                output_server_1_users.append(plex_user)
    elif server_1_type == "jellyfin":
        output_server_1_users = {}
        for jellyfin_user, jellyfin_id in server_1_connection.users.items():
            if (
                jellyfin_user.lower() in users_filtered.keys()
                or jellyfin_user.lower() in users_filtered.values()
            ):
                output_server_1_users[jellyfin_user] = jellyfin_id

    if server_2_type == "plex":
        output_server_2_users = []
        for plex_user in server_2_connection.users:
            if (
                plex_user.title.lower() in users_filtered.keys()
                or plex_user.title.lower() in users_filtered.values()
            ):
                output_server_2_users.append(plex_user)
    elif server_2_type == "jellyfin":
        output_server_2_users = {}
        for jellyfin_user, jellyfin_id in server_2_connection.users.items():
            if (
                jellyfin_user.lower() in users_filtered.keys()
                or jellyfin_user.lower() in users_filtered.values()
            ):
                output_server_2_users[jellyfin_user] = jellyfin_id

    if len(output_server_1_users) == 0:
        raise Exception(
            f"No users found for server 1, users found {users} filtered users {users_filtered}"
        )

    if len(output_server_2_users) == 0:
        raise Exception(
            f"No users found for server 2, users found {users} filtered users {users_filtered}"
        )

    logger(f"Server 1 users: {output_server_1_users}", 1)
    logger(f"Server 2 users: {output_server_2_users}", 1)

    return output_server_1_users, output_server_2_users


def generate_server_connections():
    servers = []

    plex_baseurl = os.getenv("PLEX_BASEURL", None)
    plex_token = os.getenv("PLEX_TOKEN", None)
    plex_username = os.getenv("PLEX_USERNAME", None)
    plex_password = os.getenv("PLEX_PASSWORD", None)
    plex_servername = os.getenv("PLEX_SERVERNAME", None)
    ssl_bypass = str_to_bool(os.getenv("SSL_BYPASS", "False"))

    if plex_baseurl and plex_token:
        plex_baseurl = plex_baseurl.split(",")
        plex_token = plex_token.split(",")

        if len(plex_baseurl) != len(plex_token):
            raise Exception(
                "PLEX_BASEURL and PLEX_TOKEN must have the same number of entries"
            )

        for i, url in enumerate(plex_baseurl):
            servers.append(
                (
                    "plex",
                    Plex(
                        baseurl=url.strip(),
                        token=plex_token[i].strip(),
                        username=None,
                        password=None,
                        servername=None,
                        ssl_bypass=ssl_bypass,
                    ),
                )
            )

    if plex_username and plex_password and plex_servername:
        plex_username = plex_username.split(",")
        plex_password = plex_password.split(",")
        plex_servername = plex_servername.split(",")

        if len(plex_username) != len(plex_password) or len(plex_username) != len(
            plex_servername
        ):
            raise Exception(
                "PLEX_USERNAME, PLEX_PASSWORD and PLEX_SERVERNAME must have the same number of entries"
            )

        for i, username in enumerate(plex_username):
            servers.append(
                (
                    "plex",
                    Plex(
                        baseurl=None,
                        token=None,
                        username=username.strip(),
                        password=plex_password[i].strip(),
                        servername=plex_servername[i].strip(),
                        ssl_bypass=ssl_bypass,
                    ),
                )
            )

    jellyfin_baseurl = os.getenv("JELLYFIN_BASEURL", None)
    jellyfin_token = os.getenv("JELLYFIN_TOKEN", None)

    if jellyfin_baseurl and jellyfin_token:
        jellyfin_baseurl = jellyfin_baseurl.split(",")
        jellyfin_token = jellyfin_token.split(",")

        if len(jellyfin_baseurl) != len(jellyfin_token):
            raise Exception(
                "JELLYFIN_BASEURL and JELLYFIN_TOKEN must have the same number of entries"
            )

        for i, baseurl in enumerate(jellyfin_baseurl):
            servers.append(
                (
                    "jellyfin",
                    Jellyfin(baseurl=baseurl.strip(), token=jellyfin_token[i].strip()),
                )
            )

    return servers


def main_loop():
    logfile = os.getenv("LOGFILE", "log.log")
    # Delete logfile if it exists
    if os.path.exists(logfile):
        os.remove(logfile)

    dryrun = str_to_bool(os.getenv("DRYRUN", "False"))
    logger(f"Dryrun: {dryrun}", 1)

    user_mapping = os.getenv("USER_MAPPING")
    if user_mapping:
        user_mapping = json.loads(user_mapping.lower())
        logger(f"User Mapping: {user_mapping}", 1)

    library_mapping = os.getenv("LIBRARY_MAPPING")
    if library_mapping:
        library_mapping = json.loads(library_mapping)
        logger(f"Library Mapping: {library_mapping}", 1)

    # Create (black/white)lists
    logger("Creating (black/white)lists", 1)
    blacklist_library = os.getenv("BLACKLIST_LIBRARY", None)
    whitelist_library = os.getenv("WHITELIST_LIBRARY", None)
    blacklist_library_type = os.getenv("BLACKLIST_LIBRARY_TYPE", None)
    whitelist_library_type = os.getenv("WHITELIST_LIBRARY_TYPE", None)
    blacklist_users = os.getenv("BLACKLIST_USERS", None)
    whitelist_users = os.getenv("WHITELIST_USERS", None)

    (
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        blacklist_users,
        whitelist_users,
    ) = setup_black_white_lists(
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        blacklist_users,
        whitelist_users,
        library_mapping,
        user_mapping,
    )

    # Create server connections
    logger("Creating server connections", 1)
    servers = generate_server_connections()

    for server_1 in servers:
        # If server is the final server in the list, then we are done with the loop
        if server_1 == servers[-1]:
            break

        # Start server_2 at the next server in the list
        for server_2 in servers[servers.index(server_1) + 1 :]:

            server_1_connection = server_1[1]
            server_2_connection = server_2[1]

            # Create users list
            logger("Creating users list", 1)
            server_1_users, server_2_users = setup_users(
                server_1, server_2, blacklist_users, whitelist_users, user_mapping
            )

            logger("Creating watched lists", 1)
            server_1_watched = server_1_connection.get_watched(
                server_1_users,
                blacklist_library,
                whitelist_library,
                blacklist_library_type,
                whitelist_library_type,
                library_mapping,
            )
            logger("Finished creating watched list server 1", 1)
            server_2_watched = asyncio.run(
                server_2_connection.get_watched(
                    server_2_users,
                    blacklist_library,
                    whitelist_library,
                    blacklist_library_type,
                    whitelist_library_type,
                    library_mapping,
                )
            )
            logger("Finished creating watched list server 2", 1)
            logger(f"Server 1 watched: {server_1_watched}", 3)
            logger(f"Server 2 watched: {server_2_watched}", 3)

            logger("Cleaning Server 1 Watched", 1)
            server_1_watched_filtered = cleanup_watched(
                server_1_watched, server_2_watched, user_mapping, library_mapping
            )

            logger("Cleaning Server 2 Watched", 1)
            server_2_watched_filtered = cleanup_watched(
                server_2_watched, server_1_watched, user_mapping, library_mapping
            )

            logger(
                f"server 1 watched that needs to be synced to server 2:\n{server_1_watched_filtered}",
                1,
            )
            logger(
                f"server 2 watched that needs to be synced to server 1:\n{server_2_watched_filtered}",
                1,
            )

            server_1_connection.update_watched(
                server_2_watched_filtered, user_mapping, library_mapping, dryrun
            )
            asyncio.run(
                server_2_connection.update_watched(
                    server_1_watched_filtered, user_mapping, library_mapping, dryrun
                )
            )


def main():
    sleep_duration = float(os.getenv("SLEEP_DURATION", "3600"))
    times = []
    while True:
        try:
            start = perf_counter()
            main_loop()
            end = perf_counter()
            times.append(end - start)

            if len(times) > 0:
                logger(f"Average time: {sum(times) / len(times)}", 0)

            logger(f"Looping in {sleep_duration}")
            sleep(sleep_duration)

        except Exception as error:
            if isinstance(error, list):
                for message in error:
                    logger(message, log_type=2)
            else:
                logger(error, log_type=2)

            logger(traceback.format_exc(), 2)
            logger(f"Retrying in {sleep_duration}", log_type=0)
            sleep(sleep_duration)

        except KeyboardInterrupt:
            logger("Exiting", log_type=0)
            os._exit(0)
