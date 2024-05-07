import os, traceback, json
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
from src.emby import Emby

load_dotenv(override=True)


def setup_users(
    server_1, server_2, blacklist_users, whitelist_users, user_mapping=None
):
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


def jellyfin_emby_server_connection(server_baseurl, server_token, server_type):
    servers = []

    server_baseurl = server_baseurl.split(",")
    server_token = server_token.split(",")

    if len(server_baseurl) != len(server_token):
        raise Exception(
            f"{server_type.upper()}_BASEURL and {server_type.upper()}_TOKEN must have the same number of entries"
        )

    for i, baseurl in enumerate(server_baseurl):
        baseurl = baseurl.strip()
        if baseurl[-1] == "/":
            baseurl = baseurl[:-1]

        if server_type == "jellyfin":
            server = Jellyfin(baseurl=baseurl, token=server_token[i].strip())
            servers.append(
                (
                    "jellyfin",
                    server,
                )
            )

        elif server_type == "emby":
            server = Emby(baseurl=baseurl, token=server_token[i].strip())
            servers.append(
                (
                    "emby",
                    server,
                )
            )
        else:
            raise Exception("Unknown server type")

        logger(f"{server_type} Server {i} info: {server.info()}", 3)

    return servers


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
            server = Plex(
                baseurl=url.strip(),
                token=plex_token[i].strip(),
                username=None,
                password=None,
                servername=None,
                ssl_bypass=ssl_bypass,
            )

            logger(f"Plex Server {i} info: {server.info()}", 3)

            servers.append(
                (
                    "plex",
                    server,
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
            server = Plex(
                baseurl=None,
                token=None,
                username=username.strip(),
                password=plex_password[i].strip(),
                servername=plex_servername[i].strip(),
                ssl_bypass=ssl_bypass,
            )

            logger(f"Plex Server {i} info: {server.info()}", 3)
            servers.append(
                (
                    "plex",
                    server,
                )
            )

    jellyfin_baseurl = os.getenv("JELLYFIN_BASEURL", None)
    jellyfin_token = os.getenv("JELLYFIN_TOKEN", None)

    if jellyfin_baseurl and jellyfin_token:
        servers.extend(
            jellyfin_emby_server_connection(
                jellyfin_baseurl, jellyfin_token, "jellyfin"
            )
        )

    emby_baseurl = os.getenv("EMBY_BASEURL", None)
    emby_token = os.getenv("EMBY_TOKEN", None)

    if emby_baseurl and emby_token:
        servers.extend(
            jellyfin_emby_server_connection(emby_baseurl, emby_token, "emby")
        )

    return servers


def should_sync_server(server_1_type, server_2_type):
    sync_from_plex_to_jellyfin = str_to_bool(
        os.getenv("SYNC_FROM_PLEX_TO_JELLYFIN", "True")
    )
    sync_from_plex_to_plex = str_to_bool(os.getenv("SYNC_FROM_PLEX_TO_PLEX", "True"))
    sync_from_plex_to_emby = str_to_bool(os.getenv("SYNC_FROM_PLEX_TO_EMBY", "True"))

    sync_from_jelly_to_plex = str_to_bool(
        os.getenv("SYNC_FROM_JELLYFIN_TO_PLEX", "True")
    )
    sync_from_jelly_to_jellyfin = str_to_bool(
        os.getenv("SYNC_FROM_JELLYFIN_TO_JELLYFIN", "True")
    )
    sync_from_jelly_to_emby = str_to_bool(
        os.getenv("SYNC_FROM_JELLYFIN_TO_EMBY", "True")
    )

    sync_from_emby_to_plex = str_to_bool(os.getenv("SYNC_FROM_EMBY_TO_PLEX", "True"))
    sync_from_emby_to_jellyfin = str_to_bool(
        os.getenv("SYNC_FROM_EMBY_TO_JELLYFIN", "True")
    )
    sync_from_emby_to_emby = str_to_bool(os.getenv("SYNC_FROM_EMBY_TO_EMBY", "True"))

    if server_1_type == "plex":
        if server_2_type == "jellyfin" and not sync_from_plex_to_jellyfin:
            logger("Sync from plex -> jellyfin is disabled", 1)
            return False

        if server_2_type == "emby" and not sync_from_plex_to_emby:
            logger("Sync from plex -> emby is disabled", 1)
            return False

        if server_2_type == "plex" and not sync_from_plex_to_plex:
            logger("Sync from plex -> plex is disabled", 1)
            return False

    if server_1_type == "jellyfin":
        if server_2_type == "plex" and not sync_from_jelly_to_plex:
            logger("Sync from jellyfin -> plex is disabled", 1)
            return False

        if server_2_type == "jellyfin" and not sync_from_jelly_to_jellyfin:
            logger("Sync from jellyfin -> jellyfin is disabled", 1)
            return False

        if server_2_type == "emby" and not sync_from_jelly_to_emby:
            logger("Sync from jellyfin -> emby is disabled", 1)
            return False

    if server_1_type == "emby":
        if server_2_type == "plex" and not sync_from_emby_to_plex:
            logger("Sync from emby -> plex is disabled", 1)
            return False

        if server_2_type == "jellyfin" and not sync_from_emby_to_jellyfin:
            logger("Sync from emby -> jellyfin is disabled", 1)
            return False

        if server_2_type == "emby" and not sync_from_emby_to_emby:
            logger("Sync from emby -> emby is disabled", 1)
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
            # Check if server 1 and server 2 are going to be synced in either direction, skip if not
            if not should_sync_server(server_1[0], server_2[0]) and not should_sync_server(server_2[0], server_1[0]):
                continue

            logger(f"Server 1: {server_1[0].capitalize()}: {server_1[1].info()}", 0)
            logger(f"Server 2: {server_2[0].capitalize()}: {server_2[1].info()}", 0)

            # Create users list
            logger("Creating users list", 1)
            server_1_users, server_2_users = setup_users(
                server_1, server_2, blacklist_users, whitelist_users, user_mapping
            )

            logger("Creating watched lists", 1)
            server_1_watched = server_1[1].get_watched(
                server_1_users,
                blacklist_library,
                whitelist_library,
                blacklist_library_type,
                whitelist_library_type,
                library_mapping,
            )
            logger("Finished creating watched list server 1", 1)

            server_2_watched = server_2[1].get_watched(
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

            if should_sync_server(server_2[0], server_1[0]):
                logger(f"Syncing {server_2[1].info()} -> {server_1[1].info()}", 0)
                server_1[1].update_watched(
                    server_2_watched_filtered,
                    user_mapping,
                    library_mapping,
                    dryrun,
                )

            if should_sync_server(server_1[0], server_2[0]):
                logger(f"Syncing {server_1[1].info()} -> {server_2[1].info()}", 0)
                server_2[1].update_watched(
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
            if len(times) > 0:
                logger(f"Average time: {sum(times) / len(times)}", 0)
            logger("Exiting", log_type=0)
            os._exit(0)
