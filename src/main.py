import os
import traceback
import json
import sys
from dotenv import dotenv_values
from time import sleep, perf_counter
from loguru import logger

from src.emby import Emby
from src.jellyfin import Jellyfin
from src.plex import Plex
from src.library import setup_libraries
from src.functions import (
    parse_string_to_list,
    str_to_bool,
    get_env_value,
)
from src.users import setup_users
from src.watched import (
    cleanup_watched,
    merge_server_watched,
)
from src.black_white import setup_black_white_lists
from src.connection import generate_server_connections


def configure_logger(log_file: str = "log.log", debug_level: str = "INFO") -> None:
    # Remove default logger to configure our own
    logger.remove()

    # Choose log level based on environment
    # If in debug mode with a "debug" level, use DEBUG; otherwise, default to INFO.

    if debug_level not in ["INFO", "DEBUG", "TRACE"]:
        logger.add(sys.stdout)
        raise Exception(
            f"Invalid DEBUG_LEVEL {debug_level}, please choose between INFO, DEBUG, TRACE"
        )

    # Add a sink for file logging and the console.
    logger.add(log_file, level=debug_level, mode="w")
    logger.add(sys.stdout, level=debug_level)


def should_sync_server(
    env,
    server_1: Plex | Jellyfin | Emby,
    server_2: Plex | Jellyfin | Emby,
) -> bool:
    sync_from_plex_to_jellyfin = str_to_bool(
        get_env_value(env, "SYNC_FROM_PLEX_TO_JELLYFIN", "True")
    )
    sync_from_plex_to_plex = str_to_bool(
        get_env_value(env, "SYNC_FROM_PLEX_TO_PLEX", "True")
    )
    sync_from_plex_to_emby = str_to_bool(
        get_env_value(env, "SYNC_FROM_PLEX_TO_EMBY", "True")
    )

    sync_from_jelly_to_plex = str_to_bool(
        get_env_value(env, "SYNC_FROM_JELLYFIN_TO_PLEX", "True")
    )
    sync_from_jelly_to_jellyfin = str_to_bool(
        get_env_value(env, "SYNC_FROM_JELLYFIN_TO_JELLYFIN", "True")
    )
    sync_from_jelly_to_emby = str_to_bool(
        get_env_value(env, "SYNC_FROM_JELLYFIN_TO_EMBY", "True")
    )

    sync_from_emby_to_plex = str_to_bool(
        get_env_value(env, "SYNC_FROM_EMBY_TO_PLEX", "True")
    )
    sync_from_emby_to_jellyfin = str_to_bool(
        get_env_value(env, "SYNC_FROM_EMBY_TO_JELLYFIN", "True")
    )
    sync_from_emby_to_emby = str_to_bool(
        get_env_value(env, "SYNC_FROM_EMBY_TO_EMBY", "True")
    )

    if isinstance(server_1, Plex):
        if isinstance(server_2, Jellyfin) and not sync_from_plex_to_jellyfin:
            logger.info("Sync from plex -> jellyfin is disabled")
            return False

        if isinstance(server_2, Emby) and not sync_from_plex_to_emby:
            logger.info("Sync from plex -> emby is disabled")
            return False

        if isinstance(server_2, Plex) and not sync_from_plex_to_plex:
            logger.info("Sync from plex -> plex is disabled")
            return False

    if isinstance(server_1, Jellyfin):
        if isinstance(server_2, Plex) and not sync_from_jelly_to_plex:
            logger.info("Sync from jellyfin -> plex is disabled")
            return False

        if isinstance(server_2, Jellyfin) and not sync_from_jelly_to_jellyfin:
            logger.info("Sync from jellyfin -> jellyfin is disabled")
            return False

        if isinstance(server_2, Emby) and not sync_from_jelly_to_emby:
            logger.info("Sync from jellyfin -> emby is disabled")
            return False

    if isinstance(server_1, Emby):
        if isinstance(server_2, Plex) and not sync_from_emby_to_plex:
            logger.info("Sync from emby -> plex is disabled")
            return False

        if isinstance(server_2, Jellyfin) and not sync_from_emby_to_jellyfin:
            logger.info("Sync from emby -> jellyfin is disabled")
            return False

        if isinstance(server_2, Emby) and not sync_from_emby_to_emby:
            logger.info("Sync from emby -> emby is disabled")
            return False

    return True


