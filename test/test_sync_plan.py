from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import permutations
from unittest.mock import Mock

import pytest

from conftest import settings_override
from src import main
from src.jellyfin import Jellyfin
from src.settings import AppSettings
from src.sync_plan import generate_watched_plan
from src.watched import (
    LibraryData,
    MediaIdentifiers,
    MediaItem,
    Series,
    UserData,
    WatchedScope,
    WatchedStatus,
    WatchedWriteOutcome,
    cleanup_watched,
)


def make_settings(directions=None, **overrides):
    if directions is None:
        directions = {
            name: [other for other in "abc" if other != name] for name in "abc"
        }
    return settings_override(
        plex=[],
        jellyfin=[
            dict(name=name, baseurl=f"http://{name}", token="x", sync_to=targets)
            for name, targets in directions.items()
        ],
        **overrides,
    )


def make_servers(settings: AppSettings):
    servers = {}
    for config in settings.jellyfin:
        server = object.__new__(Jellyfin)
        server.server_settings = config
        server.app_settings = settings
        server.server_type = "Jellyfin"
        server.info = Mock(return_value=config.name)
        server.get_watched = Mock(side_effect=AssertionError("Planner must not fetch"))
        server.update_watched = Mock(
            side_effect=AssertionError("Planner must not write")
        )
        servers[config.name] = server
    return servers


def movie(name="shared", *, time=0, completed=True, date=0, **identifiers):
    return MediaItem(
        identifiers=MediaIdentifiers(title=name, imdb_id=name, **identifiers),
        status=WatchedStatus(
            completed=completed,
            time=time,
            viewed_date=datetime(2026, 1, 1, tzinfo=timezone.utc)
            + timedelta(seconds=date),
        ),
    )


def history(*movies, user="alice", library="Movies", series=()):
    return {
        user: UserData(
            libraries={
                library: LibraryData(
                    title=library, movies=list(movies), series=list(series)
                )
            }
        )
    }


def updates_for(plan, server):
    return [update for batch in plan.get(server, {}).values() for update in batch]


def movies_for(plan, server):
    return [
        item
        for update in updates_for(plan, server)
        for item in update.library_data.movies
    ]


@pytest.mark.parametrize("order", list(permutations("abc")))
def test_global_movie_winners_are_unique_and_independent_of_server_order(order):
    settings = make_settings()
    servers = make_servers(settings)
    watched = {
        servers["a"]: history(movie(time=30_000, completed=False), movie("only-a")),
        servers["b"]: history(movie(time=60_000, completed=False), movie("only-b")),
        servers["c"]: history(movie()),
    }
    before = {server: deepcopy(data) for server, data in watched.items()}
    plan = generate_watched_plan(
        {servers[name]: watched[servers[name]] for name in order}, settings, 0
    )
    assert {item.identifiers.title for item in movies_for(plan, servers["a"])} == {
        "shared",
        "only-b",
    }
    assert {item.identifiers.title for item in movies_for(plan, servers["b"])} == {
        "shared",
        "only-a",
    }
    assert {item.identifiers.title for item in movies_for(plan, servers["c"])} == {
        "only-a",
        "only-b",
    }
    for name in "ab":
        shared = [
            item
            for item in movies_for(plan, servers[name])
            if item.identifiers.title == "shared"
        ]
        assert len(shared) == 1
        assert shared[0].status.completed
        assert [
            item.identifiers.title
            for item in plan[servers[name]]["c"][0].library_data.movies
        ] == ["shared"]
    assert watched == before
    # Neither the plan nor another destination shares mutable item objects.
    plan[servers["a"]]["c"][0].library_data.movies[0].status.completed = False
    assert plan[servers["b"]]["c"][0].library_data.movies[0].status.completed
    assert watched == before


@pytest.mark.parametrize("order", list(permutations("abc")))
def test_tied_sources_keep_stable_source_and_native_identifiers(order):
    settings = make_settings({"a": ["c"], "b": ["c"], "c": []})
    servers = make_servers(settings)
    watched = {
        servers["a"]: history(movie(locations=("/a/movie.mkv",))),
        servers["b"]: history(movie(locations=("/b/movie.mkv",))),
        servers["c"]: history(),
    }
    plan = generate_watched_plan(
        {servers[name]: watched[servers[name]] for name in order}, settings, 0
    )
    assert set(plan[servers["c"]]) == {"a"}
    assert movies_for(plan, servers["c"])[0].identifiers.locations == ("/a/movie.mkv",)


