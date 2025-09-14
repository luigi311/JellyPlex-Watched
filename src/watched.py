from datetime import datetime
from pydantic import BaseModel, Field
from loguru import logger
from typing import Any, Literal

from src.functions import search_mapping


class MediaIdentifiers(BaseModel):
    title: str | None = None
    locations: tuple[str, ...] = tuple()
    imdb_id: str | None = None
    tvdb_id: str | None = None
    tmdb_id: str | None = None
    id: str | None = None
    server: Any | None = None
    user_id: str | None = None


class WatchedStatus(BaseModel):
    completed: bool
    time: int
    viewed_date: datetime
    last_updated_at: datetime


class MediaItem(BaseModel):
    identifiers: MediaIdentifiers
    status: WatchedStatus


class Series(BaseModel):
    identifiers: MediaIdentifiers
    episodes: list[MediaItem] = Field(default_factory=list)


class LibraryData(BaseModel):
    title: str
    movies: list[MediaItem] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)


class UserData(BaseModel):
    libraries: dict[str, LibraryData] = Field(default_factory=dict)


def check_same_identifiers(item1: MediaIdentifiers, item2: MediaIdentifiers) -> bool:
    if item1.locations and item2.locations:
        if set(item1.locations) & set(item2.locations):
            return True
    if (
        (item1.imdb_id and item2.imdb_id and item1.imdb_id == item2.imdb_id)
        or (item1.tvdb_id and item2.tvdb_id and item1.tvdb_id == item2.tvdb_id)
        or (item1.tmdb_id and item2.tmdb_id and item1.tmdb_id == item2.tmdb_id)
    ):
        return True
    return False

def sync_watched_lists(
    server1_data: dict[str, UserData],
    server2_data: dict[str, UserData],
    user_mapping: dict[str, str] | None = None,
    library_mapping: dict[str, str] | None = None,
) -> list[tuple[Literal["mark_watched", "mark_unwatched"], Any, str, str, str]]:
    actions = []

    for user1_name, user1_data in server1_data.items():
        user2_name = search_mapping(user_mapping, user1_name) if user_mapping else user1_name
        if user2_name not in server2_data:
            continue

        user2_data = server2_data[user2_name]

        for lib1_name, lib1_data in user1_data.libraries.items():
            lib2_name = search_mapping(library_mapping, lib1_name) if library_mapping else lib1_name
            if lib2_name not in user2_data.libraries:
                continue

            lib2_data = user2_data.libraries[lib2_name]

            # Sync movies
            for movie1 in lib1_data.movies:
                for movie2 in lib2_data.movies:
                    if check_same_identifiers(movie1.identifiers, movie2.identifiers):
                        action = compare_and_get_action(movie1, movie2)
                        if action:
                            actions.append(action)
                        break

            # Sync series (episodes)
            for series1 in lib1_data.series:
                for series2 in lib2_data.series:
                    if check_same_identifiers(series1.identifiers, series2.identifiers):
                        for episode1 in series1.episodes:
                            for episode2 in series2.episodes:
                                if check_same_identifiers(episode1.identifiers, episode2.identifiers):
                                    action = compare_and_get_action(episode1, episode2)
                                    if action:
                                        actions.append(action)
                                    break
                        break
    return actions


def compare_and_get_action(item1: MediaItem, item2: MediaItem):
    if item1.status.completed == item2.status.completed:
        return None

    if item1.status.last_updated_at > item2.status.last_updated_at:
        source_item, dest_item = item1, item2
    elif item2.status.last_updated_at > item1.status.last_updated_at:
        source_item, dest_item = item2, item1
    else:
        return None

    action_type = "mark_watched" if source_item.status.completed else "mark_unwatched"

    logger.info(f"Scheduling action: {action_type} for item {dest_item.identifiers.title} on server {dest_item.identifiers.server.server_type}")

    return (
        action_type,
        dest_item.identifiers.server,
        dest_item.identifiers.user_id,
        dest_item.identifiers.id,
        source_item.status.viewed_date.isoformat().replace("+00:00", "Z")
    )
