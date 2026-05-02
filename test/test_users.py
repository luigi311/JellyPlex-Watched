import os
import sys

# getting the name of the directory
# where the this file is present.
current = os.path.dirname(os.path.realpath(__file__))

# Getting the parent directory name
# where the current directory is present.
parent = os.path.dirname(current)

# adding the parent directory to
# the sys.path.
sys.path.append(parent)

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.settings import AppSettings
from src.users import combine_user_lists


class _IsolatedAppSettings(AppSettings):
    """
    AppSettings that ignores all external configuration sources (env vars,
    .env, legacy .env, config.yaml) so tests depend only on the kwargs passed
    in. Without this, constructing AppSettings would read the developer's real
    .env / config.yaml and contaminate the test (e.g. a real whitelist_users
    would filter out the test users, yielding empty results).
    """

    # model_config is merged across inheritance in pydantic-settings, so the
    # base yaml_file keys must be explicitly cleared to avoid an unused-key
    # warning once the YAML source is dropped below.
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
        # Only honor explicit kwargs; suppress every ambient source.
        return (init_settings,)


class _FakeServerSettings:
    """Minimal stand-in for a Plex/Jellyfin/Emby *Settings object."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeServer:
    """
    Minimal stand-in for a connected server. combine_user_lists only reads
    `server.server_settings.name`, so that's all we need to provide.
    """

    def __init__(self, name: str) -> None:
        self.server_settings = _FakeServerSettings(name)


def _settings(**overrides) -> AppSettings:
    """
    Build an AppSettings without touching .env / config.yaml. Two token
    servers (plex-main, jellyfin-main) are always declared so the names used
    in the tests resolve; overrides let individual tests tweak sync_to,
    mappings, and filters.
    """
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


def test_combine_user_lists_implicit_same_name():
    """Users with identical names on both servers sync without any mapping."""
    settings = _settings()
    server_1 = _FakeServer("plex-main")
    server_2 = _FakeServer("jellyfin-main")

    server_1_users = ["test", "test3", "luigi311"]
    server_2_users = ["luigi311", "test2", "test3"]

    combined = combine_user_lists(
        server_1, server_2, server_1_users, server_2_users, settings
    )

    # 'luigi311' and 'test3' exist on both servers -> matched to themselves.
    # 'test' / 'test2' don't share a name and aren't mapped -> not matched.
    assert combined == {
        "luigi311": ["luigi311"],
        "test3": ["test3"],
    }


def test_combine_user_lists_with_mapping():
    """A user_mappings entry links differently-named users across servers."""
    settings = _settings(
        user_mappings=[
            {
                "canonical": "shared",
                "aliases": [
                    {"server": "plex-main", "username": "test"},
                    {"server": "jellyfin-main", "username": "test2"},
                ],
            }
        ],
    )
    server_1 = _FakeServer("plex-main")
    server_2 = _FakeServer("jellyfin-main")

    server_1_users = ["test", "test3", "luigi311"]
    server_2_users = ["luigi311", "test2", "test3"]

    combined = combine_user_lists(
        server_1, server_2, server_1_users, server_2_users, settings
    )

    # 'test' (plex) now maps to 'test2' (jellyfin) via the canonical, plus the
    # implicit same-name matches for luigi311 and test3.
    assert combined == {
        "test": ["test2"],
        "luigi311": ["luigi311"],
        "test3": ["test3"],
    }


def test_combine_user_lists_blacklist():
    """A blacklisted user is filtered out by should_sync_user."""
    settings = _settings(blacklist_users=["test3"])
    server_1 = _FakeServer("plex-main")
    server_2 = _FakeServer("jellyfin-main")

    server_1_users = ["luigi311", "test3"]
    server_2_users = ["luigi311", "test3"]

    combined = combine_user_lists(
        server_1, server_2, server_1_users, server_2_users, settings
    )

    assert combined == {"luigi311": ["luigi311"]}


def test_combine_user_lists_whitelist():
    """With a whitelist set, only whitelisted users sync."""
    settings = _settings(whitelist_users=["luigi311"])
    server_1 = _FakeServer("plex-main")
    server_2 = _FakeServer("jellyfin-main")

    server_1_users = ["luigi311", "test3"]
    server_2_users = ["luigi311", "test3"]

    combined = combine_user_lists(
        server_1, server_2, server_1_users, server_2_users, settings
    )

    assert combined == {"luigi311": ["luigi311"]}


def test_combine_user_lists_fanout():
    """One source identity fanning out to multiple users on the other server."""
    settings = _settings(
        user_mappings=[
            {
                "canonical": "family",
                "aliases": [
                    {"server": "plex-main", "username": "family"},
                    {"server": "jellyfin-main", "username": "alice"},
                    {"server": "jellyfin-main", "username": "bob"},
                ],
            }
        ],
    )
    server_1 = _FakeServer("plex-main")
    server_2 = _FakeServer("jellyfin-main")

    server_1_users = ["family"]
    server_2_users = ["alice", "bob"]

    combined = combine_user_lists(
        server_1, server_2, server_1_users, server_2_users, settings
    )

    # 'family' on plex fans out to both 'alice' and 'bob' on jellyfin.
    assert combined == {"family": ["alice", "bob"]}


def test_combine_user_lists_case_insensitive():
    """Server-reported casing differences don't break mapping resolution."""
    settings = _settings(
        user_mappings=[
            {
                "canonical": "JellyUser",
                "aliases": [
                    {"server": "plex-main", "username": "JellyUser"},
                    {"server": "jellyfin-main", "username": "jellyplex_watched"},
                ],
            }
        ],
    )
    server_1 = _FakeServer("plex-main")
    server_2 = _FakeServer("jellyfin-main")

    # servers report lowercased names
    server_1_users = ["jellyuser"]
    server_2_users = ["jellyplex_watched"]

    combined = combine_user_lists(
        server_1, server_2, server_1_users, server_2_users, settings
    )

    assert combined == {"jellyuser": ["jellyplex_watched"]}
