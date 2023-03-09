from src.functions import logger, search_mapping


def setup_black_white_lists(
    blacklist_library: str,
    whitelist_library: str,
    blacklist_library_type: str,
    whitelist_library_type: str,
    blacklist_users: str,
    whitelist_users: str,
    library_mapping=None,
    user_mapping=None,
):
    blacklist_library, blacklist_library_type, blacklist_users = setup_black_lists(
        blacklist_library,
        blacklist_library_type,
        blacklist_users,
        library_mapping,
        user_mapping,
    )

    whitelist_library, whitelist_library_type, whitelist_users = setup_white_lists(
        whitelist_library,
        whitelist_library_type,
        whitelist_users,
        library_mapping,
        user_mapping,
    )

    return (
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        blacklist_users,
        whitelist_users,
    )


def setup_black_lists(
    blacklist_library,
    blacklist_library_type,
    blacklist_users,
    library_mapping=None,
    user_mapping=None,
):
    if blacklist_library:
        if len(blacklist_library) > 0:
            blacklist_library = blacklist_library.split(",")
            blacklist_library = [x.strip() for x in blacklist_library]
            if library_mapping:
                temp_library = []
                for library in blacklist_library:
                    library_other = search_mapping(library_mapping, library)
                    if library_other:
                        temp_library.append(library_other)

                blacklist_library = blacklist_library + temp_library
    else:
        blacklist_library = []
    logger(f"Blacklist Library: {blacklist_library}", 1)

    if blacklist_library_type:
        if len(blacklist_library_type) > 0:
            blacklist_library_type = blacklist_library_type.split(",")
            blacklist_library_type = [x.lower().strip() for x in blacklist_library_type]
    else:
        blacklist_library_type = []
    logger(f"Blacklist Library Type: {blacklist_library_type}", 1)

    if blacklist_users:
        if len(blacklist_users) > 0:
            blacklist_users = blacklist_users.split(",")
            blacklist_users = [x.lower().strip() for x in blacklist_users]
            if user_mapping:
                temp_users = []
                for user in blacklist_users:
                    user_other = search_mapping(user_mapping, user)
                    if user_other:
                        temp_users.append(user_other)

                blacklist_users = blacklist_users + temp_users
    else:
        blacklist_users = []
    logger(f"Blacklist Users: {blacklist_users}", 1)

    return blacklist_library, blacklist_library_type, blacklist_users


def setup_white_lists(
    whitelist_library,
    whitelist_library_type,
    whitelist_users,
    library_mapping=None,
    user_mapping=None,
):
    if whitelist_library:
        if len(whitelist_library) > 0:
            whitelist_library = whitelist_library.split(",")
            whitelist_library = [x.strip() for x in whitelist_library]
            if library_mapping:
                temp_library = []
                for library in whitelist_library:
                    library_other = search_mapping(library_mapping, library)
                    if library_other:
                        temp_library.append(library_other)

                whitelist_library = whitelist_library + temp_library
    else:
        whitelist_library = []
    logger(f"Whitelist Library: {whitelist_library}", 1)

    if whitelist_library_type:
        if len(whitelist_library_type) > 0:
            whitelist_library_type = whitelist_library_type.split(",")
            whitelist_library_type = [x.lower().strip() for x in whitelist_library_type]
    else:
        whitelist_library_type = []
    logger(f"Whitelist Library Type: {whitelist_library_type}", 1)

    if whitelist_users:
        if len(whitelist_users) > 0:
            whitelist_users = whitelist_users.split(",")
            whitelist_users = [x.lower().strip() for x in whitelist_users]
            if user_mapping:
                temp_users = []
                for user in whitelist_users:
                    user_other = search_mapping(user_mapping, user)
                    if user_other:
                        temp_users.append(user_other)

                whitelist_users = whitelist_users + temp_users
        else:
            whitelist_users = []
    else:
        whitelist_users = []
    logger(f"Whitelist Users: {whitelist_users}", 1)

    return whitelist_library, whitelist_library_type, whitelist_users
