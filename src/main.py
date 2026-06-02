import os
import traceback
from time import perf_counter, sleep

from loguru import logger

from src.connection import generate_server_connections
from src.functions import (
    configure_logger,
    get_env_value,
)
from src.library import setup_libraries
from src.settings import AppSettings, load_settings
from src.users import setup_users
from src.watched import (
    cleanup_watched,
    merge_server_watched,
)


def main_loop(settings: AppSettings, average_time: float) -> None:
    logger.info(f"Dryrun: {settings.dryrun}")

    logger.bind(data=settings).trace("Settings")
    if settings.debug_level != "TRACE":
        # Avoid printing both full settings and these individual when in trace mode
        logger.bind(data=settings.user_mappings).info("User Mapping: ")
        logger.bind(data=settings.whitelist_users).info("Whitelist Users: ")
        logger.bind(data=settings.blacklist_users).info("Blacklist Users: ")
        logger.bind(data=settings.library_mappings).info("Library Mapping: ")
        logger.bind(data=settings.whitelist_libraries).info("Whitelist Libraries: ")
        logger.bind(data=settings.blacklist_libraries).info("Blacklist Libraries: ")
        logger.bind(data=settings.whitelist_library_types).info(
            "Whitelist Library Types: "
        )
        logger.bind(data=settings.blacklist_library_types).info(
            "Blacklist Library Types: "
        )

    servers = generate_server_connections(settings)

    for server_1 in servers:
        # If server is the final server in the list, then we are done with the loop
        if server_1 == servers[-1]:
            break

        # Store a copy of server_1_watched that way it can be used multiple times without having to regather everyones watch history every single time
        server_1_watched = None

        # Start server_2 at the next server in the list
        for server_2 in servers[servers.index(server_1) + 1 :]:
            # Check if server 1 and server 2 are going to be synced in either direction, skip if not
            if not settings.should_sync_server(
                server_1.server_settings.name, server_2.server_settings.name
            ) and not settings.should_sync_server(
                server_2.server_settings.name, server_1.server_settings.name
            ):
                msg = f"Neither {server_1.info()} or {server_2.info()} are syncing towards each other, skipping pair"
                logger.warning(msg)
                continue

            logger.info(f"Server 1: {type(server_1)}: {server_1.info()}")
            logger.info(f"Server 2: {type(server_2)}: {server_2.info()}")

            # Create users list
            logger.info("Creating users list")
            server_1_users, server_2_users = setup_users(server_1, server_2, settings)

            if not server_1_users and not server_2_users:
                continue

            server_1_libraries, server_2_libraries = setup_libraries(
                server_1, server_2, settings
            )
            logger.info(f"Server 1 syncing libraries: {server_1_libraries}")
            logger.info(f"Server 2 syncing libraries: {server_2_libraries}")

            logger.info("Creating watched lists")
            server_1_watched = server_1.get_watched(
                server_1_users, server_1_libraries, server_1_watched
            )
            logger.info("Finished creating watched list server 1")

            server_2_watched = server_2.get_watched(server_2_users, server_2_libraries)
            logger.info("Finished creating watched list server 2")

            logger.info("Cleaning Server 1 Watched")
            server_1_watched_filtered = cleanup_watched(
                server_1_watched,
                server_2_watched,
                server_1.server_settings.name,
                server_2.server_settings.name,
                settings,
                average_time,
            )

            logger.info("Cleaning Server 2 Watched")
            server_2_watched_filtered = cleanup_watched(
                server_2_watched,
                server_1_watched,
                server_2.server_settings.name,
                server_1.server_settings.name,
                settings,
                average_time,
            )

            logger.debug(
                f"server 1 watched that needs to be synced to server 2:\n{server_1_watched_filtered}",
            )
            logger.debug(
                f"server 2 watched that needs to be synced to server 1:\n{server_2_watched_filtered}",
            )

            if settings.should_sync_server(
                server_2.server_settings.name, server_1.server_settings.name
            ):
                logger.info(f"Syncing {server_2.info()} -> {server_1.info()}")

                # Add server_2_watched_filtered to server_1_watched that way the stored version isn't stale for the next server
                # if not settings.dryrun:
                #     server_1_watched = merge_server_watched(
                #         server_1_watched,
                #         server_2_watched_filtered,
                #         server_1.server_settings.name,
                #         server_2.server_settings.name,
                #         settings,
                #         average_time,
                #     )

                server_1.update_watched(
                    server_2_watched_filtered, server_2.server_settings.name
                )

            if settings.should_sync_server(
                server_1.server_settings.name, server_2.server_settings.name
            ):
                logger.info(f"Syncing {server_1.info()} -> {server_2.info()}")
                server_2.update_watched(
                    server_1_watched_filtered, server_1.server_settings.name
                )


@logger.catch
def main() -> None:
    # Resolve config file paths, honoring ENV_FILE / YAML_FILE overrides and
    # falling back to the conventional defaults. Resolving here keeps the path
    # discovery in one place and lets load_settings stay path-agnostic.
    env_file = get_env_value(None, "ENV_FILE", ".env")
    yaml_file = get_env_value(None, "YAML_FILE", "config.yaml")

    settings: AppSettings = load_settings(env_file=env_file, yaml_file=yaml_file)

    times: list[float] = []
    average_time: float = 100.0  # Seed average time at 100
    while True:
        try:
            start = perf_counter()
            # Reconfigure the logger on each loop so the logs are rotated on each run
            configure_logger(settings.log_file, settings.debug_level)
            main_loop(settings, average_time)
            end = perf_counter()
            times.append(end - start)

            if len(times) > 0:
                average_time = sum(times) / len(times)
                logger.info(f"Average time: {average_time}")

            if settings.run_only_once:
                break

            logger.info(f"Looping in {settings.sleep_duration}")
            sleep(settings.sleep_duration)

        except Exception as error:
            if isinstance(error, list):
                for message in error:
                    logger.error(message)
            else:
                logger.error(error)

            logger.error(traceback.format_exc())

            if settings.run_only_once:
                break

            logger.info(f"Retrying in {settings.sleep_duration}")
            sleep(settings.sleep_duration)

        except KeyboardInterrupt:
            if len(times) > 0:
                logger.info(f"Average time: {sum(times) / len(times)}")
            logger.info("Exiting")
            os._exit(0)