@pytest.mark.parametrize(
    "first,second,baseline,expected",
    [
        (movie(), movie(time=60_000, completed=False), None, "a"),
        (movie(), movie(time=60_000, completed=False, date=7200), None, "b"),
        (
            movie(time=30_000, completed=False),
            movie(time=60_000, completed=False),
            None,
            "b",
        ),
        (
            movie(time=30_000, completed=False),
            movie(time=35_000, completed=False),
            None,
            "a",
        ),
        (movie(), movie(), movie(), None),
        # The baseline ties with b (10 s) and b ties with a (10 s), but a
        # beats the baseline (20 s). Compare to the baseline before reducing.
        (
            movie(time=40_000, completed=False),
            movie(time=30_000, completed=False),
            movie(time=20_000, completed=False),
            "a",
        ),
    ],
)
def test_uses_existing_completion_timeline_and_date_comparison(
    first, second, baseline, expected
):
    settings = make_settings({"a": ["c"], "b": ["c"], "c": []})
    servers = make_servers(settings)
    plan = generate_watched_plan(
        {
            servers["a"]: history(first),
            servers["b"]: history(second),
            servers["c"]: history(*([baseline] if baseline else [])),
        },
        settings,
        0,
    )
    if expected is None:
        assert plan == {}
    else:
        assert set(plan[servers["c"]]) == {expected}
        assert len(movies_for(plan, servers["c"])) == 1


def test_episode_winners_keep_their_series_and_source_identity():
    settings = make_settings({"a": ["c"], "b": ["c"], "c": []})
    servers = make_servers(settings)

    def show(name, *episodes):
        return Series(
            identifiers=MediaIdentifiers(tvdb_id="show", title=name),
            episodes=list(episodes),
        )

    plan = generate_watched_plan(
        {
            servers["a"]: history(
                series=[
                    show(
                        "A title",
                        movie("ep1"),
                        movie("ep2", time=30_000, completed=False),
                    )
                ]
            ),
            servers["b"]: history(
                series=[
                    show(
                        "B title",
                        movie("ep1", time=30_000, completed=False),
                        movie("ep2"),
                        movie("ep3"),
                    )
                ]
            ),
            servers["c"]: history(series=[show("C title", movie("ep3"))]),
        },
        settings,
        0,
    )
    batches = plan[servers["c"]]
    assert batches["a"][0].library_data.series == [show("A title", movie("ep1"))]
    assert batches["b"][0].library_data.series == [show("B title", movie("ep2"))]


def test_episode_identifiers_are_scoped_to_their_show():
    settings = make_settings({"a": ["c"], "b": ["c"], "c": []})
    servers = make_servers(settings)
    first = Series(
        identifiers=MediaIdentifiers(tvdb_id="first"), episodes=[movie("ep1")]
    )
    second = Series(
        identifiers=MediaIdentifiers(tvdb_id="second"), episodes=[movie("ep1")]
    )
    plan = generate_watched_plan(
        {
            servers["a"]: history(series=[first]),
            servers["b"]: history(series=[second]),
            servers["c"]: history(series=[first]),
        },
        settings,
        0,
    )
    assert set(plan[servers["c"]]) == {"b"}
    assert plan[servers["c"]]["b"][0].library_data.series == [second]


