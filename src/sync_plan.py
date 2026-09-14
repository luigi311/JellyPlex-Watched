"""Compare a fetched snapshot and plan updates across all servers."""

from collections import deque
from dataclasses import dataclass, field, replace

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
    filter_library_watched,
    find_target_library_keys,
    find_target_user_keys,
)


# Destination server -> final incoming server name -> winning updates.
# Indirect updates retain their origin and authorized route in relay_path.
type WatchedPlan = dict[Server, dict[str, list[WatchedUpdate]]]


@dataclass(frozen=True)
class _SourceLibrary:
    data: LibraryData
    path: tuple[WatchedScope, ...] = ()


@dataclass(frozen=True)
class _Candidate:
    source: _SourceLibrary
    item: MediaItem
    series: MediaIdentifiers | None = None


@dataclass
class _SeriesCandidates:
    identifiers: MediaIdentifiers
    episodes: list[_Candidate] = field(default_factory=list)


def _select_candidate(
    winners: list[_Candidate],
    candidate: _Candidate,
    settings: AppSettings,
    average_time: float,
) -> None:
    for index, winner in enumerate(winners):
        if check_same_identifiers(winner.item.identifiers, candidate.item.identifiers):
            if (
                compare_media_items(winner.item, candidate.item, settings, average_time)
                == Ord.B_BETTER
            ):
                winners[index] = candidate
            return
    winners.append(candidate)


def _compare_destination(
    sources: list[_SourceLibrary],
    target_user: str,
    target_library: str,
    baseline: LibraryData,
    settings: AppSettings,
    average_time: float,
) -> dict[str, list[WatchedUpdate]]:
    movies: list[_Candidate] = []
    series: list[_SeriesCandidates] = []
    for source in sources:
        # Compare every candidate against the fetched destination first. The
        # timestamp/timeline tolerances are not a transitive ordering, so a
        # candidate suppressed by the baseline must not displace a valid one.
        pending = filter_library_watched(source.data, baseline, settings, average_time)
        for movie in pending.movies:
            _select_candidate(movies, _Candidate(source, movie), settings, average_time)
        for show in pending.series:
            matching = next(
                (
                    existing
                    for existing in series
                    if check_same_identifiers(existing.identifiers, show.identifiers)
                ),
                None,
            )
            if matching is None:
                matching = _SeriesCandidates(show.identifiers)
                series.append(matching)
            for episode in show.episodes:
                _select_candidate(
                    matching.episodes,
                    _Candidate(source, episode, show.identifiers),
                    settings,
                    average_time,
                )

    # Existing adapters route using the final edge. Preserve the complete path
    # separately rather than claiming the original server has a direct mapping
    # to this destination or that an intermediate write has already succeeded.
    libraries: dict[tuple[WatchedScope, tuple[WatchedScope, ...]], LibraryData] = {}
    winners = movies + [episode for show in series for episode in show.episodes]
    for winner in winners:
        source = winner.source
        incoming_scope = source.path[-2]
        relay_path = source.path if len(source.path) > 2 else ()
        key = (incoming_scope, relay_path)
        data = libraries.setdefault(key, LibraryData(title=source.data.title))
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
                    if not settings.should_sync_library(
                        library_name, source_name, target_name
                    ):
                        continue
                    for target_library in find_target_library_keys(
                        settings,
                        source_name,
                        library_name,
                        target_name,
                        servers_watched[target][target_user].libraries,
                    ):
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
                    replace(source, path=target_path)
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
