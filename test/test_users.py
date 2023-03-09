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
