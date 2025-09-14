from datetime import datetime, timedelta
import sys
import os
from unittest.mock import Mock

# Add parent directory to sys.path
current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
sys.path.append(parent)

from src.watched import (
    LibraryData,
    MediaIdentifiers,
    MediaItem,
    Series,
    UserData,
    WatchedStatus,
    sync_watched_lists,
)

# --- Mock Data Setup ---
now = datetime.now()
time_new = now
time_old = now - timedelta(days=1)

# Mock server objects
mock_server1 = Mock()
mock_server1.server_type = "Plex"
mock_server2 = Mock()
mock_server2.server_type = "Jellyfin"

# --- Test Case 1: Sync "watched" from Server 1 to Server 2 ---
movie_s1_watched = MediaItem(
    identifiers=MediaIdentifiers(title="Movie A", id="1", server=mock_server1, user_id="user1", imdb_id="tt1"),
    status=WatchedStatus(completed=True, time=0, viewed_date=time_new, last_updated_at=time_new),
)
movie_s2_unwatched = MediaItem(
    identifiers=MediaIdentifiers(title="Movie A", id="a", server=mock_server2, user_id="user1", imdb_id="tt1"),
    status=WatchedStatus(completed=False, time=0, viewed_date=time_old, last_updated_at=time_old),
)

# --- Test Case 2: Sync "unwatched" from Server 2 to Server 1 ---
movie_s1_unwatched_old = MediaItem(
    identifiers=MediaIdentifiers(title="Movie B", id="2", server=mock_server1, user_id="user1", imdb_id="tt2"),
    status=WatchedStatus(completed=True, time=0, viewed_date=time_old, last_updated_at=time_old),
)
movie_s2_unwatched_new = MediaItem(
    identifiers=MediaIdentifiers(title="Movie B", id="b", server=mock_server2, user_id="user1", imdb_id="tt2"),
    status=WatchedStatus(completed=False, time=0, viewed_date=time_new, last_updated_at=time_new),
)

# --- Test Case 3: No sync needed (already in sync) ---
movie_s1_synced = MediaItem(
    identifiers=MediaIdentifiers(title="Movie C", id="3", server=mock_server1, user_id="user1", imdb_id="tt3"),
    status=WatchedStatus(completed=True, time=0, viewed_date=time_new, last_updated_at=time_new),
)
movie_s2_synced = MediaItem(
    identifiers=MediaIdentifiers(title="Movie C", id="c", server=mock_server2, user_id="user1", imdb_id="tt3"),
    status=WatchedStatus(completed=True, time=0, viewed_date=time_new, last_updated_at=time_new),
)

# --- Test Case 4: No sync needed (timestamps equal) ---
movie_s1_equal_ts = MediaItem(
    identifiers=MediaIdentifiers(title="Movie D", id="4", server=mock_server1, user_id="user1", imdb_id="tt4"),
    status=WatchedStatus(completed=True, time=0, viewed_date=time_new, last_updated_at=time_new),
)
movie_s2_equal_ts = MediaItem(
    identifiers=MediaIdentifiers(title="Movie D", id="d", server=mock_server2, user_id="user1", imdb_id="tt4"),
    status=WatchedStatus(completed=False, time=0, viewed_date=time_new, last_updated_at=time_new),
)


def build_test_data(movies1, movies2):
    return (
        {"user1": UserData(libraries={"Movies": LibraryData(title="Movies", movies=movies1, series=[])})},
        {"user1": UserData(libraries={"Movies": LibraryData(title="Movies", movies=movies2, series=[])})},
    )

def test_sync_watched_from_s1_to_s2():
    server1_data, server2_data = build_test_data([movie_s1_watched], [movie_s2_unwatched])
    actions = sync_watched_lists(server1_data, server2_data)

    assert len(actions) == 1
    action = actions[0]
    assert action[0] == "mark_watched"
    assert action[1] == mock_server2
    assert action[2] == "user1"
    assert action[3] == "a"

def test_sync_unwatched_from_s2_to_s1():
    server1_data, server2_data = build_test_data([movie_s1_unwatched_old], [movie_s2_unwatched_new])
    actions = sync_watched_lists(server1_data, server2_data)

    assert len(actions) == 1
    action = actions[0]
    assert action[0] == "mark_unwatched"
    assert action[1] == mock_server1
    assert action[2] == "user1"
    assert action[3] == "2"

def test_no_sync_when_already_synced():
    server1_data, server2_data = build_test_data([movie_s1_synced], [movie_s2_synced])
    actions = sync_watched_lists(server1_data, server2_data)
    assert len(actions) == 0

def test_no_sync_when_timestamps_equal():
    server1_data, server2_data = build_test_data([movie_s1_equal_ts], [movie_s2_equal_ts])
    actions = sync_watched_lists(server1_data, server2_data)
    assert len(actions) == 0

def test_sync_with_user_mapping():
    server1_data = {"plex_user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[movie_s1_watched], series=[])})}
    server2_data = {"jellyfin_user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[movie_s2_unwatched], series=[])})}
    user_mapping = {"plex_user": "jellyfin_user"}

    actions = sync_watched_lists(server1_data, server2_data, user_mapping=user_mapping)

    assert len(actions) == 1
    action = actions[0]
    assert action[0] == "mark_watched"
    assert action[1] == mock_server2

def test_sync_with_library_mapping():
    server1_data = {"user1": UserData(libraries={"Plex Movies": LibraryData(title="Plex Movies", movies=[movie_s1_watched], series=[])})}
    server2_data = {"user1": UserData(libraries={"Jellyfin Movies": LibraryData(title="Jellyfin Movies", movies=[movie_s2_unwatched], series=[])})}
    library_mapping = {"Plex Movies": "Jellyfin Movies"}

    actions = sync_watched_lists(server1_data, server2_data, library_mapping=library_mapping)

    assert len(actions) == 1
    action = actions[0]
    assert action[0] == "mark_watched"
    assert action[1] == mock_server2
