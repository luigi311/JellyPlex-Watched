import os, traceback, json, asyncio
from dotenv import load_dotenv
from time import sleep, perf_counter

from src.functions import (
    logger,
    str_to_bool,
)
from src.users import (
    generate_user_list,
    combine_user_lists,
    filter_user_lists,
    generate_server_users,
)
from src.watched import (
    cleanup_watched,
)
from src.black_white import setup_black_white_lists

from src.plex import Plex
from src.jellyfin import Jellyfin

load_dotenv(override=True)


def setup_users(
    server_1, server_2, blacklist_users, whitelist_users, user_mapping=None
):
    server_1_users = generate_user_list(server_1)
    server_2_users = generate_user_list(server_2)

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
            baseurl = baseurl.strip()
            if baseurl[-1] == "/":
                baseurl = baseurl[:-1]
            servers.append(
                (
                    "jellyfin",
                    Jellyfin(baseurl=baseurl, token=jellyfin_token[i].strip()),
                )
            )

    return servers


def get_server_watched(
    server_connection: list,
    users: dict,
    blacklist_library: list,
    whitelist_library: list,
    blacklist_library_type: list,
    whitelist_library_type: list,
    library_mapping: dict,
):
    if server_connection[0] == "plex":
        return server_connection[1].get_watched(
            users,
            blacklist_library,
            whitelist_library,
            blacklist_library_type,
            whitelist_library_type,
            library_mapping,
        )
    elif server_connection[0] == "jellyfin":
        return asyncio.run(
            server_connection[1].get_watched(
                users,
                blacklist_library,
                whitelist_library,
                blacklist_library_type,
                whitelist_library_type,
                library_mapping,
            )
        )


def update_server_watched(
    server_connection: list,
    server_watched_filtered: dict,
    user_mapping: dict,
    library_mapping: dict,
    dryrun: bool,
):
    if server_connection[0] == "plex":
        server_connection[1].update_watched(
            server_watched_filtered, user_mapping, library_mapping, dryrun
        )
    elif server_connection[0] == "jellyfin":
        asyncio.run(
            server_connection[1].update_watched(
                server_watched_filtered, user_mapping, library_mapping, dryrun
            )
        )


def should_sync_server(server_1_type, server_2_type):
    sync_from_plex_to_jellyfin = str_to_bool(
        os.getenv("SYNC_FROM_PLEX_TO_JELLYFIN", "True")
    )
    sync_from_jelly_to_plex = str_to_bool(
        os.getenv("SYNC_FROM_JELLYFIN_TO_PLEX", "True")
    )
    sync_from_plex_to_plex = str_to_bool(os.getenv("SYNC_FROM_PLEX_TO_PLEX", "True"))
    sync_from_jelly_to_jellyfin = str_to_bool(
        os.getenv("SYNC_FROM_JELLYFIN_TO_JELLYFIN", "True")
    )

    if (
        server_1_type == "plex"
        and server_2_type == "plex"
        and not sync_from_plex_to_plex
    ):
        logger("Sync between plex and plex is disabled", 1)
        return False

    if (
        server_1_type == "plex"
        and server_2_type == "jellyfin"
        and not sync_from_jelly_to_plex
    ):
        logger("Sync from jellyfin to plex disabled", 1)
        return False

    if (
        server_1_type == "jellyfin"
        and server_2_type == "jellyfin"
        and not sync_from_jelly_to_jellyfin
    ):
        logger("Sync between jellyfin and jellyfin is disabled", 1)
        return False

    if (
        server_1_type == "jellyfin"
        and server_2_type == "plex"
        and not sync_from_plex_to_jellyfin
    ):
        logger("Sync from plex to jellyfin is disabled", 1)
        return False

    return True


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
            logger(f"Server 1: {server_1[0].capitalize()}: {server_1[1].info()}", 0)
            logger(f"Server 2: {server_2[0].capitalize()}: {server_2[1].info()}", 0)

            # Create users list
            logger("Creating users list", 1)
            server_1_users, server_2_users = setup_users(
                server_1, server_2, blacklist_users, whitelist_users, user_mapping
            )

            logger("Creating watched lists", 1)
            server_1_watched = get_server_watched(
                server_1,
                server_1_users,
                blacklist_library,
                whitelist_library,
                blacklist_library_type,
                whitelist_library_type,
                library_mapping,
            )
            logger("Finished creating watched list server 1", 1)
            server_2_watched = get_server_watched(
                server_2,
                server_2_users,
                blacklist_library,
                whitelist_library,
                blacklist_library_type,
                whitelist_library_type,
                library_mapping,
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

            if should_sync_server(server_1[0], server_2[0]):
                update_server_watched(
                    server_1,
                    server_2_watched_filtered,
                    user_mapping,
                    library_mapping,
                    dryrun,
                )

            if should_sync_server(server_2[0], server_1[0]):
                update_server_watched(
                    server_2,
                    server_1_watched_filtered,
                    user_mapping,
                    library_mapping,
                    dryrun,
                )


def main():
    run_only_once = str_to_bool(os.getenv("RUN_ONLY_ONCE", "False"))
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

            if run_only_once:
                break

            logger(f"Looping in {sleep_duration}")
            sleep(sleep_duration)

        except Exception as error:
            if isinstance(error, list):
                for message in error:
                    logger(message, log_type=2)
            else:
                logger(error, log_type=2)

            logger(traceback.format_exc(), 2)

            if run_only_once:
                break

            logger(f"Retrying in {sleep_duration}", log_type=0)
            sleep(sleep_duration)

        except KeyboardInterrupt:
            logger("Exiting", log_type=0)
            os._exit(0)
