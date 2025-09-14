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
from src.watched import sync_watched_lists
from src.black_white import setup_black_white_lists
from src.connection import generate_server_connections


def configure_logger(log_file: str = "log.log", debug_level: str = "INFO") -> None:
    logger.remove()
    if debug_level not in ["INFO", "DEBUG", "TRACE"]:
        logger.add(sys.stdout)
        raise Exception(f"Invalid DEBUG_LEVEL {debug_level}, please choose between INFO, DEBUG, TRACE")
    logger.add(log_file, level=debug_level, mode="w")
    logger.add(sys.stdout, level=debug_level)


def should_sync_server(env, server_1: Plex | Jellyfin | Emby, server_2: Plex | Jellyfin | Emby) -> bool:
    sync_map = {
        (Plex, Jellyfin): "SYNC_FROM_PLEX_TO_JELLYFIN",
        (Plex, Emby): "SYNC_FROM_PLEX_TO_EMBY",
        (Plex, Plex): "SYNC_FROM_PLEX_TO_PLEX",
        (Jellyfin, Plex): "SYNC_FROM_JELLYFIN_TO_PLEX",
        (Jellyfin, Jellyfin): "SYNC_FROM_JELLYFIN_TO_JELLYFIN",
        (Jellyfin, Emby): "SYNC_FROM_JELLYFIN_TO_EMBY",
        (Emby, Plex): "SYNC_FROM_EMBY_TO_PLEX",
        (Emby, Jellyfin): "SYNC_FROM_EMBY_TO_JELLYFIN",
        (Emby, Emby): "SYNC_FROM_EMBY_TO_EMBY",
    }
    key = (type(server_1), type(server_2))
    env_var = sync_map.get(key)
    if env_var and not str_to_bool(get_env_value(env, env_var, "True")):
        logger.info(f"Sync from {server_1.server_type} -> {server_2.server_type} is disabled")
        return False
    return True


def main_loop(env) -> None:
    dryrun = str_to_bool(get_env_value(env, "DRYRUN", "False"))
    logger.info(f"Dryrun: {dryrun}")

    user_mapping = json.loads(get_env_value(env, "USER_MAPPING", "{}").lower())
    logger.info(f"User Mapping: {user_mapping}")

    library_mapping = json.loads(get_env_value(env, "LIBRARY_MAPPING", "{}"))
    logger.info(f"Library Mapping: {library_mapping}")

    (
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        blacklist_users,
        whitelist_users,
    ) = setup_black_white_lists(
        parse_string_to_list(get_env_value(env, "BLACKLIST_LIBRARY", None)),
        parse_string_to_list(get_env_value(env, "WHITELIST_LIBRARY", None)),
        parse_string_to_list(get_env_value(env, "BLACKLIST_LIBRARY_TYPE", None)),
        parse_string_to_list(get_env_value(env, "WHITELIST_LIBRARY_TYPE", None)),
        parse_string_to_list(get_env_value(env, "BLACKLIST_USERS", None)),
        parse_string_to_list(get_env_value(env, "WHITELIST_USERS", None)),
        library_mapping,
        user_mapping,
    )

    servers = generate_server_connections(env)

    for i, server_1 in enumerate(servers):
        for j in range(i + 1, len(servers)):
            server_2 = servers[j]

            if not should_sync_server(env, server_1, server_2) and not should_sync_server(env, server_2, server_1):
                continue

            logger.info(f"Comparing Server 1: {server_1.info()} with Server 2: {server_2.info()}")

            server_1_users, server_2_users = setup_users(server_1, server_2, blacklist_users, whitelist_users, user_mapping)
            server_1_libraries, server_2_libraries = setup_libraries(server_1, server_2, blacklist_library, blacklist_library_type, whitelist_library, whitelist_library_type, library_mapping)

            logger.info("Gathering watched content from servers...")
            server_1_watched = server_1.get_watched(server_1_users, server_1_libraries)
            server_2_watched = server_2.get_watched(server_2_users, server_2_libraries)

            logger.info("Comparing watched content and generating sync actions...")
            actions = sync_watched_lists(server_1_watched, server_2_watched, user_mapping, library_mapping)

            if not actions:
                logger.info("No sync actions needed.")
                continue

            logger.info(f"Found {len(actions)} actions to perform.")
            for action_type, server, user_id, item_id, viewed_date in actions:
                if dryrun:
                    logger.info(f"[DRYRUN] Would perform {action_type} for item {item_id} for user {user_id} on {server.server_type}")
                    continue

                try:
                    if action_type == "mark_watched":
                        server.mark_watched(user_id, item_id, viewed_date)
                        logger.success(f"Marked item {item_id} as watched for user {user_id} on {server.server_type}")
                    elif action_type == "mark_unwatched":
                        server.mark_unwatched(user_id, item_id)
                        logger.success(f"Marked item {item_id} as unwatched for user {user_id} on {server.server_type}")
                except Exception as e:
                    logger.error(f"Failed to perform action {action_type} for item {item_id} on {server.server_type}: {e}")


@logger.catch
def main() -> None:
    env_file = get_env_value(None, "ENV_FILE", ".env")
    env = dotenv_values(env_file)
    run_only_once = str_to_bool(get_env_value(env, "RUN_ONLY_ONCE", "False"))
    sleep_duration = float(get_env_value(env, "SLEEP_DURATION", "3600"))
    log_file = get_env_value(env, "LOG_FILE", "log.log")
    debug_level = get_env_value(env, "DEBUG_LEVEL", "INFO",).upper()

    times = []
    while True:
        try:
            start = perf_counter()
            configure_logger(log_file, debug_level)
            main_loop(env)
            end = perf_counter()
            times.append(end - start)
            if times:
                logger.info(f"Average execution time: {sum(times) / len(times):.2f}s")
            if run_only_once:
                break
            logger.info(f"Sleeping for {sleep_duration} seconds.")
            sleep(sleep_duration)
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
            logger.error(traceback.format_exc())
            if run_only_once:
                break
            logger.info(f"Retrying in {sleep_duration} seconds.")
            sleep(sleep_duration)
        except KeyboardInterrupt:
            if times:
                logger.info(f"Average execution time: {sum(times) / len(times):.2f}s")
            logger.info("Exiting.")
            os._exit(0)
