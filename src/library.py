from loguru import logger

from src.emby import Emby
from src.jellyfin import Jellyfin
from src.plex import Plex
from src.settings import AppSettings


def generate_library_list(server: Plex | Jellyfin | Emby) -> dict[str, str]:
    """
    Return the server's libraries as {library_name: library_type}.
    """
    return server.get_libraries()


def combine_library_lists(
    server_1: Plex | Jellyfin | Emby,
    server_2: Plex | Jellyfin | Emby,
    server_1_libraries: dict[str, str],
    server_2_libraries: dict[str, str],
    settings: AppSettings,
) -> dict[str, list[str]]:
    """
    Build the map of libraries that should sync between two servers, using
    the new settings model. Mirrors users.combine_user_lists.

    Returns {source_library_on_server_1: [target_libraries_on_server_2, ...]}.

    A single source library may map to multiple libraries on the other server
    (the fan-out case), so every server_1 key maps to a *list* of server_2
    library names.

    Filtering is fully delegated to the settings model:
      - settings.is_library_type_allowed handles the library-type
        blacklist/whitelist (movie/show), which is non-directional.
      - settings.should_sync_library handles the library-name
        blacklist/whitelist, per-library sync_rules, and the server-level
        sync_to fallback for a given direction.
      - settings.sync_targets_for_library resolves the target library name(s)
        on the other server (explicit library_mappings aliases plus the
        implicit same-name fallback).

    Both directions (1 -> 2 and 2 -> 1) are considered so the map covers
    relationships declared on either side, and targets discovered from each
    direction are merged rather than overwritten.
    """
    s1_name = server_1.server_settings.name
    s2_name = server_2.server_settings.name

    # Accumulate into sets to dedupe targets discovered from both directions.
    accumulator: dict[str, set[str]] = {}

    def add(s1_library: str, s2_library: str) -> None:
        accumulator.setdefault(s1_library, set()).add(s2_library)

    # server_1 -> server_2
    for s1_library, s1_type in server_1_libraries.items():
        if not settings.is_library_type_allowed(s1_type):
            logger.info(
                f"Skipping library {s1_library}: type '{s1_type}' is filtered out"
            )
            continue
        if not settings.should_sync_library(s1_library, s1_name, s2_name):
            continue
        for target in settings.sync_targets_for_library(s1_name, s1_library, s2_name):
            if target in server_2_libraries:
                add(s1_library, target)

    # server_2 -> server_1 (fills in relationships declared the other way)
    for s2_library, s2_type in server_2_libraries.items():
        if not settings.is_library_type_allowed(s2_type):
            logger.info(
                f"Skipping library {s2_library}: type '{s2_type}' is filtered out"
            )
            continue
        if not settings.should_sync_library(s2_library, s2_name, s1_name):
            continue
        for target in settings.sync_targets_for_library(s2_name, s2_library, s1_name):
            if target in server_1_libraries:
                # key is always the server_1-side library name
                add(target, s2_library)

    # Freeze to sorted lists for a stable, deterministic result.
    return {s1_library: sorted(targets) for s1_library, targets in accumulator.items()}


def generate_server_libraries(
    server: Plex | Jellyfin | Emby,
    libraries: dict[str, list[str]],
) -> list[str]:
    """
    Return the names of `server`'s libraries that participate in the sync
    map, matched against both the server_1-side keys and the server_2-side
    targets. Mirrors users.generate_server_users.
    """
    source_names = set(libraries.keys())
    target_names = {target for targets in libraries.values() for target in targets}
    all_names = source_names | target_names

    return [library for library in server.get_libraries() if library in all_names]


def setup_libraries(
    server_1: Plex | Jellyfin | Emby,
    server_2: Plex | Jellyfin | Emby,
    settings: AppSettings,
) -> tuple[list[str], list[str]]:
    server_1_libraries = generate_library_list(server_1)
    server_2_libraries = generate_library_list(server_2)

    logger.debug(
        f"Server 1 ({server_1.server_settings.name}): Libraries and types {server_1_libraries}"
    )
    logger.debug(
        f"Server 2 ({server_2.server_settings.name}): Libraries and types {server_2_libraries}"
    )

    # Blacklist/whitelist (name + type) and per-library sync rules are all
    # resolved inside combine_library_lists via the settings model, so there
    # is no longer a separate filtering step.
    libraries = combine_library_lists(
        server_1, server_2, server_1_libraries, server_2_libraries, settings
    )
    logger.debug(f"Library list to sync between servers {libraries}")

    output_server_1_libraries = generate_server_libraries(server_1, libraries)
    output_server_2_libraries = generate_server_libraries(server_2, libraries)

    return output_server_1_libraries, output_server_2_libraries
