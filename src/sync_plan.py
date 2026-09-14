"""Compare a fetched snapshot and plan updates across all servers."""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace

from src.functions import normalize_name
from src.settings import AppSettings
from src.sync_inventory import Server
from src.watched import (
    LibraryData,
    MediaIdentifiers,
    MediaItem,
    Ord,
    Series,
    UserData,
    WatchedScope,
    WatchedUpdate,
    check_same_identifiers,
    compare_media_items,
    find_target_library_keys,
    find_target_user_keys,
    media_identifier_keys,
)


# Destination server -> final incoming server name -> winning updates.
# Indirect updates retain their origin and authorized route in relay_path.
type WatchedPlan = dict[Server, dict[str, list[WatchedUpdate]]]


@dataclass(frozen=True)
class _SourceLibrary:
    data: LibraryData
    path: tuple[WatchedScope, ...] = ()
    # Adapters recheck the final hop, whose native type can differ from origin.
    incoming_library_type: str | None = None


@dataclass(frozen=True)
class _Candidate:
    # None identifies an item from the fetched destination baseline.
    source: _SourceLibrary | None
    item: MediaItem
    series: MediaIdentifiers | None = None


def _group_by_identity[T](
    entries: list[T], identifiers: Callable[[T], MediaIdentifiers]
) -> list[list[T]]:
    """Group connected identities, retaining entry order for state tie breaks."""
    parents = list(range(len(entries)))
    seen: dict[tuple[str, str], int] = {}

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for index, entry in enumerate(entries):
        for key in media_identifier_keys(identifiers(entry)):
            previous = seen.setdefault(key, index)
            parents[root(previous)] = root(index)

    groups: dict[int, list[T]] = {}
    for index, entry in enumerate(entries):
        groups.setdefault(root(index), []).append(entry)
    return list(groups.values())


def _with_matching_aliases(
    winner: MediaIdentifiers, identities: list[MediaIdentifiers]
) -> MediaIdentifiers:
    keys = frozenset().union(*(media_identifier_keys(item) for item in identities))
    return winner.model_copy(
        deep=True,
        update={
            "matching_aliases": winner.matching_aliases
            | (keys - media_identifier_keys(winner))
        },
    )


def _select_candidates(
    candidates: list[_Candidate],
    settings: AppSettings,
    average_time: float,
) -> list[_Candidate]:
    winners = []
    for group in _group_by_identity(
        candidates, lambda candidate: candidate.item.identifiers
    ):
        baseline = [candidate.item for candidate in group if candidate.source is None]
        winner = None
        for candidate in group:
            if candidate.source is None:
                continue
            # Keep baseline filtering before state reduction: timestamp and
            # timeline tolerances do not form a transitive ordering. Suppressed
            # candidates still contribute identity evidence to the group.
            if any(
                compare_media_items(candidate.item, item, settings, average_time)
                != Ord.A_BETTER
                for item in baseline
            ):
                continue
            if (
                winner is None
                or compare_media_items(
                    winner.item, candidate.item, settings, average_time
                )
                == Ord.B_BETTER
            ):
                winner = candidate
        if winner is not None:
            winners.append(
                replace(
                    winner,
                    item=winner.item.model_copy(
                        deep=True,
                        update={
                            "identifiers": _with_matching_aliases(
                                winner.item.identifiers,
                                [entry.item.identifiers for entry in group],
                            )
                        },
                    ),
                )
            )
    return winners


def _compare_destination(
    sources: list[_SourceLibrary],
    target_user: str,
    target_library: str,
    baseline: LibraryData,
    settings: AppSettings,
    average_time: float,
) -> dict[str, list[WatchedUpdate]]:
    movies: list[_Candidate] = []
    series: list[tuple[_SourceLibrary | None, Series]] = []
    histories: list[tuple[_SourceLibrary | None, LibraryData]] = [
        (source, source.data) for source in sources
    ]
    histories.append((None, baseline))
    for source, data in histories:
        movies.extend(_Candidate(source, movie) for movie in data.movies)
        series.extend((source, show) for show in data.series)

    winners = _select_candidates(movies, settings, average_time)
    for shows in _group_by_identity(series, lambda entry: entry[1].identifiers):
        episodes = [
            _Candidate(source, episode, show.identifiers)
            for source, show in shows
            for episode in show.episodes
        ]
        for winner in _select_candidates(episodes, settings, average_time):
            assert winner.series is not None
            winners.append(
                replace(
                    winner,
                    series=_with_matching_aliases(
                        winner.series, [show.identifiers for _, show in shows]
                    ),
                )
            )

    # Existing adapters route using the final edge. Preserve the complete path
    # separately rather than claiming the original server has a direct mapping
    # to this destination or that an intermediate write has already succeeded.
    libraries: dict[tuple[WatchedScope, tuple[WatchedScope, ...]], LibraryData] = {}
    for winner in winners:
        source = winner.source
        assert source is not None
        incoming_scope = source.path[-2]
        relay_path = source.path if len(source.path) > 2 else ()
        key = (incoming_scope, relay_path)
        data = libraries.setdefault(
            key,
            LibraryData(
                title=source.data.title, library_type=source.incoming_library_type
            ),
        )
        item = winner.item.model_copy(deep=True)
        if winner.series is None:
            data.movies.append(item)
        else:
            matching_show = next(
                (
                    show
                    for show in data.series
                    if check_same_identifiers(show.identifiers, winner.series)
                ),
                None,
            )
            if matching_show is None:
                matching_show = Series(identifiers=winner.series.model_copy(deep=True))
                data.series.append(matching_show)
            matching_show.episodes.append(item)

    result: dict[str, list[WatchedUpdate]] = {}
    for (incoming_scope, relay_path), data in sorted(libraries.items()):
        result.setdefault(incoming_scope.server_name, []).append(
            WatchedUpdate(
                source_user=incoming_scope.username,
                target_user=target_user,
                source_library=incoming_scope.library_name,
                target_library=target_library,
                library_data=data,
                relay_path=relay_path,
            )
        )
    return result


