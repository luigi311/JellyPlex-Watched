import os
import sys
from types import SimpleNamespace
from typing import cast

from conftest import settings_override

# getting the name of the directory
# where the this file is present.
current = os.path.dirname(os.path.realpath(__file__))

# Getting the parent directory name
# where the current directory is present.
parent = os.path.dirname(current)

# adding the parent directory to
# the sys.path.
sys.path.append(parent)

from src.library import combine_library_lists, generate_server_libraries  # noqa: E402
from src.plex import Plex  # noqa: E402


def test_combine_library_lists_implicit_same_name():
    """Libraries with the same name on both servers sync without a mapping."""
    settings = settings_override()

    # {library_name: type}
    server_1_libs = {"Movies": "movie", "TV Shows": "show"}
    server_2_libs = {"Movies": "movies", "Music": "music"}

    combined = combine_library_lists(
        "plex-main", "jellyfin-main", server_1_libs, server_2_libs, settings
    )

    # Only 'Movies' exists on both -> matched to itself. 'TV Shows' has no
    # counterpart on server 2; 'Music' has none on server 1.
    assert combined == {"Movies": ["Movies"]}


def test_combine_library_lists_with_mapping():
    """A library_mappings entry links differently-named libraries."""
    settings = settings_override(
        library_mappings=[
            {
                "canonical": "Shows",
                "aliases": [
                    {"server": "plex-main", "library": "TV Shows"},
                    {"server": "jellyfin-main", "library": "Shows"},
                    {
                        "server": "jellyfin-main",
                        "library": "Shows Archive",
                    },
                ],
            }
        ],
    )

    server_1_libs = {"TV Shows": "show"}
    server_2_libs = {"Shows": "tvshows", "Shows Archive": "tvshows"}

    combined = combine_library_lists(
        "plex-main", "jellyfin-main", server_1_libs, server_2_libs, settings
    )

    assert combined == {"TV Shows": ["Shows", "Shows Archive"]}


def test_legacy_library_mapping_skips_ambiguous_discovery():
    """Legacy-expanded pairs sync only when each side identifies one alias."""
    settings = settings_override(
        library_mappings=[
            {
                "canonical": "movies",
                "legacy": True,
                "aliases": [
                    {"server": "plex-main", "library": "Movies"},
                    {"server": "plex-main", "library": "Films"},
                    {"server": "jellyfin-main", "library": "Movies"},
                    {"server": "jellyfin-main", "library": "Films"},
                ],
            }
        ]
    )

    assert (
        combine_library_lists(
            "plex-main",
            "jellyfin-main",
            {"Movies": "movie", "Films": "movie"},
            {"Movies": "movie", "Films": "movie"},
            settings,
        )
        == {}
    )
    assert combine_library_lists(
        "plex-main",
        "jellyfin-main",
        {"Movies": "movie"},
        {"Films": "movie"},
        settings,
    ) == {"Movies": ["Films"]}


def test_combine_library_lists_type_blacklist():
    """A library whose type is blacklisted is dropped regardless of name match."""
    settings = settings_override(blacklist_library_types=["music"])

    server_1_libs = {"Movies": "movie", "Music": "music"}
    server_2_libs = {"Movies": "movies", "Music": "music"}

    combined = combine_library_lists(
        "plex-main", "jellyfin-main", server_1_libs, server_2_libs, settings
    )

    # 'Music' is dropped by the type blacklist; only 'Movies' remains.
    assert combined == {"Movies": ["Movies"]}


def test_combine_library_lists_type_whitelist():
    """With a type whitelist set, only matching types sync."""
    settings = settings_override(whitelist_library_types=["movie", "movies"])

    server_1_libs = {"Movies": "movie", "TV Shows": "show"}
    server_2_libs = {"Movies": "movies", "Shows": "tvshows"}

    combined = combine_library_lists(
        "plex-main", "jellyfin-main", server_1_libs, server_2_libs, settings
    )

    assert combined == {"Movies": ["Movies"]}


def test_combine_library_lists_filters_types_on_both_servers():
    """A filtered type cannot enter the map through the other direction."""
    settings = settings_override(blacklist_library_types=["music"])

    server_1_libraries = {
        "Movies": "movie",
        "Shows": "show",
    }
    server_2_libraries = {
        "Movies": "music",
        "Shows": "show",
    }

    assert combine_library_lists(
        "plex-main",
        "jellyfin-main",
        server_1_libraries,
        server_2_libraries,
        settings,
    ) == {"Shows": ["Shows"]}
    assert combine_library_lists(
        "plex-main",
        "jellyfin-main",
        server_2_libraries,
        server_1_libraries,
        settings,
    ) == {"Shows": ["Shows"]}


def test_combine_library_lists_name_blacklist():
    """A blacklisted library name is filtered out by should_sync_library."""
    settings = settings_override(blacklist_libraries=["TV Shows"])

    server_1_libs = {"Movies": "movie", "TV Shows": "show"}
    server_2_libs = {"Movies": "movies", "TV Shows": "tvshows"}

    combined = combine_library_lists(
        "plex-main", "jellyfin-main", server_1_libs, server_2_libs, settings
    )

    assert combined == {"Movies": ["Movies"]}


def test_combine_library_lists_name_whitelist():
    """With a library whitelist set, only whitelisted libraries sync."""
    settings = settings_override(
        blacklist_libraries=["Movies"],
        whitelist_libraries=["Movies"],
    )

    server_1_libs = {"Movies": "movie", "TV Shows": "show"}
    server_2_libs = {"Movies": "movies", "TV Shows": "tvshows"}

    combined = combine_library_lists(
        "plex-main", "jellyfin-main", server_1_libs, server_2_libs, settings
    )

    assert combined == {"Movies": ["Movies"]}


def test_generate_server_libraries_uses_side_specific_names():
    """Source keys and target values are matched only on their own side."""
    server = cast(
        Plex,
        SimpleNamespace(
            get_libraries=lambda: {
                "TV Shows": "show",
                "Shows": "show",
            }
        ),
    )
    library_map = {"tv shows": ["SHOWS"]}

    assert generate_server_libraries(server, library_map.keys()) == ["TV Shows"]
    assert generate_server_libraries(server, ["SHOWS"]) == ["Shows"]
