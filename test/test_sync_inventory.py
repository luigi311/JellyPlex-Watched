from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from plexapi.myplex import MyPlexUser

from conftest import settings_override
from src.emby import Emby
from src.jellyfin import Jellyfin
from src.plex import Plex
from src.sync_inventory import generate_sync_inventory
from src.users import generate_all_server_users


@pytest.mark.parametrize("reverse", [False, True])
def test_inventory_retains_accessible_fanout_and_fetches_once(reverse):
    settings = settings_override(
        plex=[
            dict(
                name="plex-main",
                baseurl="http://plex",
                token="x",
                sync_to=[] if reverse else ["jellyfin-main"],
            )
        ],
        jellyfin=[
            dict(
                name="jellyfin-main",
                baseurl="http://jf",
                token="x",
                sync_to=["plex-main"] if reverse else [],
            )
        ],
        user_mappings=[
            dict(
                canonical="family",
                aliases=[
                    dict(server="plex-main", username="Family"),
                    dict(server="jellyfin-main", username="Alice"),
                    dict(server="jellyfin-main", username="Bob"),
                ],
            )
        ],
        library_mappings=[
            dict(
                canonical="shows",
                aliases=[
                    dict(server="plex-main", library="TV"),
                    dict(server="jellyfin-main", library="Shows"),
                    dict(server="jellyfin-main", library="Archive"),
                ],
            )
        ],
        blacklist_libraries=["Blocked"],
    )
    plex = object.__new__(Plex)
    plex.server_settings = settings.plex[0]
    user = SimpleNamespace(username=None, title="FAMILY")
    plex.users = [user]
    plex.get_user_libraries = Mock(return_value={"TV": "show", "Blocked": "movie"})
    jf = object.__new__(Jellyfin)
    jf.server_settings = settings.jellyfin[0]
    jf.users = {"Alice": "a", "Bob": "b"}
    jf.get_user_libraries = Mock(
        side_effect=[
            {"Shows": "tvshows", "Archive": "tvshows", "Blocked": "movies"},
            {"Unrelated": "movies"},
        ]
    )
    empty = object.__new__(Emby)
    empty.server_settings = SimpleNamespace(name="empty")
    empty.users = {}
    empty.get_user_libraries = Mock()
    result = generate_sync_inventory(
        generate_all_server_users([plex, jf, empty], settings), settings
    )
    assert list(result) == [plex, jf]
    assert result[plex][0].user is user
    assert result[plex][0].libraries == {"TV": "show"}
    assert len(result[jf]) == 1
    assert result[jf][0].user == ("Alice", "a")
    assert result[jf][0].libraries == {"Shows": "tvshows", "Archive": "tvshows"}
    plex.get_user_libraries.assert_called_once_with(user)
    assert jf.get_user_libraries.call_count == 2
    empty.get_user_libraries.assert_not_called()


@pytest.mark.parametrize("same_direction", [False, True])
def test_user_and_library_rules_must_allow_same_direction(same_direction):
    settings = settings_override(
        plex=[dict(name="plex-main", baseurl="http://plex", token="x", sync_to=[])],
        jellyfin=[
            dict(name="jellyfin-main", baseurl="http://jf", token="x", sync_to=[])
        ],
        user_sync_rules=[
            {"users": ["alice"], "from": "plex-main", "to": "jellyfin-main"}
        ],
        library_sync_rules=[
            {
                "libraries": ["Movies"],
                "from": "plex-main" if same_direction else "jellyfin-main",
                "to": "jellyfin-main" if same_direction else "plex-main",
            }
        ],
    )
    servers = []
    for name in ["plex-main", "jellyfin-main"]:
        server = object.__new__(Jellyfin)
        server.server_settings = SimpleNamespace(name=name)
        server.users = {"alice": "a"}
        server.get_user_libraries = Mock(return_value={"Movies": "movies"})
        servers.append(server)
    result = generate_sync_inventory(
        generate_all_server_users(servers, settings), settings
    )
    assert bool(result) is same_direction


