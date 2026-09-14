from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from plexapi.myplex import MyPlexAccount

from conftest import settings_override
from src.library import combine_library_lists
from src.plex import Plex
from src.jellyfin import Jellyfin
from src.emby import Emby
from src.users import combine_user_lists
from src.watched import LibraryData, UserData, WatchedUpdate


def policy_settings(source="a", target="b", *, server_direction=False, **overrides):
    return settings_override(
        plex=[],
        jellyfin=[
            dict(
                name=source,
                baseurl="http://source",
                token="x",
                sync_to=[target] if server_direction else [],
            ),
            dict(name=target, baseurl="http://target", token="x", sync_to=[]),
            # Keep the configuration valid even when the tested pair is disabled.
            dict(name="c", baseurl="http://third", token="x", sync_to=[target]),
        ],
        **overrides,
    )


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "mode,expected",
    [
        ("none", set()),
        ("user", {("alice", "Movies"), ("alice", "Shows")}),
        ("library", {("alice", "Movies"), ("bob", "Movies")}),
        ("both", {("alice", "Movies"), ("alice", "Shows"), ("bob", "Movies")}),
    ],
)
def test_rule_only_directions_add_permissions_independently(reverse, mode, expected):
    source, target = ("b", "a") if reverse else ("a", "b")
    settings = policy_settings(
        source,
        target,
        user_sync_rules=[{"users": ["alice"], "from": source, "to": target}]
        if mode in ("user", "both")
        else [],
        library_sync_rules=[{"libraries": ["Movies"], "from": source, "to": target}]
        if mode in ("library", "both")
        else [],
    )
    actual = {
        (user, library)
        for user in ("alice", "bob")
        for library in ("Movies", "Shows")
        if settings.should_sync_scope(user, library, source, target)
    }
    assert actual == expected
    assert not settings.should_sync_user("alice", target, source)
    assert not settings.should_sync_library("Movies", target, source)


@pytest.mark.parametrize("scope", ["user", "library"])
@pytest.mark.parametrize("filter_kind", ["blacklist", "whitelist"])
@pytest.mark.parametrize("rule_name", ["canonical", "literal", "wildcard"])
@pytest.mark.parametrize("server_direction", [False, True])
def test_matching_rules_override_filters_for_only_their_direction(
    scope, filter_kind, rule_name, server_direction
):
    plural = "users" if scope == "user" else "libraries"
    alias_field = "username" if scope == "user" else "library"
    rule_value = {"canonical": "identity", "literal": "sOuRcE", "wildcard": "*"}[
        rule_name
    ]
    settings = policy_settings(
        server_direction=server_direction,
        **{
            f"{scope}_mappings": [
                {
                    "canonical": "identity",
                    "aliases": [
                        {"server": "a", alias_field: "Source"},
                        {"server": "b", alias_field: "Destination"},
                    ],
                }
            ],
            f"{scope}_sync_rules": [{plural: [rule_value], "from": "a", "to": "b"}],
            f"{filter_kind}_{plural}": ["Source"]
            if filter_kind == "blacklist"
            else ["Other"],
        },
    )
    permits = (
        settings.should_sync_user if scope == "user" else settings.should_sync_library
    )
    assert permits("SOURCE", "a", "b")
    assert not permits("SOURCE", "a", "c")
    assert not permits("Destination", "b", "a")
    if scope == "user":
        assert combine_user_lists("a", "b", ["Source"], ["Destination"], settings) == {
            "source": ["destination"]
        }
    else:
        assert combine_library_lists(
            "a", "b", {"Source": "movie"}, {"Destination": "movies"}, settings
        ) == {"Source": ["Destination"]}


@pytest.mark.parametrize("filter_kind", ["blacklist", "whitelist"])
@pytest.mark.parametrize("blocked_endpoint", ["source", "target"])
def test_library_exception_overrides_endpoint_type_filters(
    filter_kind, blocked_endpoint
):
    settings = policy_settings(
        **{
            "library_sync_rules": [{"libraries": ["Movies"], "from": "a", "to": "b"}],
            f"{filter_kind}_library_types": ["show"]
            if filter_kind == "blacklist"
            else ["movie"],
        }
    )
    source_type, target_type = (
        ("show", "movie") if blocked_endpoint == "source" else ("movie", "show")
    )
    assert combine_library_lists(
        "a", "b", {"Movies": source_type}, {"Movies": target_type}, settings
    ) == {"Movies": ["Movies"]}
    assert not settings.should_sync_library(
        "Movies", "c", "b", library_type=source_type, target_library_type=target_type
    )


