import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

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

from src.users import combine_user_lists  # noqa: E402
from src.jellyfin_emby import JellyfinEmby  # noqa: E402
from src.plex import Plex  # noqa: E402
from src.watched import (  # noqa: E402
    LibraryData,
    MediaIdentifiers,
    MediaItem,
    UserData,
    WatchedStatus,
    cleanup_watched,
)


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


def test_legacy_user_mapping_skips_ambiguous_discovery():
    """Legacy-expanded pairs sync only when each side identifies one alias."""
    settings = settings_override(
        user_mappings=[
            {
                "canonical": "a",
                "legacy": True,
                "aliases": [
                    {"server": "plex-main", "username": "a"},
                    {"server": "plex-main", "username": "b"},
                    {"server": "jellyfin-main", "username": "a"},
                    {"server": "jellyfin-main", "username": "b"},
                ],
            }
        ]
    )

    assert (
        combine_user_lists(
            "plex-main",
            "jellyfin-main",
            ["a", "b"],
            ["a", "b"],
            settings,
        )
        == {}
    )
    assert combine_user_lists(
        "plex-main", "jellyfin-main", ["a"], ["b"], settings
    ) == {"a": ["b"]}


def test_adapter_resolvers_return_all_user_and_library_fanout_targets():
    """Adapters preserve every mapped target when resolving a write."""
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
        library_mappings=[
            {
                "canonical": "shows",
                "aliases": [
                    {"server": "plex-main", "library": "TV Shows"},
                    {"server": "jellyfin-main", "library": "Shows"},
                    {"server": "jellyfin-main", "library": "Shows Archive"},
                ],
            }
        ],
    )

    plex_adapter = object.__new__(Plex)
    plex_adapter.app_settings = settings
    plex_adapter.server_settings = SimpleNamespace(name="jellyfin-main")
    plex_adapter.users = [
        SimpleNamespace(username="alice", title="Alice"),
        SimpleNamespace(username="bob", title="Bob"),
    ]

    assert [
        user.username
        for user in plex_adapter._resolve_local_users("plex-main", "family")
    ] == ["alice", "bob"]
    assert plex_adapter._resolve_local_libraries(
        "plex-main", "TV Shows", ["Shows", "Shows Archive"]
    ) == ["Shows", "Shows Archive"]

    jellyfin_adapter = object.__new__(JellyfinEmby)
    jellyfin_adapter.app_settings = settings
    jellyfin_adapter.server_settings = SimpleNamespace(name="jellyfin-main")
    jellyfin_adapter.users = {"alice": "alice-id", "bob": "bob-id"}

    assert jellyfin_adapter._resolve_local_users("plex-main", "family") == [
        ("alice", "alice-id"),
        ("bob", "bob-id"),
    ]
    assert jellyfin_adapter._resolve_local_libraries(
        "plex-main",
        "TV Shows",
        [
            {"Name": "Shows", "Id": "shows-id"},
            {"Name": "Shows Archive", "Id": "archive-id"},
        ],
    ) == [("Shows", "shows-id"), ("Shows Archive", "archive-id")]


