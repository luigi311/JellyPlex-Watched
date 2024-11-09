import os, traceback, json
from typing import Literal
from dotenv import load_dotenv
from time import sleep, perf_counter

from src.library import setup_libraries
from src.functions import (
    logger,
    parse_string_to_list,
    str_to_bool,
)
from src.users import setup_users
from src.watched import (
    cleanup_watched,
)
from src.black_white import setup_black_white_lists
from src.connection import generate_server_connections

load_dotenv(override=True)


def should_sync_server(
    server_1_type: Literal["plex", "jellyfin", "emby"],
    server_2_type: Literal["plex", "jellyfin", "emby"],
) -> bool:
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
    log_file = os.getenv("LOG_FILE", os.getenv("LOGFILE", "log.log"))
    # Delete log_file if it exists
    if os.path.exists(log_file):
        os.remove(log_file)

    dryrun = str_to_bool(os.getenv("DRYRUN", "False"))
    logger(f"Dryrun: {dryrun}", 1)

    user_mapping = os.getenv("USER_MAPPING", "")
    user_mapping = json.loads(user_mapping.lower())
    logger(f"User Mapping: {user_mapping}", 1)

    library_mapping = os.getenv("LIBRARY_MAPPING", "")
    library_mapping = json.loads(library_mapping)
    logger(f"Library Mapping: {library_mapping}", 1)

    # Create (black/white)lists
    logger("Creating (black/white)lists", 1)
    blacklist_library = parse_string_to_list(os.getenv("BLACKLIST_LIBRARY", None))
    whitelist_library = parse_string_to_list(os.getenv("WHITELIST_LIBRARY", None))
    blacklist_library_type = parse_string_to_list(
        os.getenv("BLACKLIST_LIBRARY_TYPE", None)
    )
    whitelist_library_type = parse_string_to_list(
        os.getenv("WHITELIST_LIBRARY_TYPE", None)
    )
    blacklist_users = parse_string_to_list(os.getenv("BLACKLIST_USERS", None))
    whitelist_users = parse_string_to_list(os.getenv("WHITELIST_USERS", None))

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
            if not should_sync_server(
                server_1[0], server_2[0]
            ) and not should_sync_server(server_2[0], server_1[0]):
                continue

            logger(f"Server 1: {server_1[0].capitalize()}: {server_1[1].info()}", 0)
            logger(f"Server 2: {server_2[0].capitalize()}: {server_2[1].info()}", 0)

            # Create users list
            logger("Creating users list", 1)
            server_1_users, server_2_users = setup_users(
                server_1, server_2, blacklist_users, whitelist_users, user_mapping
            )

            server_1_libraries, server_2_libraries = setup_libraries(
                server_1[1],
                server_2[1],
                blacklist_library,
                blacklist_library_type,
                whitelist_library,
                whitelist_library_type,
                library_mapping,
            )

            logger("Creating watched lists", 1)
            server_1_watched = server_1[1].get_watched(
                server_1_users, server_1_libraries
            )
            logger("Finished creating watched list server 1", 1)

            server_2_watched = server_2[1].get_watched(
                server_2_users, server_2_libraries
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
    times: list[float] = []
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
