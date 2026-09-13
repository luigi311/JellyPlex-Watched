from unittest.mock import Mock

import pytest
from plexapi.myplex import MyPlexUser

from src.emby import Emby
from src.jellyfin import Jellyfin
from src.plex import Plex
from src.sync_inventory import UserLibraries, fetch_watched_inventory
from src.watched import LibraryData, UserData


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
    assert result == {server: {"alice": alice, "bob": bob}}
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
    second_data = UserData()
    first.get_watched = Mock(return_value={"alice": first_data})
    second.get_watched = Mock(return_value={"alice": second_data})
    entry = UserLibraries(user, {"Movies": "movie"})
    assert fetch_watched_inventory({first: [entry], second: [entry]}) == {
        first: {"alice": first_data},
        second: {"alice": second_data},
    }
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
    assert result[server]["alice"].libraries == {"Custom": data}
    server.get_user_library_watched.assert_called_once_with(
        "Alice", "a", "tvshows", "c", "Custom"
    )