def test_adapters_write_cleanup_pending_fanout_targets():
    """Cleanup keeps updates for targets with different watched histories."""
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
        library_mappings=[
            {
                "canonical": "shows",
                "aliases": [
                    {"server": "plex-main", "library": "TV Shows"},
                    {"server": "jellyfin-main", "library": "Shows"},
                    {"server": "jellyfin-main", "library": "Shows Archive"},
                ],
            }
        ],
    )
    movie = MediaItem(
        identifiers=MediaIdentifiers(
            title="Fan-out movie",
            locations=("fan-out-movie.mkv",),
        ),
        status=WatchedStatus(
            completed=True,
            time=0,
            viewed_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )
    watched = {
        "family": UserData(
            libraries={
                "TV Shows": LibraryData(title="TV Shows", movies=[movie])
            }
        )
    }
    destination_watched = {
        "alice": UserData(
            libraries={
                "Shows": LibraryData(title="Shows", movies=[movie]),
                "Shows Archive": LibraryData(title="Shows Archive"),
            }
        ),
        "bob": UserData(
            libraries={
                "Shows": LibraryData(title="Shows"),
                "Shows Archive": LibraryData(title="Shows Archive"),
            }
        ),
    }
    pending = cleanup_watched(
        watched,
        destination_watched,
        "plex-main",
        "jellyfin-main",
        settings,
        average_time=0.0,
    )
    assert sorted((update.target_user, update.target_library) for update in pending) == [
        ("alice", "Shows Archive"),
        ("bob", "Shows"),
        ("bob", "Shows Archive"),
    ]

    jellyfin_adapter = object.__new__(JellyfinEmby)
    jellyfin_adapter.app_settings = settings
    jellyfin_adapter.server_settings = SimpleNamespace(name="jellyfin-main")
    jellyfin_adapter.server_type = "Jellyfin"
    jellyfin_adapter.users = {"alice": "alice-id", "bob": "bob-id"}
    jellyfin_adapter.query = lambda _path, _method: {
        "Items": [
            {"Name": "Shows", "Id": "shows-id"},
            {"Name": "Shows Archive", "Id": "archive-id"},
        ]
    }
    jellyfin_calls: list[tuple[str, str, str]] = []

    def record_jellyfin_write(
        user_name: str,
        user_id: str,
        _library_data: LibraryData,
        library_name: str,
        _library_id: str,
        _dryrun: bool,
    ) -> None:
        jellyfin_calls.append((user_name, user_id, library_name))

    jellyfin_adapter.update_user_watched = record_jellyfin_write
    jellyfin_updated = jellyfin_adapter.update_watched(pending, "plex-main")

    assert sorted(jellyfin_calls) == [
        ("alice", "alice-id", "Shows Archive"),
        ("bob", "bob-id", "Shows"),
        ("bob", "bob-id", "Shows Archive"),
    ]
    assert set(jellyfin_updated) == {"alice", "bob"}
    assert set(jellyfin_updated["alice"].libraries) == {"Shows Archive"}
    assert set(jellyfin_updated["bob"].libraries) == {"Shows", "Shows Archive"}

    class _EveryUserIsAdmin:
        def __eq__(self, _other: object) -> bool:
            return True

    plex_adapter = object.__new__(Plex)
    plex_adapter.app_settings = settings
    plex_adapter.server_settings = SimpleNamespace(name="jellyfin-main")
    plex_adapter.admin_user = _EveryUserIsAdmin()
    plex_adapter.plex = SimpleNamespace(
        library=SimpleNamespace(
            sections=lambda: [
                SimpleNamespace(title="Shows"),
                SimpleNamespace(title="Shows Archive"),
            ]
        )
    )
    plex_adapter.users = [
        SimpleNamespace(username="alice", title="Alice"),
        SimpleNamespace(username="bob", title="Bob"),
    ]
    plex_calls: list[tuple[str, str]] = []

    def record_plex_write(
        plex_user: SimpleNamespace,
        _plex_server: SimpleNamespace,
        _library_data: LibraryData,
        library_name: str,
        _dryrun: bool,
    ) -> None:
        plex_calls.append((plex_user.username, library_name))

    plex_adapter.update_user_watched = record_plex_write
    plex_updated = plex_adapter.update_watched(pending, "plex-main")

    assert sorted(plex_calls) == [
        ("alice", "Shows Archive"),
        ("bob", "Shows"),
        ("bob", "Shows Archive"),
    ]
    assert set(plex_updated) == {"alice", "bob"}
    assert set(plex_updated["alice"].libraries) == {"Shows Archive"}
    assert set(plex_updated["bob"].libraries) == {"Shows", "Shows Archive"}


def test_adapter_requires_library_authorization_for_each_write():
    """A permitted user cannot write a library filtered by policy."""
    settings = settings_override(blacklist_libraries=["TV Shows"])
    adapter = object.__new__(JellyfinEmby)
    adapter.app_settings = settings
    adapter.server_settings = SimpleNamespace(name="jellyfin-main")
    adapter.server_type = "Jellyfin"
    adapter.users = {"alice": "alice-id"}
    adapter.query = lambda _path, _method: {
        "Items": [{"Name": "TV Shows", "Id": "tv-id"}]
    }
    writes: list[str] = []

    def record_write(
        _user_name: str,
        _user_id: str,
        _library_data: LibraryData,
        library_name: str,
        _library_id: str,
        _dryrun: bool,
    ) -> None:
        writes.append(library_name)

    adapter.update_user_watched = record_write

    updated = adapter.update_watched(
        {
            "alice": UserData(
                libraries={"TV Shows": LibraryData(title="TV Shows")}
            )
        },
        "plex-main",
    )

    assert writes == []
    assert updated == {}


def test_jellyfin_watched_includes_played_series_with_zero_aggregate_count():
    """A played custom series is read even when Jellyfin reports a 0/0 aggregate."""
    adapter = object.__new__(JellyfinEmby)
    adapter.app_settings = settings_override()
    adapter.server_type = "Jellyfin"

    show = {
        "Id": "series-id",
        "Name": "Greatest Show Ever (3000)",
        "Path": "/data/custom_tvshows/Greatest Show Ever (3000)",
        "UserData": {
            "Played": True,
            "UnplayedItemCount": 0,
        },
        "RecursiveItemCount": 0,
    }
    responses = iter(
        [
            {"Items": [show]},
            {"Items": []},
            {
                "Items": [
                    {
                        "Name": "S01E02",
                        "Path": "/data/custom_tvshows/Greatest Show Ever (3000)/Season 1/S01E02.mkv",
                        "UserData": {"Played": True},
                    }
                ]
            },
        ]
    )
    adapter.query = lambda _path, _method: next(responses)

    watched = adapter.get_user_library_watched(
        "JellyUser",
        "user-id",
        "tvshows",
        "library-id",
        "Custom TV Shows",
    )

    assert [episode.identifiers.title for episode in watched.series[0].episodes] == [
        "S01E02"
    ]


def test_combine_user_lists_keeps_same_name_identities_separate():
    """User filters resolve same names against the source server identity."""
    settings = settings_override(
        user_mappings=[
            {
                "canonical": "first",
                "aliases": [
                    {"server": "plex-main", "username": "shared"},
                    {"server": "jellyfin-main", "username": "first-jf"},
                ],
            },
            {
                "canonical": "second",
                "aliases": [
                    {"server": "plex-main", "username": "second-plex"},
                    {"server": "jellyfin-main", "username": "shared"},
                ],
            },
        ],
        whitelist_users=["first"],
    )

    combined = combine_user_lists(
        "plex-main",
        "jellyfin-main",
        ["shared"],
        ["first-jf", "shared"],
        settings,
    )

    assert combined == {"shared": ["first-jf"]}


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
