import os
import sys

from pydantic_settings import SettingsConfigDict

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
from src.settings import AppSettings


class _IsolatedAppSettings(AppSettings):
    """
    AppSettings that ignores all external configuration sources (env vars,
    .env, legacy .env, config.yaml) so tests depend only on the kwargs passed
    in. Without this, constructing AppSettings would read the developer's real
    .env / config.yaml and contaminate the test.
    """

    model_config = SettingsConfigDict(
        yaml_file=None,
        yaml_file_encoding=None,
        nested_model_default_partial_update=True,
        extra="forbid",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (init_settings,)


def _settings(**overrides) -> AppSettings:
    base = {
        "plex": [
            {
                "name": "plex-main",
                "baseurl": "http://plex",
                "token": "x",
                "sync_to": ["jellyfin-main"],
            }
        ],
        "jellyfin": [
            {
                "name": "jellyfin-main",
                "baseurl": "http://jellyfin",
                "token": "x",
                "sync_to": ["plex-main"],
            }
        ],
    }
    base.update(overrides)
    return _IsolatedAppSettings(**base)


def test_combine_library_lists_implicit_same_name():
    """Libraries with the same name on both servers sync without a mapping."""
    settings = _settings()

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
    settings = _settings(
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
    settings = _settings(blacklist_library_types=["music"])

    server_1_libs = {"Movies": "movie", "Music": "music"}
    server_2_libs = {"Movies": "movies", "Music": "music"}

    combined = combine_library_lists(
        "plex-main", "jellyfin-main", server_1_libs, server_2_libs, settings
    )

    # 'Music' is dropped by the type blacklist; only 'Movies' remains.
    assert combined == {"Movies": ["Movies"]}


def test_combine_library_lists_type_whitelist():
    """With a type whitelist set, only matching types sync."""
    settings = _settings(whitelist_library_types=["movie", "movies"])

    server_1_libs = {"Movies": "movie", "TV Shows": "show"}
    server_2_libs = {"Movies": "movies", "Shows": "tvshows"}

    combined = combine_library_lists(
        "plex-main", "jellyfin-main", server_1_libs, server_2_libs, settings
    )

    assert combined == {"Movies": ["Movies"]}


def test_combine_library_lists_name_blacklist():
    """A blacklisted library name is filtered out by should_sync_library."""
    settings = _settings(blacklist_libraries=["TV Shows"])

    server_1_libs = {"Movies": "movie", "TV Shows": "show"}
    server_2_libs = {"Movies": "movies", "TV Shows": "tvshows"}

    combined = combine_library_lists(
        "plex-main", "jellyfin-main", server_1_libs, server_2_libs, settings
    )

    assert combined == {"Movies": ["Movies"]}


def test_combine_library_lists_name_whitelist():
    """With a library whitelist set, only whitelisted libraries sync."""
    settings = _settings(whitelist_libraries=["Movies"])

    server_1_libs = {"Movies": "movie", "TV Shows": "show"}
    server_2_libs = {"Movies": "movies", "TV Shows": "tvshows"}

    combined = combine_library_lists(
        "plex-main", "jellyfin-main", server_1_libs, server_2_libs, settings
    )

    assert combined == {"Movies": ["Movies"]}
