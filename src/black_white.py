from src.functions import logger, search_mapping


def setup_black_white_lists(
    blacklist_library: list[str] | None,
    whitelist_library: list[str] | None,
    blacklist_library_type: list[str] | None,
    whitelist_library_type: list[str] | None,
    blacklist_users: list[str] | None,
    whitelist_users: list[str] | None,
    library_mapping: dict[str, str] | None = None,
    user_mapping: dict[str, str] | None = None,
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
    xlist_library: list[str] | None,
    xlist_library_type: list[str] | None,
    xlist_users: list[str] | None,
    xlist_type: str | None,
    library_mapping: dict[str, str] | None = None,
    user_mapping: dict[str, str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    out_library: list[str] = []
    if xlist_library:
        out_library = [x.strip() for x in xlist_library]
        if library_mapping:
            temp_library: list[str] = []
            for library in xlist_library:
                library_other = search_mapping(library_mapping, library)
                if library_other:
                    temp_library.append(library_other)

            out_library = out_library + temp_library
        logger(f"{xlist_type}list Library: {xlist_library}", 1)

    out_library_type: list[str] = []
    if xlist_library_type:
        out_library_type = [x.lower().strip() for x in xlist_library_type]

        logger(f"{xlist_type}list Library Type: {out_library_type}", 1)

    out_users: list[str] = []
    if xlist_users:
        out_users = [x.lower().strip() for x in xlist_users]
        if user_mapping:
            temp_users: list[str] = []
            for user in out_users:
                user_other = search_mapping(user_mapping, user)
                if user_other:
                    temp_users.append(user_other)

            out_users = out_users + temp_users

        logger(f"{xlist_type}list Users: {out_users}", 1)

    return out_library, out_library_type, out_users
