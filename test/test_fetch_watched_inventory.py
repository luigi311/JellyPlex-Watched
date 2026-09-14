from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from plexapi.myplex import MyPlexUser

from src.emby import Emby
from src.jellyfin import Jellyfin
from src.plex import Plex
from src.sync_inventory import UserLibraries, fetch_watched_inventory
from conftest import settings_override
from src.watched import (
    LibraryData,
    UserData,
    MediaItem,
    MediaIdentifiers,
    WatchedStatus,
    cleanup_watched,
)


@pytest.mark.parametrize("adapter_type", [Jellyfin, Emby])
def test_fetch_uses_each_users_libraries_and_preserves_results_on_failure(adapter_type):
    server = object.__new__(adapter_type)
    alice = UserData(libraries={"Movies": LibraryData(title="Movies")})
    bob = UserData(libraries={"Shows": LibraryData(title="Shows")})
    server.get_watched = Mock(side_effect=[{"alice": alice}, {}, {"bob": bob}])
    result = fetch_watched_inventory(
        {
            server: [
                UserLibraries(("Alice", "a"), {"Movies": "movies"}),
                UserLibraries(("Failed", "f"), {"Movies": "movies"}),
                UserLibraries(("Bob", "b"), {"Shows": "tvshows"}),
                UserLibraries(("Empty", "e"), {}),
            ]
        }
    )
    assert set(result[server]) == {"alice", "bob"}
    assert result[server]["alice"].libraries["Movies"] == alice.libraries[
        "Movies"
    ].model_copy(update={"library_type": "movies"})
    assert result[server]["bob"].libraries["Shows"].library_type == "tvshows"
    assert alice.libraries["Movies"].library_type is None
    assert server.get_watched.call_count == 3
    assert server.get_watched.call_args_list[0].args == ({"Alice": "a"}, ["Movies"])
    assert server.get_watched.call_args_list[2].args == ({"Bob": "b"}, ["Shows"])
    assert server.get_watched.call_args_list[2].kwargs == {
        "library_types": {"Shows": "tvshows"}
    }


def test_fetch_keeps_servers_separate_and_preserves_plex_objects():
    first = object.__new__(Plex)
    second = object.__new__(Plex)
    user = Mock(spec=MyPlexUser, username="alice")
    first_data = UserData(libraries={"Movies": LibraryData(title="Movies")})
    second_data = UserData(libraries={"Movies": LibraryData(title="Movies")})
    first.get_watched = Mock(return_value={"alice": first_data})
    second.get_watched = Mock(return_value={"alice": second_data})
    entry = UserLibraries(user, {"Movies": "movie"})
    result = fetch_watched_inventory({first: [entry], second: [entry]})
    assert set(result) == {first, second}
    for server in (first, second):
        assert result[server]["alice"].libraries["Movies"].library_type == "movie"
    assert result[first]["alice"] is not result[second]["alice"]
    first.get_watched.assert_called_once_with([user], ["Movies"])
    second.get_watched.assert_called_once_with([user], ["Movies"])
    assert fetch_watched_inventory({}) == {}


def test_custom_library_uses_discovered_type_and_only_selected_history_is_fetched():
    server = object.__new__(Jellyfin)
    server.server_type = "Jellyfin"
    server.query = Mock(
        return_value={
            "Items": [
                {"Name": "Custom", "Id": "c"},
                {"Name": "Unselected", "Id": "u", "CollectionType": "movies"},
            ]
        }
    )
    data = LibraryData(title="Custom")
    server.get_user_library_watched = Mock(return_value=data)
    result = fetch_watched_inventory(
        {
            server: [
                UserLibraries(("Alice", "a"), {"Custom": "tvshows"}),
            ]
        }
    )
    assert result[server]["alice"].libraries == {
        "Custom": data.model_copy(update={"library_type": "tvshows"})
    }
    server.get_user_library_watched.assert_called_once_with(
        "Alice", "a", "tvshows", "c", "Custom"
    )


@pytest.mark.parametrize("failure", [None, RuntimeError("read failed")])
def test_unknown_destination_is_skipped_but_empty_history_is_updated(failure):

    server = object.__new__(Jellyfin)
    server.server_type = "Jellyfin"
    server.query = Mock(
        return_value={
            "Items": [{"Name": "Movies", "Id": "m", "CollectionType": "movies"}]
        }
    )
    server.get_user_library_watched = Mock(
        side_effect=[failure, LibraryData(title="Movies")]
    )
    fetched = fetch_watched_inventory(
        {
            server: [
                UserLibraries(("failed", "f"), {"Movies": "movies"}),
                UserLibraries(("healthy", "h"), {"Movies": "movies"}),
            ]
        }
    )[server]
    assert set(fetched) == {"healthy"}
    movie = MediaItem(
        identifiers=MediaIdentifiers(title="Movie"),
        status=WatchedStatus(
            completed=True,
            time=0,
            viewed_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )
    source = {
        name: UserData(
            libraries={"Movies": LibraryData(title="Movies", movies=[movie])}
        )
        for name in ["failed", "healthy"]
    }
    pending = cleanup_watched(
        source,
        fetched,
        "plex-main",
        "jellyfin-main",
        settings_override(),
        0.0,
        require_destination_scope=True,
    )
    assert [update.target_user for update in pending] == ["healthy"]


@pytest.mark.parametrize("response", [None, {}, {"Items": []}])
def test_jellyfin_empty_history_is_distinct_from_invalid_response(response):
    server = object.__new__(Jellyfin)
    server.server_type = "Jellyfin"
    server.query = Mock(return_value=response)
    result = server.get_user_library_watched("alice", "a", "movies", "m", "Movies")
    if response == {"Items": []}:
        assert result == LibraryData(title="Movies")
    else:
        assert result is None


def test_plex_failed_library_read_is_not_an_empty_history():
    server = object.__new__(Plex)
    user_plex = Mock()
    library = Mock(title="Movies", type="movie")
    user_plex.library.section.side_effect = RuntimeError("read failed")
    assert server.get_user_library_watched("alice", user_plex, library) is None


def test_missing_selected_library_excludes_incomplete_user():
    server = object.__new__(Jellyfin)
    server.get_watched = Mock(
        return_value={
            "alice": UserData(libraries={"Movies": LibraryData(title="Movies")}),
        }
    )
    assert fetch_watched_inventory(
        {
            server: [
                UserLibraries(("alice", "a"), {"Movies": "movies", "Shows": "tvshows"}),
            ]
        }
    ) == {server: {}}