@pytest.mark.parametrize("reverse", [False, True])
def test_user_and_library_fanout_respects_each_destinations_history(reverse):
    source, target = ("b", "a") if reverse else ("a", "b")
    settings = make_settings(
        {source: [target], target: [], "c": []},
        user_mappings=[
            dict(
                canonical="family",
                aliases=[
                    dict(server=source, username="Family"),
                    dict(server=target, username="Alice"),
                    dict(server=target, username="Bob"),
                ],
            )
        ],
        library_mappings=[
            dict(
                canonical="films",
                aliases=[
                    dict(server=source, library="Films"),
                    dict(server=target, library="Movies"),
                    dict(server=target, library="Archive"),
                ],
            )
        ],
    )
    servers = make_servers(settings)
    watched = {
        servers[source]: history(movie(), user="FAMILY", library="FILMS"),
        servers[target]: {
            "ALICE": UserData(
                libraries={
                    "MOVIES": LibraryData(title="MOVIES", movies=[movie()]),
                    "Archive": LibraryData(title="Archive"),
                }
            ),
            "Bob": UserData(
                libraries={
                    "MOVIES": LibraryData(title="MOVIES"),
                    "Archive": LibraryData(title="Archive"),
                }
            ),
        },
        servers["c"]: history(),
    }
    plan = generate_watched_plan(watched, settings, 0)
    assert set(plan) == {servers[target]}
    assert {
        (update.target_user, update.target_library)
        for update in updates_for(plan, servers[target])
    } == {
        ("ALICE", "Archive"),
        ("Bob", "MOVIES"),
        ("Bob", "Archive"),
    }
    assert all(
        update.source_user == "FAMILY" and update.source_library == "FILMS"
        for update in updates_for(plan, servers[target])
    )


@pytest.mark.parametrize("scope", ["user", "library"])
def test_policy_is_applied_before_global_fanin(scope):
    field = "username" if scope == "user" else "library"
    plural = "users" if scope == "user" else "libraries"
    other_scope, other_plural = (
        ("library", "libraries") if scope == "user" else ("user", "users")
    )
    settings = make_settings(
        {"a": [], "b": ["c"], "c": []},
        **{
            f"{scope}_mappings": [
                dict(
                    canonical="combined",
                    aliases=[
                        {"server": "b", field: "Allowed"},
                        {"server": "b", field: "Restricted"},
                        {"server": "a", field: "Merged"},
                        {"server": "c", field: "Merged"},
                    ],
                )
            ],
            f"{scope}_sync_rules": [{plural: ["Allowed"], "from": "b", "to": "a"}],
            f"{other_scope}_sync_rules": [
                {other_plural: ["*"], "from": "b", "to": "a"}
            ],
        },
    )
    servers = make_servers(settings)
    source = {}
    for name in ["Allowed", "Restricted"]:
        username, library = (name, "Movies") if scope == "user" else ("alice", name)
        source.setdefault(username, UserData()).libraries[library] = LibraryData(
            title=library, movies=[movie(name)]
        )
    kwargs = {"user" if scope == "user" else "library": "Merged"}
    plan = generate_watched_plan(
        {
            servers["a"]: history(**kwargs),
            servers["b"]: source,
            servers["c"]: history(**kwargs),
        },
        settings,
        0,
    )
    assert [item.identifiers.title for item in movies_for(plan, servers["a"])] == [
        "Allowed"
    ]
    assert {item.identifiers.title for item in movies_for(plan, servers["c"])} == {
        "Allowed",
        "Restricted",
    }


def test_missing_destinations_are_unknown_but_empty_libraries_are_valid():
    settings = make_settings({"a": ["b", "c", "d"], "b": [], "c": [], "d": []})
    servers = make_servers(settings)
    plan = generate_watched_plan(
        {
            servers["a"]: history(movie()),
            servers["b"]: {},
            servers["c"]: {"alice": UserData()},
            servers["d"]: history(),
        },
        settings,
        0,
    )
    assert set(plan) == {servers["d"]}
    assert movies_for(plan, servers["d"]) == [movie()]
    assert generate_watched_plan({}, settings, 0) == {}
    assert generate_watched_plan({servers["a"]: history(movie())}, settings, 0) == {}


