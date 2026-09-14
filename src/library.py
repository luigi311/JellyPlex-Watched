from collections.abc import Iterable

from loguru import logger

from src.emby import Emby
from src.functions import normalize_name
from src.jellyfin import Jellyfin
from src.plex import Plex
from src.settings import AppSettings


def generate_library_list(server: Plex | Jellyfin | Emby) -> dict[str, str]:
    """
    Return the server's libraries as {library_name: library_type}.
    """
    return server.get_libraries()


def combine_library_lists(
    server_1_name: str,
    server_2_name: str,
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
      - settings.should_sync_library handles name and endpoint type filters,
        explicit library exceptions, and default eligibility for each direction.
      - settings.sync_targets_for_library resolves the target library name(s)
        on the other server (explicit library_mappings aliases plus the
        implicit same-name fallback).

    Both directions (1 -> 2 and 2 -> 1) are considered so the map covers
    relationships declared on either side, and targets discovered from each
    direction are merged rather than overwritten.
    """
    # Accumulate into sets to dedupe targets discovered from both directions.
    accumulator: dict[str, set[str]] = {}
    server_1_by_name = {normalize_name(name): name for name in server_1_libraries}
    server_2_by_name = {normalize_name(name): name for name in server_2_libraries}
    legacy_conflicts = settings.legacy_library_conflicts(
        server_1_name, server_1_libraries
    ) | settings.legacy_library_conflicts(server_2_name, server_2_libraries)

    for canonical in sorted(legacy_conflicts):
        logger.warning(
            f"Skipping legacy library mapping '{canonical}' between "
            f"{server_1_name} and {server_2_name}: both aliases are present "
            "on at least one server. Replace it with server-scoped YAML "
            "aliases before syncing these libraries."
        )

    def add(s1_library: str, s2_library: str) -> None:
        accumulator.setdefault(s1_library, set()).add(s2_library)

    # server_1 -> server_2
    for s1_library, s1_type in server_1_libraries.items():
        canonical = settings.lookup_library(server_1_name, s1_library)
        if canonical is not None and canonical in legacy_conflicts:
            continue
        for target in settings.sync_targets_for_library(
            server_1_name, s1_library, server_2_name
        ):
            target_name = server_2_by_name.get(normalize_name(target))
            if target_name is not None and settings.should_sync_library(
                s1_library,
                server_1_name,
                server_2_name,
                library_type=s1_type,
                target_library_type=server_2_libraries[target_name],
            ):
                add(s1_library, target_name)

    # server_2 -> server_1 (fills in relationships declared the other way)
    for s2_library, s2_type in server_2_libraries.items():
        canonical = settings.lookup_library(server_2_name, s2_library)
        if canonical is not None and canonical in legacy_conflicts:
            continue
        for target in settings.sync_targets_for_library(
            server_2_name, s2_library, server_1_name
        ):
            target_name = server_1_by_name.get(normalize_name(target))
            if target_name is not None and settings.should_sync_library(
                s2_library,
                server_2_name,
                server_1_name,
                library_type=s2_type,
                target_library_type=server_1_libraries[target_name],
            ):
                # key is always the server_1-side library name
                add(target_name, s2_library)

    # Freeze to sorted lists for a stable, deterministic result.
    return {s1_library: sorted(targets) for s1_library, targets in accumulator.items()}


def generate_server_libraries(
    server: Plex | Jellyfin | Emby,
    library_names: Iterable[str],
) -> list[str]:
    """
    Return the names of `server`'s libraries that participate in the sync
    map, matched against the names belonging to this side of the map.
    """
    normalized_names = {normalize_name(name) for name in library_names}

    return [
        library
        for library in server.get_libraries()
        if normalize_name(library) in normalized_names
    ]


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
        server_1.server_settings.name,
        server_2.server_settings.name,
        server_1_libraries,
        server_2_libraries,
        settings,
    )
    logger.debug(f"Library list to sync between servers {libraries}")

    output_server_1_libraries = generate_server_libraries(server_1, libraries.keys())
    target_library_names = [
        target for targets in libraries.values() for target in targets
    ]
    output_server_2_libraries = generate_server_libraries(
        server_2, target_library_names
    )

    return output_server_1_libraries, output_server_2_libraries