def main_loop(env: dict[str, str | float | None]) -> None:
    dryrun = str_to_bool(get_env_value(env, "DRYRUN", "False"))
    logger.info(f"Dryrun: {dryrun}")

    user_mapping_env = get_env_value(env, "USER_MAPPING", None)
    user_mapping = None
    if user_mapping_env:
        user_mapping = json.loads(user_mapping_env.lower())
    logger.info(f"User Mapping: {user_mapping}")

    library_mapping_env = get_env_value(env, "LIBRARY_MAPPING", None)
    library_mapping = None
    if library_mapping_env:
        library_mapping = json.loads(library_mapping_env)
    logger.info(f"Library Mapping: {library_mapping}")

    # Create (black/white)lists
    logger.info("Creating (black/white)lists")
    blacklist_library = parse_string_to_list(
        get_env_value(env, "BLACKLIST_LIBRARY", None)
    )
    whitelist_library = parse_string_to_list(
        get_env_value(env, "WHITELIST_LIBRARY", None)
    )
    blacklist_library_type = parse_string_to_list(
        get_env_value(env, "BLACKLIST_LIBRARY_TYPE", None)
    )
    whitelist_library_type = parse_string_to_list(
        get_env_value(env, "WHITELIST_LIBRARY_TYPE", None)
    )
    blacklist_users = parse_string_to_list(get_env_value(env, "BLACKLIST_USERS", None))
    whitelist_users = parse_string_to_list(get_env_value(env, "WHITELIST_USERS", None))

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
    logger.info("Creating server connections")
    servers = generate_server_connections(env)

    for server_1 in servers:
        # If server is the final server in the list, then we are done with the loop
        if server_1 == servers[-1]:
            break

        # Store a copy of server_1_watched that way it can be used multiple times without having to regather everyones watch history every single time
        server_1_watched = None

        # Start server_2 at the next server in the list
        for server_2 in servers[servers.index(server_1) + 1 :]:
            # Check if server 1 and server 2 are going to be synced in either direction, skip if not
            if not should_sync_server(
                env, server_1, server_2
            ) and not should_sync_server(env, server_2, server_1):
                continue

            logger.info(f"Server 1: {type(server_1)}: {server_1.info()}")
            logger.info(f"Server 2: {type(server_2)}: {server_2.info()}")

            # Create users list
            logger.info("Creating users list")
            server_1_users, server_2_users = setup_users(
                server_1, server_2, blacklist_users, whitelist_users, user_mapping
            )

            server_1_libraries, server_2_libraries = setup_libraries(
                server_1,
                server_2,
                blacklist_library,
                blacklist_library_type,
                whitelist_library,
                whitelist_library_type,
                library_mapping,
            )
            logger.info(f"Server 1 syncing libraries: {server_1_libraries}")
            logger.info(f"Server 2 syncing libraries: {server_2_libraries}")

            logger.info("Creating watched lists", 1)
            server_1_watched = server_1.get_watched(
                server_1_users, server_1_libraries, server_1_watched
            )
            logger.info("Finished creating watched list server 1")

            server_2_watched = server_2.get_watched(server_2_users, server_2_libraries)
            logger.info("Finished creating watched list server 2")

            logger.trace(f"Server 1 watched: {server_1_watched}")
            logger.trace(f"Server 2 watched: {server_2_watched}")

            logger.info("Cleaning Server 1 Watched", 1)
            server_1_watched_filtered = cleanup_watched(
                server_1_watched,
                server_2_watched,
                env,
                user_mapping,
                library_mapping,
            )

            logger.info("Cleaning Server 2 Watched", 1)
            server_2_watched_filtered = cleanup_watched(
                server_2_watched,
                server_1_watched,
                env,
                user_mapping,
                library_mapping,
            )

            logger.debug(
                f"server 1 watched that needs to be synced to server 2:\n{server_1_watched_filtered}",
            )
            logger.debug(
                f"server 2 watched that needs to be synced to server 1:\n{server_2_watched_filtered}",
            )

            if should_sync_server(env, server_2, server_1):
                logger.info(f"Syncing {server_2.info()} -> {server_1.info()}")

                # Add server_2_watched_filtered to server_1_watched that way the stored version isn't stale for the next server
                if not dryrun:
                    server_1_watched = merge_server_watched(
                        server_1_watched,
                        server_2_watched_filtered,
                        env,
                        user_mapping,
                        library_mapping,
                    )

                server_1.update_watched(
                    server_2_watched_filtered,
                    user_mapping,
                    library_mapping,
                    dryrun,
                )

            if should_sync_server(env, server_1, server_2):
                logger.info(f"Syncing {server_1.info()} -> {server_2.info()}")
                server_2.update_watched(
                    server_1_watched_filtered,
                    user_mapping,
                    library_mapping,
                    dryrun,
                )


@logger.catch
def main() -> None:
    # Get environment variables
    env_file = get_env_value(None, "ENV_FILE", ".env")
    env = dotenv_values(env_file)

    run_only_once = str_to_bool(get_env_value(env, "RUN_ONLY_ONCE", "False"))
    sleep_duration = float(get_env_value(env, "SLEEP_DURATION", "3600"))
    log_file = get_env_value(env, "LOG_FILE", "log.log")
    debug_level = get_env_value(env, "DEBUG_LEVEL", "INFO")
    if debug_level:
        debug_level = debug_level.upper()

    times: list[float] = []
    while True:
        try:
            start = perf_counter()
            # Reconfigure the logger on each loop so the logs are rotated on each run
            configure_logger(log_file, debug_level)
            main_loop(env)
            end = perf_counter()
            times.append(end - start)

            if len(times) > 0:
                average_time = sum(times) / len(times)
                logger.info(f"Average time: {average_time}")
                env["AVERAGE_TIME"] = average_time

            if run_only_once:
                break

            logger.info(f"Looping in {sleep_duration}")
            sleep(sleep_duration)

        except Exception as error:
            if isinstance(error, list):
                for message in error:
                    logger.error(message)
            else:
                logger.error(error)

            logger.error(traceback.format_exc())

            if run_only_once:
                break

            logger.info(f"Retrying in {sleep_duration}")
            sleep(sleep_duration)

        except KeyboardInterrupt:
            if len(times) > 0:
                logger.info(f"Average time: {sum(times) / len(times)}")
            logger.info("Exiting")
            os._exit(0)