@pytest.mark.parametrize("dryrun", [False, True])
@pytest.mark.parametrize("receipt", ["applied", "failed", "skipped"])
def test_main_plans_chain_without_waiting_for_intermediate_receipts(
    monkeypatch, dryrun, receipt
):
    settings = make_settings({"a": ["b"], "b": ["c"], "c": []}, dryrun=dryrun)
    servers = make_servers(settings)
    watched = {
        servers["a"]: history(movie()),
        servers["b"]: history(),
        servers["c"]: history(),
    }
    before = {server: deepcopy(data) for server, data in watched.items()}
    monkeypatch.setattr(
        main, "generate_server_connections", Mock(return_value=list(servers.values()))
    )
    monkeypatch.setattr(main, "generate_all_server_users", Mock(return_value={}))
    monkeypatch.setattr(main, "generate_sync_inventory", Mock(return_value={}))
    fetch = Mock(return_value=watched)
    monkeypatch.setattr(main, "fetch_watched_inventory", fetch)
    servers["b"].update_watched = Mock(
        return_value=[
            WatchedWriteOutcome(
                status=receipt,
                target_user="alice",
                target_library="Movies",
                media_item=movie(),
            )
        ]
    )
    servers["c"].update_watched = Mock(return_value=[])
    main.main_loop(settings, 0)
    servers["b"].update_watched.assert_called_once()
    assert servers["b"].update_watched.call_args.args[1] == "a"
    servers["a"].update_watched.assert_not_called()
    servers["c"].update_watched.assert_called_once()
    updates, source = servers["c"].update_watched.call_args.args
    assert source == "b"
    assert updates[0].library_data.movies == [movie()]
    assert updates[0].relay_path == tuple(
        WatchedScope(name, "alice", "Movies") for name in "abc"
    )
    fetch.assert_called_once()
    assert watched == before


def test_two_server_plan_matches_existing_cleanup():
    settings = make_settings({"a": ["b"], "b": ["a"]})
    servers = make_servers(settings)
    watched = {
        servers["a"]: history(movie(), movie("partial", time=30_000, completed=False)),
        servers["b"]: history(
            movie(time=30_000, completed=False),
            movie("partial", time=60_000, completed=False),
            movie("unique"),
        ),
    }
    plan = generate_watched_plan(watched, settings, 0)
    for source, target in [("a", "b"), ("b", "a")]:
        assert plan[servers[target]][source] == cleanup_watched(
            watched[servers[source]],
            watched[servers[target]],
            source,
            target,
            settings,
            0,
            require_destination_scope=True,
        )


def test_each_destination_uses_only_its_permitted_sources():
    settings = make_settings({"a": ["c", "d"], "b": ["d"], "c": [], "d": []})
    servers = make_servers(settings)
    partial = movie(time=30_000, completed=False)
    plan = generate_watched_plan(
        {
            servers["a"]: history(partial),
            servers["b"]: history(movie()),
            servers["c"]: history(),
            servers["d"]: history(),
        },
        settings,
        0,
    )
    assert movies_for(plan, servers["c"]) == [partial]
    assert movies_for(plan, servers["d"]) == [movie()]


def test_existing_adapter_receives_each_winner_with_its_own_source_mapping():
    settings = make_settings(
        {"a": ["c"], "b": ["c"], "c": []},
        user_mappings=[
            dict(
                canonical="family",
                aliases=[
                    dict(server="a", username="First"),
                    dict(server="b", username="Second"),
                    dict(server="c", username="Destination"),
                ],
            )
        ],
        library_mappings=[
            dict(
                canonical="films",
                aliases=[
                    dict(server="a", library="First Library"),
                    dict(server="b", library="Second Library"),
                    dict(server="c", library="Destination Library"),
                ],
            )
        ],
    )
    servers = make_servers(settings)
    plan = generate_watched_plan(
        {
            servers["a"]: history(
                movie(time=30_000, completed=False),
                movie("only-a"),
                user="First",
                library="First Library",
            ),
            servers["b"]: history(movie(), user="Second", library="Second Library"),
            servers["c"]: history(user="Destination", library="Destination Library"),
        },
        settings,
        0,
    )
    target = servers["c"]
    target.users = {"Destination": "user-id"}
    target.query = Mock(
        return_value={"Items": [{"Name": "Destination Library", "Id": "library-id"}]}
    )
    target.update_user_watched = Mock(return_value=[])
    for source, updates in plan[target].items():
        Jellyfin.update_watched(target, updates, source)
    assert target.update_user_watched.call_count == 2
    items = []
    for call in target.update_user_watched.call_args_list:
        username, user_id, data, library_name, library_id, dryrun = call.args
        assert (username, user_id, library_name, library_id, dryrun) == (
            "Destination",
            "user-id",
            "Destination Library",
            "library-id",
            True,
        )
        items.extend(data.movies)
    assert items == [movie("only-a"), movie()]


