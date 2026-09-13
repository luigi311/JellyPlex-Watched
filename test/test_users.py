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
    WatchedWriteOutcome,
    cleanup_watched,
    merge_destination_watched,
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
        library_data: LibraryData,
        library_name: str,
        library_id: str,
        _dryrun: bool,
    ) -> list[WatchedWriteOutcome]:
        jellyfin_calls.append((user_name, user_id, library_name))
        return [
            WatchedWriteOutcome(
                status="applied",
                target_user=user_name,
                target_library=library_name,
                media_item=library_data.movies[0],
                target_user_id=user_id,
                target_library_id=library_id,
            )
        ]

    jellyfin_adapter.update_user_watched = record_jellyfin_write
    jellyfin_updated = jellyfin_adapter.update_watched(pending, "plex-main")

    assert sorted(jellyfin_calls) == [
        ("alice", "alice-id", "Shows Archive"),
        ("bob", "bob-id", "Shows"),
        ("bob", "bob-id", "Shows Archive"),
    ]
    assert sorted(
        (outcome.target_user, outcome.target_library)
        for outcome in jellyfin_updated
        if outcome.status == "applied"
    ) == [
        ("alice", "Shows Archive"),
        ("bob", "Shows"),
        ("bob", "Shows Archive"),
    ]

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
        library_data: LibraryData,
        library_name: str,
        _dryrun: bool,
    ) -> list[WatchedWriteOutcome]:
        plex_calls.append((plex_user.username, library_name))
        return [
            WatchedWriteOutcome(
                status="applied",
                target_user=plex_user.username,
                target_library=library_name,
                media_item=library_data.movies[0],
            )
        ]

    plex_adapter.update_user_watched = record_plex_write
    plex_updated = plex_adapter.update_watched(pending, "plex-main")

    assert sorted(plex_calls) == [
        ("alice", "Shows Archive"),
        ("bob", "Shows"),
        ("bob", "Shows Archive"),
    ]
    assert sorted(
        (outcome.target_user, outcome.target_library)
        for outcome in plex_updated
        if outcome.status == "applied"
    ) == [
        ("alice", "Shows Archive"),
        ("bob", "Shows"),
        ("bob", "Shows Archive"),
    ]