def generate_watched_plan(
    servers_watched: dict[Server, dict[str, UserData]],
    settings: AppSettings,
    average_time: float,
) -> WatchedPlan:
    """Plan all destinations from one snapshot without I/O or mutation.

    Build a graph of permitted user/library mappings, then gather the original
    histories reachable along any directed path. Compare those histories for
    each destination before writing anything. Unknown scopes cannot receive or
    relay history; successfully fetched empty libraries can do both.

    Each origin visits a scope at most once, including in cycles. The shortest
    permitted route is retained with stable name ordering to break route ties.
    State comparison also uses stable origin order and the existing rules.
    No simulated write receipts or intermediate server mutations are needed.
    """
    servers = sorted(servers_watched, key=lambda server: server.server_settings.name)
    sources: dict[WatchedScope, _SourceLibrary] = {}
    edges: dict[WatchedScope, list[WatchedScope]] = {}
    for source in servers:
        source_name = source.server_settings.name
        targets = [
            target
            for target in servers
            if target is not source
            and settings.should_sync_server(source_name, target.server_settings.name)
        ]
        for username, user_data in sorted(
            servers_watched[source].items(), key=lambda entry: normalize_name(entry[0])
        ):
            destinations = [
                (target, target_user)
                for target in targets
                if settings.should_sync_user(
                    username, source_name, target.server_settings.name
                )
                for target_user in find_target_user_keys(
                    settings,
                    source_name,
                    username,
                    target.server_settings.name,
                    servers_watched[target],
                )
            ]
            for library_name, data in sorted(
                user_data.libraries.items(), key=lambda entry: normalize_name(entry[0])
            ):
                source_scope = WatchedScope(source_name, username, library_name)
                sources[source_scope] = _SourceLibrary(data)
                edges[source_scope] = []
                for target, target_user in destinations:
                    target_name = target.server_settings.name
                    for target_library in find_target_library_keys(
                        settings,
                        source_name,
                        library_name,
                        target_name,
                        servers_watched[target][target_user].libraries,
                    ):
                        if not settings.should_sync_scope(
                            username,
                            library_name,
                            source_name,
                            target_name,
                            library_type=data.library_type,
                            target_library_type=servers_watched[target][target_user]
                            .libraries[target_library]
                            .library_type,
                        ):
                            continue
                        edges[source_scope].append(
                            WatchedScope(target_name, target_user, target_library)
                        )

    incoming: dict[WatchedScope, list[_SourceLibrary]] = {}
    for origin, source in sorted(sources.items()):
        visited = {origin}
        pending: deque[tuple[WatchedScope, ...]] = deque([(origin,)])
        while pending:
            path = pending.popleft()
            for target_scope in sorted(edges[path[-1]]):
                if target_scope in visited:
                    continue
                visited.add(target_scope)
                target_path = (*path, target_scope)
                incoming.setdefault(target_scope, []).append(
                    replace(
                        source,
                        path=target_path,
                        incoming_library_type=sources[path[-1]].data.library_type,
                    )
                )
                pending.append(target_path)

    plan: WatchedPlan = {}
    servers_by_name = {server.server_settings.name: server for server in servers}
    for target_scope, reachable_sources in sorted(incoming.items()):
        target = servers_by_name[target_scope.server_name]
        username = target_scope.username
        library_name = target_scope.library_name
        batches = _compare_destination(
            reachable_sources,
            username,
            library_name,
            servers_watched[target][username].libraries[library_name],
            settings,
            average_time,
        )
        for source_name, updates in batches.items():
            plan.setdefault(target, {}).setdefault(source_name, []).extend(updates)
    return plan