@pytest.mark.parametrize("topology", ["direct", "cycle"])
def test_cars_completed_state_reaches_every_server_in_one_plan(topology):
    directions = (
        {name: [other for other in "abcde" if other != name] for name in "abcde"}
        if topology == "direct"
        else {"c": ["a"], "a": ["b"], "b": ["d"], "d": ["e"], "e": ["c"]}
    )
    settings = make_settings(directions)
    servers = make_servers(settings)
    watched = {servers[name]: history() for name in "abcde"}
    watched[servers["a"]] = history(movie("Cars", time=20 * 60_000, completed=False))
    watched[servers["c"]] = history(movie("Cars"))
    # Exhaustively reorder the five inputs, including the cycle's entry point.
    expected = generate_watched_plan(watched, settings, 0)
    for order in permutations("abcde"):
        plan = generate_watched_plan(
            {servers[name]: watched[servers[name]] for name in order}, settings, 0
        )
        assert plan == expected
        assert set(plan) == {servers[name] for name in "abde"}
        for name in "abde":
            assert movies_for(plan, servers[name]) == [movie("Cars")]
    if topology == "cycle":
        update = updates_for(expected, servers["e"])[0]
        assert [scope.server_name for scope in update.relay_path] == list("cabde")


@pytest.mark.parametrize("missing", ["user", "library"])
def test_unknown_intermediate_scope_blocks_the_path(missing):
    settings = make_settings({"a": ["b"], "b": ["c"], "c": []})
    servers = make_servers(settings)
    watched = {
        servers["a"]: history(movie()),
        servers["b"]: {} if missing == "user" else {"alice": UserData()},
        servers["c"]: history(),
    }
    assert generate_watched_plan(watched, settings, 0) == {}


@pytest.mark.parametrize("blocked_scope", ["user", "library"])
def test_every_intermediate_hop_must_allow_both_user_and_library(blocked_scope):
    permitted_scope = "library" if blocked_scope == "user" else "user"
    permitted_field = "libraries" if permitted_scope == "library" else "users"
    settings = make_settings(
        {"a": ["b"], "b": [], "c": []},
        **{
            f"{permitted_scope}_sync_rules": [
                {permitted_field: ["*"], "from": "b", "to": "c"}
            ]
        },
    )
    servers = make_servers(settings)
    plan = generate_watched_plan(
        {
            servers["a"]: history(movie()),
            servers["b"]: history(),
            servers["c"]: history(),
        },
        settings,
        0,
    )
    assert set(plan) == {servers["b"]}


def test_relay_preserves_episode_origin_and_resolves_final_hop_aliases():
    settings = make_settings(
        {"a": ["b"], "b": ["c"], "c": []},
        user_mappings=[
            dict(
                canonical="family",
                aliases=[dict(server=name, username=f"User {name}") for name in "abc"],
            )
        ],
        library_mappings=[
            dict(
                canonical="shows",
                aliases=[dict(server=name, library=f"Shows {name}") for name in "abc"],
            )
        ],
    )
    servers = make_servers(settings)
    show = Series(
        identifiers=MediaIdentifiers(tvdb_id="series", title="Original"),
        episodes=[movie("episode")],
    )
    watched = {
        servers[name]: history(
            user=f"User {name}",
            library=f"Shows {name}",
            series=[show] if name == "a" else [],
        )
        for name in "abc"
    }
    plan = generate_watched_plan(watched, settings, 0)
    assert plan[servers["c"]]["b"][0].relay_path == tuple(
        WatchedScope(name, f"User {name}", f"Shows {name}") for name in "abc"
    )
    target = servers["c"]
    target.users = {"User c": "user-id"}
    target.query = Mock(return_value={"Items": [{"Name": "Shows c", "Id": "shows-id"}]})
    target.update_user_watched = Mock(return_value=[])
    for source, updates in plan[target].items():
        Jellyfin.update_watched(target, updates, source)
    target.update_user_watched.assert_called_once()
    username, user_id, data, library_name, library_id, dryrun = (
        target.update_user_watched.call_args.args
    )
    assert (username, library_name) == ("User c", "Shows c")
    assert data.series == [show]