@pytest.mark.parametrize(
    "filter_field,values,scope",
    [
        ("blacklist_libraries", ["Movies"], "user"),
        ("whitelist_libraries", ["Shows"], "user"),
        ("blacklist_library_types", ["movies"], "user"),
        ("whitelist_library_types", ["tvshows"], "user"),
        ("blacklist_users", ["alice"], "library"),
        ("whitelist_users", ["bob"], "library"),
    ],
)
def test_rule_exception_does_not_override_other_scopes_filters(
    filter_field, values, scope
):
    field, names = (
        ("users", ["alice"]) if scope == "user" else ("libraries", ["Movies"])
    )
    settings = policy_settings(
        **{
            f"{scope}_sync_rules": [{field: names, "from": "a", "to": "b"}],
            filter_field: values,
        }
    )
    assert not settings.should_sync_scope(
        "alice", "Movies", "a", "b", library_type="movies"
    )


@pytest.mark.parametrize("filter_kind", ["blacklist", "whitelist"])
def test_matching_user_and_library_exceptions_add_filtered_library(filter_kind):
    settings = policy_settings(
        **{
            "user_sync_rules": [{"users": ["alice"], "from": "a", "to": "b"}],
            "library_sync_rules": [{"libraries": ["Movies"], "from": "a", "to": "b"}],
            f"{filter_kind}_users": ["alice"]
            if filter_kind == "blacklist"
            else ["bob"],
            f"{filter_kind}_libraries": ["Movies"]
            if filter_kind == "blacklist"
            else ["Shows"],
            "blacklist_library_types": ["movies"],
        }
    )
    assert settings.should_sync_scope(
        "alice",
        "Shows",
        "a",
        "b",
        library_type="tvshows",
        target_library_type="tvshows",
    )
    assert settings.should_sync_scope(
        "alice", "Movies", "a", "b", library_type="movies"
    )
    assert settings.should_sync_scope("bob", "Movies", "a", "b", library_type="movies")
    assert not settings.should_sync_scope(
        "bob", "Shows", "a", "b", library_type="tvshows", target_library_type="tvshows"
    )


def test_rules_on_another_direction_do_not_restrict_missing_scope():
    settings = policy_settings(
        user_sync_rules=[{"users": ["alice"], "from": "a", "to": "b"}],
        library_sync_rules=[{"libraries": ["Shows"], "from": "b", "to": "a"}],
    )
    assert settings.should_sync_library("Movies", "a", "b")
    assert settings.should_sync_user("bob", "b", "a")


def test_server_defaults_remain_additive_and_filters_still_apply_without_match():
    settings = policy_settings(
        server_direction=True,
        user_sync_rules=[{"users": ["alice"], "from": "a", "to": "b"}],
        library_sync_rules=[{"libraries": ["Movies"], "from": "a", "to": "b"}],
        blacklist_users=["blocked"],
        blacklist_libraries=["Blocked"],
    )
    assert settings.should_sync_user("bob", "a", "b")
    assert settings.should_sync_library("Shows", "a", "b")
    assert not settings.should_sync_user("blocked", "a", "b")
    assert not settings.should_sync_library("Blocked", "a", "b")


def test_overrides_preserve_mapping_ownership_and_missing_aliases():
    settings = policy_settings(
        user_sync_rules=[{"users": ["*"], "from": "a", "to": "b"}],
        library_sync_rules=[{"libraries": ["*"], "from": "a", "to": "b"}],
        blacklist_users=["shared"],
        blacklist_libraries=["Shared"],
        user_mappings=[
            {"canonical": "owner", "aliases": [{"server": "b", "username": "shared"}]}
        ],
        library_mappings=[
            {"canonical": "owned", "aliases": [{"server": "b", "library": "Shared"}]}
        ],
    )
    assert combine_user_lists("a", "b", ["shared"], ["shared"], settings) == {}
    assert (
        combine_library_lists(
            "a", "b", {"Shared": "movie"}, {"Shared": "movies"}, settings
        )
        == {}
    )
    assert combine_user_lists("a", "b", ["alice"], [], settings) == {}
    assert combine_library_lists("a", "b", {"Movies": "movie"}, {}, settings) == {}


