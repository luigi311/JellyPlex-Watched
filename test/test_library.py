import os
import sys

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

from src.library import combine_library_lists


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
                ],
            }
        ],
    )

    server_1_libs = {"TV Shows": "show"}
    server_2_libs = {"Shows": "tvshows"}

    combined = combine_library_lists(
        "plex-main", "jellyfin-main", server_1_libs, server_2_libs, settings
    )

    assert combined == {"TV Shows": ["Shows"]}


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
    settings = settings_override(whitelist_libraries=["Movies"])

    server_1_libs = {"Movies": "movie", "TV Shows": "show"}
    server_2_libs = {"Movies": "movies", "TV Shows": "tvshows"}

    combined = combine_library_lists(
        "plex-main", "jellyfin-main", server_1_libs, server_2_libs, settings
    )

    assert combined == {"Movies": ["Movies"]}
