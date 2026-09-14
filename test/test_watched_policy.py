from datetime import datetime, timezone

import pytest

from conftest import settings_override
from src.watched import (
    LibraryData,
    MediaIdentifiers,
    MediaItem,
    UserData,
    WatchedStatus,
    cleanup_watched,
)


@pytest.mark.parametrize("scope", ["library", "user"])
@pytest.mark.parametrize("reverse", [False, True])
def test_fanin_authorizes_each_source_before_coalescing(scope, reverse):
    source, target = (
        ("jellyfin-main", "plex-main") if reverse else ("plex-main", "jellyfin-main")
    )
    mapping = [
        {"server": source, scope if scope == "library" else "username": name}
        for name in ["Allowed", "Restricted"]
    ] + [
        {"server": target, scope if scope == "library" else "username": "Merged"},
        {"server": "third", scope if scope == "library" else "username": "Merged"},
    ]
    settings = settings_override(
        plex=[dict(name="plex-main", baseurl="http://plex", token="x", sync_to=[])],
        jellyfin=[
            dict(name="jellyfin-main", baseurl="http://jf", token="x", sync_to=[]),
            dict(name="third", baseurl="http://third", token="x", sync_to=[]),
        ],
        **{
            f"{scope}_mappings": [dict(canonical="combined", aliases=mapping)],
            f"{scope}_sync_rules": [
                {
                    ("libraries" if scope == "library" else "users"): ["Allowed"],
                    "from": source,
                    "to": target,
                },
                {
                    ("libraries" if scope == "library" else "users"): ["*"],
                    "from": source,
                    "to": "third",
                },
            ],
        },
    )
    watched = {}
    for name in ["Allowed", "Restricted"]:
        username = name if scope == "user" else "alice"
        library = name if scope == "library" else "Movies"
        watched.setdefault(username, UserData()).libraries[library] = LibraryData(
            title=library,
            movies=[
                MediaItem(
                    identifiers=MediaIdentifiers(
                        title=name, locations=(name + ".mkv",)
                    ),
                    status=WatchedStatus(
                        completed=True,
                        time=0,
                        viewed_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    ),
                )
            ],
        )
    for destination, expected in [
        (target, ["Allowed"]),
        ("third", ["Allowed", "Restricted"]),
    ]:
        pending = cleanup_watched(watched, {}, source, destination, settings, 0.0)
        assert len(pending) == 1
        assert [
            movie.identifiers.title for movie in pending[0].library_data.movies
        ] == expected
