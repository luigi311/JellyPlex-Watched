import sys
import os

# getting the name of the directory
# where the this file is present.
current = os.path.dirname(os.path.realpath(__file__))

# Getting the parent directory name
# where the current directory is present.
parent = os.path.dirname(current)

# adding the parent directory to
# the sys.path.
sys.path.append(parent)

from src.users import (
    combine_user_lists,
    filter_user_lists,
    sync_users
)


def test_combine_user_lists():
    server_1_users = ["test", "test3", "luigi311"]
    server_2_users = ["luigi311", "test2", "test3"]
    user_mapping = {"test2": "test"}

    combined = combine_user_lists(server_1_users, server_2_users, user_mapping)

    assert combined == {"luigi311": "luigi311", "test": "test2", "test3": "test3"}


def test_filter_user_lists():
    users = {"luigi311": "luigi311", "test": "test2", "test3": "test3"}
    blacklist_users = ["test3"]
    whitelist_users = ["test", "luigi311"]

    filtered = filter_user_lists(users, blacklist_users, whitelist_users)

    assert filtered == {"test": "test2", "luigi311": "luigi311"}

def test_sync_users():
    users = { "user1": "user1", "user2": "user2", "user3": "user3" }

    # empty sync users returns original list
    users_to_sync = sync_users(users, {}, 'jellyfin')
    assert users_to_sync == users

    # None sync users returns original list
    users_to_sync = sync_users(users, None, 'jellyfin')
    assert users_to_sync == users

    # sync user not in orignal list returns original list
    users_to_sync = sync_users(users, { "user4": ['plex'] }, 'jellyfin')
    assert users_to_sync == users

    # sync user syncing expected server returns original list
    users_to_sync = sync_users(users, { "user3": ['jellyfin'] }, 'jellyfin')
    assert users_to_sync == users

    # sync user removed as it is not syncing the server expected.
    users_to_sync = sync_users(users, { "user2": ['plex'] }, 'jellyfin')
    assert users_to_sync == { "user1": "user1", "user3": "user3" }