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

from src.black_white import setup_black_white_lists


def test_setup_black_white_lists():
    # Simple
    blacklist_library = ["library1", "library2"]
    whitelist_library = ["library1", "library2"]
    blacklist_library_type = ["library_type1", "library_type2"]
    whitelist_library_type = ["library_type1", "library_type2"]
    blacklist_users = ["user1", "user2"]
    whitelist_users = ["user1", "user2"]

    (
        results_blacklist_library,
        return_whitelist_library,
        return_blacklist_library_type,
        return_whitelist_library_type,
        return_blacklist_users,
        return_whitelist_users,
    ) = setup_black_white_lists(
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        blacklist_users,
        whitelist_users,
    )

    assert results_blacklist_library == ["library1", "library2"]
    assert return_whitelist_library == ["library1", "library2"]
    assert return_blacklist_library_type == ["library_type1", "library_type2"]
    assert return_whitelist_library_type == ["library_type1", "library_type2"]
    assert return_blacklist_users == ["user1", "user2"]
    assert return_whitelist_users == ["user1", "user2"]

def test_library_mapping_black_white_list():
    blacklist_library = ["library1", "library2"]
    whitelist_library = ["library1", "library2"]
    blacklist_library_type = ["library_type1", "library_type2"]
    whitelist_library_type = ["library_type1", "library_type2"]
    blacklist_users = ["user1", "user2"]
    whitelist_users = ["user1", "user2"]

    # Library Mapping and user mapping
    library_mapping = {"library1": "library3"}
    user_mapping = {"user1": "user3"}

    (
        results_blacklist_library,
        return_whitelist_library,
        return_blacklist_library_type,
        return_whitelist_library_type,
        return_blacklist_users,
        return_whitelist_users,
    ) = setup_black_white_lists(
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        blacklist_users,
        whitelist_users,
        library_mapping,
        user_mapping,
    )

    assert results_blacklist_library == ["library1", "library2", "library3"]
    assert return_whitelist_library == ["library1", "library2", "library3"]
    assert return_blacklist_library_type == ["library_type1", "library_type2"]
    assert return_whitelist_library_type == ["library_type1", "library_type2"]
    assert return_blacklist_users == ["user1", "user2", "user3"]
    assert return_whitelist_users == ["user1", "user2", "user3"]