def test_shortest_relay_route_is_deterministic_across_diamond():
    settings = make_settings({"a": ["c", "b"], "b": ["d"], "c": ["d"], "d": []})
    servers = make_servers(settings)
    watched = {
        servers[name]: history(movie()) if name == "a" else history() for name in "abcd"
    }
    plan = generate_watched_plan(watched, settings, 0)
    assert movies_for(plan, servers["d"]) == [movie()]
    assert [
        scope.server_name for scope in updates_for(plan, servers["d"])[0].relay_path
    ] == ["a", "b", "d"]


def apply_jellyfin_plan(monkeypatch, target, plan, item, show=None):
    """Exercise real adapter matching and writes against a fake destination."""
    monkeypatch.setattr("src.jellyfin_emby.log_marked", lambda *args, **kwargs: None)
    target.server_name = target.server_settings.name
    target.users = {"alice": "user-id"}
    target.update_partial = True
    writes = []

    def query(path, method, **kwargs):
        if method == "post":
            writes.append((path, kwargs["json"]))
            return {}
        if path.endswith("/Views"):
            return {"Items": [{"Name": "Movies", "Id": "library-id"}]}
        if "IncludeItemTypes=Series" in path:
            assert show is not None
            return {"Items": [show]}
        return {"Items": [item]}

    target.query = Mock(side_effect=query)
    outcomes = []
    for source, updates in plan.get(target, {}).items():
        outcomes.extend(Jellyfin.update_watched(target, updates, source))
    return writes, outcomes


@pytest.mark.parametrize("kind", ["movie", "episode"])
@pytest.mark.parametrize("order", list(permutations("abc")))
def test_identifier_bridges_produce_one_completed_write(monkeypatch, kind, order):
    settings = make_settings(
        {"a": ["d"], "b": ["d"], "c": ["d"], "d": []}, dryrun=False
    )
    servers = make_servers(settings)
    # The bridge can arrive before, between, or after the two separate IDs.
    identifiers = [
        MediaIdentifiers(imdb_id="shared"),
        MediaIdentifiers(imdb_id="shared", tmdb_id="123"),
        MediaIdentifiers(tmdb_id="123"),
    ]
    watched = {servers["d"]: history()}
    for name, index in zip(order, range(3)):
        item = movie(time=index * 30_000, completed=index == 0)
        item.identifiers = identifiers[index]
        if kind == "movie":
            watched[servers[name]] = history(item)
        else:
            watched[servers[name]] = history(
                series=[Series(identifiers=identifiers[index], episodes=[item])]
            )
    before = deepcopy(list(watched.values()))
    plan = generate_watched_plan(watched, settings, 0)
    target = servers["d"]
    assert set(plan[target]) == {order[0]}
    item = {
        "Id": "item-id",
        "Name": "shared",
        "ProviderIds": {"Imdb": "shared", "Tmdb": "123"},
    }
    show = {"Id": "show-id", "Name": "show", "ProviderIds": item["ProviderIds"]}
    writes, outcomes = apply_jellyfin_plan(monkeypatch, target, plan, item, show)
    assert len(writes) == 1
    assert writes[0][1]["Played"] is True
    assert [(outcome.status, outcome.target_item_id) for outcome in outcomes] == [
        ("applied", "item-id")
    ]
    assert list(watched.values()) == before


