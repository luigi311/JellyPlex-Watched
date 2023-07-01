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
    blacklist_library, blacklist_library_type, blacklist_users = setup_x_lists(
        blacklist_library,
        blacklist_library_type,
        blacklist_users,
        "Black",
        library_mapping,
        user_mapping,
    )

    whitelist_library, whitelist_library_type, whitelist_users = setup_x_lists(
        whitelist_library,
        whitelist_library_type,
        whitelist_users,
        "White",
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

def setup_x_lists(
    xlist_library,
    xlist_library_type,
    xlist_users,
    xlist_type,
    library_mapping=None,
    user_mapping=None,
):
    if xlist_library:
        if len(xlist_library) > 0:
            xlist_library = xlist_library.split(",")
            xlist_library = [x.strip() for x in xlist_library]
            if library_mapping:
                temp_library = []
                for library in xlist_library:
                    library_other = search_mapping(library_mapping, library)
                    if library_other:
                        temp_library.append(library_other)

                xlist_library = xlist_library + temp_library
    else:
        xlist_library = []
    logger(f"{xlist_type}list Library: {xlist_library}", 1)

    if xlist_library_type:
        if len(xlist_library_type) > 0:
            xlist_library_type = xlist_library_type.split(",")
            xlist_library_type = [x.lower().strip() for x in xlist_library_type]
    else:
        xlist_library_type = []
    logger(f"{xlist_type}list Library Type: {xlist_library_type}", 1)

    if xlist_users:
        if len(xlist_users) > 0:
            xlist_users = xlist_users.split(",")
            xlist_users = [x.lower().strip() for x in xlist_users]
            if user_mapping:
                temp_users = []
                for user in xlist_users:
                    user_other = search_mapping(user_mapping, user)
                    if user_other:
                        temp_users.append(user_other)

                xlist_users = xlist_users + temp_users
        else:
            xlist_users = []
    else:
        xlist_users = []
    logger(f"{xlist_type}list Users: {xlist_users}", 1)

    return xlist_library, xlist_library_type, xlist_users







