def test_jellyfin_library_discovery_is_user_scoped_and_handles_custom_types():
    server = object.__new__(Jellyfin)
    server.server_type = "Jellyfin"
    server.query = Mock(
        side_effect=[
            {
                "Items": [
                    {"Name": "Movies", "Id": "m", "CollectionType": "movies"},
                    {"Name": "Custom", "Id": "c"},
                    {"Name": "Music", "Id": "s", "CollectionType": "music"},
                ]
            },
            {"Items": [{"Type": "Episode"}]},
        ]
    )
    assert server.get_user_libraries(("alice", "a")) == {
        "Movies": "movies",
        "Custom": "tvshows",
    }
    assert server.query.call_args_list[0].args == ("/Users/a/Views", "get")
    assert "/Users/a/Items?ParentId=c" in server.query.call_args_list[1].args[0]


def test_plex_library_discovery_uses_shared_user_access():
    server = object.__new__(Plex)
    server.admin_user = object()
    server.plex = SimpleNamespace(machineIdentifier="server")
    server.base_url = "http://plex"
    user = Mock(spec=MyPlexUser)
    user.get_token.return_value = "test-token"
    sections = Mock(return_value=[SimpleNamespace(title="Shared", type="movie")])
    server.login = Mock(
        return_value=SimpleNamespace(library=SimpleNamespace(sections=sections))
    )
    assert server.get_user_libraries(user) == {"Shared": "movie"}
    server.login.assert_called_once_with("http://plex", "test-token", None, None, None)
    user.get_token.return_value = None
    assert server.get_user_libraries(user) == {}


@pytest.mark.parametrize("failure_stage", ["token", "login", "sections"])
def test_discovery_failure_does_not_discard_healthy_scopes(failure_stage):
    settings = settings_override()
    plex = object.__new__(Plex)
    plex.server_settings = settings.plex[0]
    plex.admin_user = object()
    plex.plex = SimpleNamespace(machineIdentifier="server")
    plex.base_url = "http://plex"
    failed = Mock(spec=MyPlexUser, username="failed")
    healthy = Mock(spec=MyPlexUser, username="healthy")
    failed.get_token.return_value = "failed-token"
    healthy.get_token.return_value = "healthy-token"
    good_sections = Mock(return_value=[SimpleNamespace(title="Movies", type="movie")])
    bad_sections = Mock(side_effect=RuntimeError("discovery failed"))

    def login(_url, token, *_args):
        if token == "failed-token" and failure_stage == "login":
            raise RuntimeError("login failed")
        sections = bad_sections if token == "failed-token" else good_sections
        return SimpleNamespace(library=SimpleNamespace(sections=sections))

    plex.login = Mock(side_effect=login)
    if failure_stage == "token":
        failed.get_token.side_effect = RuntimeError("token failed")
    jf = object.__new__(Jellyfin)
    jf.server_settings = settings.jellyfin[0]
    jf.get_user_libraries = Mock(return_value={"Movies": "movies"})
    result = generate_sync_inventory(
        {plex: [failed, healthy], jf: [("healthy", "h")]}, settings
    )
    assert result[plex][0].user is healthy
    assert len(result[plex]) == 1
    assert result[jf][0].libraries == {"Movies": "movies"}
    jf.get_user_libraries.assert_called_once_with(("healthy", "h"))


def test_server_library_discovery_preserves_results_after_user_failure():
    server = object.__new__(Jellyfin)
    server.users = {"first": "1", "failed": "2", "last": "3"}
    server.get_user_libraries = Mock(
        side_effect=[
            {"Movies": "movies"},
            RuntimeError("discovery failed"),
            {"Shows": "tvshows"},
        ]
    )
    assert server.get_libraries() == {"Movies": "movies", "Shows": "tvshows"}
    assert server.get_user_libraries.call_count == 3
