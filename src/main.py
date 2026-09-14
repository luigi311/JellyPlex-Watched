import os
import traceback
from time import perf_counter, sleep

from loguru import logger

from src.connection import generate_server_connections
from src.functions import configure_logger
from src.settings import AppSettings, load_settings
from src.users import generate_all_server_users
from src.sync_inventory import fetch_watched_inventory, generate_sync_inventory
from src.sync_plan import generate_watched_plan


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

    watched_plan = generate_watched_plan(servers_watched, settings, average_time)
    logger.debug("Planned watched updates for {} servers", len(watched_plan))

    for destination, source_batches in watched_plan.items():
        logger.info("Applying watched plan to {}", destination.info())
        for source_name, updates in source_batches.items():
            # For relayed winners this is the final authorized hop; each
            # update's relay_path retains the original source and full route.
            destination.update_watched(updates, source_name)


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