@pytest.mark.parametrize("adapter", [Plex, Jellyfin, Emby])
@pytest.mark.parametrize("representation", ["dictionary", "updates"])
@pytest.mark.parametrize(
    "username,library,allowed",
    [
        ("alice", "Movies", True),
        ("alice", "Shows", True),
        ("bob", "Movies", True),
        ("bob", "Shows", False),
    ],
)
def test_adapter_authorizes_additive_rules_for_the_concrete_pair(
    adapter, representation, username, library, allowed
):
    settings = policy_settings(
        user_sync_rules=[{"users": ["alice"], "from": "a", "to": "b"}],
        library_sync_rules=[{"libraries": ["Movies"], "from": "a", "to": "b"}],
        blacklist_users=["alice"],
        blacklist_libraries=["Movies"],
    )
    target = object.__new__(adapter)
    target.app_settings = settings
    target.server_settings = settings.jellyfin[1]
    target.server_type = adapter.__name__
    if adapter is Plex:
        user = Mock(spec=MyPlexAccount, username=username, title=username)
        target.users = [user]
        target.admin_user = user
        target.plex = Mock()
        target.plex.library.sections.return_value = [SimpleNamespace(title=library)]
    else:
        target.users = {username: "user-id"}
        target.query = Mock(
            return_value={"Items": [{"Name": library, "Id": "library-id"}]}
        )
    target.update_user_watched = Mock(return_value=[])
    data = LibraryData(title=library)
    payload = (
        {username: UserData(libraries={library: data})}
        if representation == "dictionary"
        else [
            WatchedUpdate(
                source_user=username,
                target_user=username,
                source_library=library,
                target_library=library,
                library_data=data,
            )
        ]
    )
    target.update_watched(payload, "a")
    assert target.update_user_watched.call_count == int(allowed)


@pytest.mark.parametrize(
    "filter_name,values",
    [
        ("whitelist_library_types", ["movie", "movies"]),
        ("blacklist_library_types", ["show", "tvshows"]),
    ],
)
@pytest.mark.parametrize(
    "source_type,target_type",
    [
        (None, "movies"),
        ("movie", None),
        ("", "movies"),
        ("movie", []),
    ],
)
def test_type_filters_reject_unknown_endpoints(
    filter_name, values, source_type, target_type
):
    settings = policy_settings(server_direction=True, **{filter_name: values})
    assert not settings.should_sync_library(
        "Movies", "a", "b", library_type=source_type, target_library_type=target_type
    )


def test_missing_types_still_allow_unfiltered_defaults_and_library_overrides():
    settings = policy_settings(server_direction=True)
    assert settings.should_sync_library("Movies", "a", "b")
    settings = policy_settings(
        whitelist_library_types=["movies"],
        library_sync_rules=[{"libraries": ["Movies"], "from": "a", "to": "b"}],
    )
    assert settings.should_sync_library("Movies", "a", "b")


@pytest.mark.parametrize("adapter", [Plex, Jellyfin, Emby])
@pytest.mark.parametrize("representation", ["dictionary", "updates"])
@pytest.mark.parametrize(
    "source_type,destination_kind,allowed",
    [
        ("movie", "allowed", True),
        ("movie", "blocked", False),
        ("movie", "missing", False),
        (None, "allowed", False),
    ],
)
def test_adapter_checks_resolved_native_type_before_writing(
    adapter, representation, source_type, destination_kind, allowed
):
    settings = policy_settings(
        user_sync_rules=[{"users": ["alice"], "from": "a", "to": "b"}],
        whitelist_library_types=["movie", "movies"],
    )
    target = object.__new__(adapter)
    target.app_settings = settings
    target.server_settings = settings.jellyfin[1]
    target.server_type = adapter.__name__
    if adapter is Plex:
        native_type = {"allowed": "movie", "blocked": "show", "missing": None}[
            destination_kind
        ]
        user = Mock(spec=MyPlexAccount, username="alice", title="Alice")
        target.users = [user]
        target.admin_user = user
        target.plex = Mock()
        target.plex.library.sections.return_value = [
            SimpleNamespace(title="Other", type="movie"),
            SimpleNamespace(title="Movies", type=native_type),
        ]
    else:
        native_type = {"allowed": "movies", "blocked": "tvshows", "missing": None}[
            destination_kind
        ]
        target.users = {"alice": "user-id"}
        target.query = Mock(
            return_value={
                "Items": [
                    {"Name": "Other", "Id": "other-id", "CollectionType": "movies"},
                    {
                        "Name": "Movies",
                        "Id": "movies-id",
                        "CollectionType": native_type,
                    },
                ]
            }
        )
    target.update_user_watched = Mock(return_value=[])
    data = LibraryData(title="Movies", library_type=source_type)
    payload = (
        {"alice": UserData(libraries={"Movies": data})}
        if representation == "dictionary"
        else [
            WatchedUpdate(
                source_user="alice",
                target_user="alice",
                source_library="Movies",
                target_library="Movies",
                library_data=data,
            )
        ]
    )
    target.update_watched(payload, "a")
    assert target.update_user_watched.call_count == int(allowed)
