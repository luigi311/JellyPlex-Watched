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

from src.users import combine_user_lists


def test_combine_user_lists_implicit_same_name():
    """Users with identical names on both servers sync without any mapping."""
    settings = settings_override()

    server_1_users = ["test", "test3", "luigi311"]
    server_2_users = ["luigi311", "test2", "test3"]

    combined = combine_user_lists(
        "plex-main", "jellyfin-main", server_1_users, server_2_users, settings
    )

    # 'luigi311' and 'test3' exist on both servers -> matched to themselves.
    # 'test' / 'test2' don't share a name and aren't mapped -> not matched.
    assert combined == {
        "luigi311": ["luigi311"],
        "test3": ["test3"],
    }


def test_combine_user_lists_with_mapping():
    """A user_mappings entry links differently-named users across servers."""
    settings = settings_override(
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

    server_1_users = ["test", "test3", "luigi311"]
    server_2_users = ["luigi311", "test2", "test3"]

    combined = combine_user_lists(
        "plex-main", "jellyfin-main", server_1_users, server_2_users, settings
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
    settings = settings_override(blacklist_users=["test3"])

    server_1_users = ["luigi311", "test3"]
    server_2_users = ["luigi311", "test3"]

    combined = combine_user_lists(
        "plex-main", "jellyfin-main", server_1_users, server_2_users, settings
    )

    assert combined == {"luigi311": ["luigi311"]}


def test_combine_user_lists_whitelist():
    """With a whitelist set, only whitelisted users sync."""
    settings = settings_override(whitelist_users=["luigi311"])

    server_1_users = ["luigi311", "test3"]
    server_2_users = ["luigi311", "test3"]

    combined = combine_user_lists(
        "plex-main", "jellyfin-main", server_1_users, server_2_users, settings
    )

    assert combined == {"luigi311": ["luigi311"]}


def test_combine_user_lists_fanout():
    """One source identity fanning out to multiple users on the other server."""
    settings = settings_override(
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

    server_1_users = ["family"]
    server_2_users = ["alice", "bob"]

    combined = combine_user_lists(
        "plex-main", "jellyfin-main", server_1_users, server_2_users, settings
    )

    # 'family' on plex fans out to both 'alice' and 'bob' on jellyfin.
    assert combined == {"family": ["alice", "bob"]}


def test_combine_user_lists_case_insensitive():
    """Server-reported casing differences don't break mapping resolution."""
    settings = settings_override(
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

    # servers report lowercased names
    server_1_users = ["jellyuser"]
    server_2_users = ["jellyplex_watched"]

    combined = combine_user_lists(
        "plex-main", "jellyfin-main", server_1_users, server_2_users, settings
    )

    assert combined == {"jellyuser": ["jellyplex_watched"]}