@pytest.mark.parametrize("kind", ["movie", "episode"])
@pytest.mark.parametrize("match_by", ["filename", "provider"])
def test_tied_source_keeps_alternate_identifiers_for_adapter(
    monkeypatch, kind, match_by
):
    settings = make_settings({"a": ["c"], "b": ["c"], "c": []}, dryrun=False)
    servers = make_servers(settings)
    watched = {servers["c"]: history()}
    for name in "ab":
        item = movie(locations=(f"{name}.mkv",))
        show_ids = MediaIdentifiers(tvdb_id="show", locations=(f"show-{name}",))
        if match_by == "provider":
            # Different IDs from the same provider, linked by a common path.
            item.identifiers = MediaIdentifiers(imdb_id=name, locations=("shared.mkv",))
            show_ids = MediaIdentifiers(tvdb_id=name, locations=("show",))
        if kind == "movie":
            watched[servers[name]] = history(item)
        else:
            watched[servers[name]] = history(
                series=[
                    Series(
                        identifiers=show_ids,
                        episodes=[item],
                    )
                ]
            )
    plan = generate_watched_plan(watched, settings, 0)
    assert set(plan[servers["c"]]) == {"a"}
    item_data = {"Path": "/media/b.mkv"}
    show_data = {"Path": "/media/show-b"}
    if match_by == "provider":
        item_data = {"ProviderIds": {"Imdb": "b"}}
        show_data = {"ProviderIds": {"Tvdb": "b"}}
    writes, outcomes = apply_jellyfin_plan(
        monkeypatch,
        servers["c"],
        plan,
        {"Id": "item-id", "Name": "shared", **item_data},
        {"Id": "show-id", "Name": "show", **show_data},
    )
    assert len(writes) == 1
    assert writes[0][1]["Played"] is True
    assert outcomes[0].status == "applied"


@pytest.mark.parametrize("kind", ["movie", "episode"])
def test_baseline_suppressed_bridge_still_links_other_candidates(kind):
    settings = make_settings({"a": ["d"], "b": ["d"], "c": ["d"], "d": []})
    servers = make_servers(settings)
    watched = {}
    for name, identifiers, time in [
        ("a", MediaIdentifiers(imdb_id="shared"), 40_000),
        ("b", MediaIdentifiers(imdb_id="shared", tmdb_id="123"), 30_000),
        ("c", MediaIdentifiers(tmdb_id="123"), 35_000),
        ("d", MediaIdentifiers(tmdb_id="123"), 20_000),
    ]:
        item = movie(time=time, completed=False)
        item.identifiers = identifiers
        watched[servers[name]] = (
            history(item)
            if kind == "movie"
            else history(series=[Series(identifiers=identifiers, episodes=[item])])
        )
    # b ties with the baseline and cannot win, but remains identity evidence.
    plan = generate_watched_plan(watched, settings, 0)
    assert set(plan[servers["d"]]) == {"a"}
    update = updates_for(plan, servers["d"])[0]
    item = (
        update.library_data.movies[0]
        if kind == "movie"
        else update.library_data.series[0].episodes[0]
    )
    assert item.status.time == 40_000


def test_destination_history_can_link_source_identifiers():
    settings = make_settings({"a": ["c"], "b": ["c"], "c": []})
    servers = make_servers(settings)
    first = movie()
    second = movie(time=60_000, completed=False)
    second.identifiers = MediaIdentifiers(tmdb_id="123")
    baseline = movie(tmdb_id="123", time=30_000, completed=False)
    plan = generate_watched_plan(
        {
            servers["a"]: history(first),
            servers["b"]: history(second),
            servers["c"]: history(baseline),
        },
        settings,
        0,
    )
    assert set(plan[servers["c"]]) == {"a"}
    assert len(movies_for(plan, servers["c"])) == 1


def test_unreachable_source_cannot_contribute_matching_identifiers():
    settings = make_settings({"a": ["d"], "b": [], "c": ["d"], "d": []})
    servers = make_servers(settings)
    first = movie()
    excluded_bridge = movie(tmdb_id="123")
    second = movie(time=60_000, completed=False)
    second.identifiers = MediaIdentifiers(tmdb_id="123")
    plan = generate_watched_plan(
        {
            servers["a"]: history(first),
            servers["b"]: history(excluded_bridge),
            servers["c"]: history(second),
            servers["d"]: history(),
        },
        settings,
        0,
    )
    assert set(plan[servers["d"]]) == {"a", "c"}
    assert movies_for(plan, servers["d"]) == [first, second]


def test_indirect_baseline_match_prevents_stale_write():
    settings = make_settings({"a": ["c"], "b": ["c"], "c": []})
    servers = make_servers(settings)
    stale = movie(time=30_000, completed=False)
    bridge = movie(tmdb_id="123")
    baseline = movie()
    baseline.identifiers = MediaIdentifiers(tmdb_id="123")
    assert (
        generate_watched_plan(
            {
                servers["a"]: history(stale),
                servers["b"]: history(bridge),
                servers["c"]: history(baseline),
            },
            settings,
            0,
        )
        == {}
    )