def test_jellyfin_receipt_contains_only_confirmed_item_writes(tmp_path):
    """Failed, unsupported, and absent items never enter the write receipt."""
    settings = settings_override(
        dryrun=False,
        mark_file=tmp_path / "mark.log",
    )
    adapter = object.__new__(JellyfinEmby)
    adapter.app_settings = settings
    adapter.server_type = "Jellyfin"
    adapter.server_name = "Jellyfin CI"
    adapter.update_partial = False

    def movie(title: str, filename: str, completed: bool = True) -> MediaItem:
        return MediaItem(
            identifiers=MediaIdentifiers(title=title, locations=(filename,)),
            status=WatchedStatus(
                completed=completed,
                time=300_000 if not completed else 0,
                viewed_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        )

    library_data = LibraryData(
        title="Movies",
        movies=[
            movie("Applied", "applied.mkv"),
            movie("Failed", "failed.mkv"),
            movie("Applied after failure", "after-failure.mkv"),
            movie("Unsupported", "unsupported.mkv", completed=False),
            movie("Absent", "absent.mkv"),
        ],
    )
    destination_items = [
        {
            "Name": "Applied",
            "Id": "applied-id",
            "Path": "/media/applied.mkv",
            "ProviderIds": {},
        },
        {
            "Name": "Failed",
            "Id": "failed-id",
            "Path": "/media/failed.mkv",
            "ProviderIds": {},
        },
        {
            "Name": "Applied after failure",
            "Id": "after-failure-id",
            "Path": "/media/after-failure.mkv",
            "ProviderIds": {},
        },
        {
            "Name": "Unsupported",
            "Id": "unsupported-id",
            "Path": "/media/unsupported.mkv",
            "ProviderIds": {},
        },
    ]
    posted_ids: list[str] = []

    def query(path: str, query_type: str, **_kwargs):
        if query_type == "get":
            return {"Items": destination_items}
        item_id = path.split("/Items/", 1)[1].split("/", 1)[0]
        if item_id == "failed-id":
            raise RuntimeError("simulated write failure")
        posted_ids.append(item_id)
        return None

    adapter.query = query
    outcomes = adapter.update_user_watched(
        "alice",
        "alice-id",
        library_data,
        "Movies",
        "movies-id",
        False,
    )

    assert [
        (outcome.status, outcome.target_item_id)
        for outcome in outcomes
    ] == [
        ("applied", "applied-id"),
        ("failed", "failed-id"),
        ("applied", "after-failure-id"),
        ("unsupported", "unsupported-id"),
        ("skipped", None),
    ]
    assert posted_ids == ["applied-id", "after-failure-id"]
    applied = [outcome for outcome in outcomes if outcome.status == "applied"]
    assert [outcome.media_item.identifiers.title for outcome in applied] == [
        "Applied",
        "Applied after failure",
    ]
    assert all(outcome.media_item.status.completed for outcome in applied)
    assert all(outcome.media_item.status.time == 0 for outcome in applied)


def test_destination_receipts_do_not_remap_crossed_identities():
    """A destination receipt updates its concrete target cache entry only."""
    settings = settings_override(
        user_mappings=[
            {
                "canonical": "alice-source",
                "aliases": [
                    {"server": "plex-main", "username": "alice"},
                    {"server": "jellyfin-main", "username": "bob"},
                ],
            },
            {
                "canonical": "charlie-source",
                "aliases": [
                    {"server": "plex-main", "username": "charlie"},
                    {"server": "jellyfin-main", "username": "alice"},
                ],
            },
        ],
        library_mappings=[
            {
                "canonical": "shows",
                "aliases": [
                    {"server": "plex-main", "library": "TV Shows"},
                    {"server": "jellyfin-main", "library": "Shows"},
                ],
            }
        ],
    )
    movie = MediaItem(
        identifiers=MediaIdentifiers(
            title="Destination movie",
            locations=("destination.mkv",),
        ),
        status=WatchedStatus(
            completed=True,
            time=0,
            viewed_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )
    cache = {
        "alice": UserData(
            libraries={"Shows": LibraryData(title="Shows")}
        ),
        "charlie": UserData(
            libraries={"Shows": LibraryData(title="Shows")}
        ),
    }
    receipt = WatchedWriteOutcome(
        status="applied",
        target_user="alice",
        target_library="Shows",
        media_item=movie,
        target_user_id="alice-id",
        target_library_id="shows-id",
        target_item_id="movie-id",
    )
    second_movie = movie.model_copy(
        update={
            "identifiers": MediaIdentifiers(
                title="Second destination movie",
                locations=("second-destination.mkv",),
            )
        }
    )
    second_receipt = WatchedWriteOutcome(
        status="applied",
        target_user="alice",
        target_library="Shows",
        media_item=second_movie,
        target_user_id="alice-id",
        target_library_id="shows-id",
        target_item_id="second-movie-id",
    )

    merged = merge_destination_watched(
        cache,
        [receipt, second_receipt],
        settings,
        average_time=0.0,
    )

    assert [
        item.identifiers.title for item in merged["alice"].libraries["Shows"].movies
    ] == ["Destination movie", "Second destination movie"]
    assert merged["charlie"].libraries["Shows"].movies == []

    unknown_receipt = WatchedWriteOutcome(
        status=receipt.status,
        target_user="missing",
        target_library=receipt.target_library,
        media_item=receipt.media_item,
        series_identifiers=receipt.series_identifiers,
        target_user_id=receipt.target_user_id,
        target_library_id=receipt.target_library_id,
        target_item_id=receipt.target_item_id,
        reason=receipt.reason,
    )
    merged_with_unknown = merge_destination_watched(
        cache,
        [unknown_receipt],
        settings,
        average_time=0.0,
    )
    assert "missing" not in merged_with_unknown


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
    assert updated == []


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
