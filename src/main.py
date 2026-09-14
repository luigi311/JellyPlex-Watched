import os
import traceback
from copy import deepcopy
from time import perf_counter, sleep

from loguru import logger

from src.connection import generate_server_connections
from src.functions import configure_logger
from src.settings import AppSettings, load_settings
from src.users import generate_all_server_users
from src.sync_inventory import fetch_watched_inventory, generate_sync_inventory
from src.watched import cleanup_watched, merge_destination_watched


def main_loop(settings: AppSettings, average_time: float) -> None:
    logger.info(f"Dryrun: {settings.dryrun}")

    logger.bind(data=settings).debug("Settings")
    if settings.debug_level != "DEBUG":
        # Avoid printing both full settings and these individual when in DEBUG mode
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

    # Generate lists of users participating in outgoing or incoming syncs.
    server_users = generate_all_server_users(servers, settings)
    logger.debug("Selected users for {} servers", len(server_users))

    # Discover accessible libraries once per user, then filter using cached inventories.
    server_user_libraries = generate_sync_inventory(server_users, settings)
    logger.debug("Selected user libraries for {} servers", len(server_user_libraries))

    servers_watched = fetch_watched_inventory(server_user_libraries)
    logger.debug("Fetched watched data for {} servers", len(servers_watched))

    working_watched = dict(servers_watched)
    fetched_servers = list(servers_watched)
    for index, server_1 in enumerate(fetched_servers[:-1]):
        # Preserve the fetched snapshot while incorporating confirmed writes.
        server_1_watched = deepcopy(working_watched[server_1])

        for server_2 in fetched_servers[index + 1 :]:
            server_2_watched = working_watched[server_2]

            # cleanup_watched applies directional user and library policy,
            # including rules that enable sync beyond server-level sync_to.
            logger.info("Cleaning Server 1 Watched")
            server_1_watched_filtered = cleanup_watched(
                server_1_watched,
                server_2_watched,
                server_1.server_settings.name,
                server_2.server_settings.name,
                settings,
                average_time,
                require_destination_scope=True,
            )

            logger.info("Cleaning Server 2 Watched")
            server_2_watched_filtered = cleanup_watched(
                server_2_watched,
                server_1_watched,
                server_2.server_settings.name,
                server_1.server_settings.name,
                settings,
                average_time,
                require_destination_scope=True,
            )

            logger.debug(
                f"server 1 watched that needs to be synced to server 2:\n{server_1_watched_filtered}",
            )
            logger.debug(
                f"server 2 watched that needs to be synced to server 1:\n{server_2_watched_filtered}",
            )

            if server_2_watched_filtered:
                logger.info(f"Syncing {server_2.info()} -> {server_1.info()}")

                write_outcomes = server_1.update_watched(
                    server_2_watched_filtered, server_2.server_settings.name
                )

                # Keep the cached target history current for the next server
                # pair using only confirmed, destination-native write results.
                if not settings.dryrun and write_outcomes:
                    server_1_watched = merge_destination_watched(
                        server_1_watched,
                        write_outcomes,
                        settings,
                        average_time,
                    )
                    working_watched[server_1] = server_1_watched

            if server_1_watched_filtered:
                logger.info(f"Syncing {server_1.info()} -> {server_2.info()}")
                write_outcomes = server_2.update_watched(
                    server_1_watched_filtered,
                    server_1.server_settings.name,
                )
                if not settings.dryrun and write_outcomes:
                    working_watched[server_2] = merge_destination_watched(
                        server_2_watched,
                        write_outcomes,
                        settings,
                        average_time,
                    )


def main() -> None:
    # load_settings resolves ENV_FILE / YAML_FILE and creates one startup
    # snapshot for the lifetime of the process.
    settings: AppSettings = load_settings()

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
