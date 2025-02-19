from src.functions import (
    logger,
    match_list,
    search_mapping,
)


def check_skip_logic(
    library_title: str,
    library_type: str,
    blacklist_library: list[str],
    whitelist_library: list[str],
    blacklist_library_type: list[str],
    whitelist_library_type: list[str],
    library_mapping: dict[str, str] | None = None,
) -> str | None:
    skip_reason = None
    library_other = None
    if library_mapping:
        library_other = search_mapping(library_mapping, library_title)

    skip_reason_black = check_blacklist_logic(
        library_title,
        library_type,
        blacklist_library,
        blacklist_library_type,
        library_other,
    )
    skip_reason_white = check_whitelist_logic(
        library_title,
        library_type,
        whitelist_library,
        whitelist_library_type,
        library_other,
    )

    # Combine skip reasons
    if skip_reason_black:
        skip_reason = skip_reason_black

    if skip_reason_white:
        if skip_reason:
            skip_reason = skip_reason + " and " + skip_reason_white
        else:
            skip_reason = skip_reason_white

    return skip_reason


def check_blacklist_logic(
    library_title: str,
    library_type: str,
    blacklist_library: list[str],
    blacklist_library_type: list[str],
    library_other: str | None = None,
):
    skip_reason = None
    if isinstance(library_type, (list, tuple, set)):
        for library_type_item in library_type:
            if library_type_item.lower() in blacklist_library_type:
                skip_reason = f"{library_type_item} is in blacklist_library_type"
    else:
        if library_type.lower() in blacklist_library_type:
            skip_reason = f"{library_type} is in blacklist_library_type"

    if library_title.lower() in [x.lower() for x in blacklist_library]:
        if skip_reason:
            skip_reason = (
                skip_reason + " and " + f"{library_title} is in blacklist_library"
            )
        else:
            skip_reason = f"{library_title} is in blacklist_library"

    if library_other:
        if library_other.lower() in [x.lower() for x in blacklist_library]:
            if skip_reason:
                skip_reason = (
                    skip_reason + " and " + f"{library_other} is in blacklist_library"
                )
            else:
                skip_reason = f"{library_other} is in blacklist_library"

    return skip_reason


def check_whitelist_logic(
    library_title: str,
    library_type: str,
    whitelist_library: list[str],
    whitelist_library_type: list[str],
    library_other: str | None = None,
):
    skip_reason = None
    if len(whitelist_library_type) > 0:
        if isinstance(library_type, (list, tuple, set)):
            for library_type_item in library_type:
                if library_type_item.lower() not in whitelist_library_type:
                    skip_reason = (
                        f"{library_type_item} is not in whitelist_library_type"
                    )
        else:
            if library_type.lower() not in whitelist_library_type:
                skip_reason = f"{library_type} is not in whitelist_library_type"

    # if whitelist is not empty and library is not in whitelist
    if len(whitelist_library) > 0:
        if library_other:
            if library_title.lower() not in [
                x.lower() for x in whitelist_library
            ] and library_other.lower() not in [x.lower() for x in whitelist_library]:
                if skip_reason:
                    skip_reason = (
                        skip_reason
                        + " and "
                        + f"{library_title} is not in whitelist_library"
                    )
                else:
                    skip_reason = f"{library_title} is not in whitelist_library"
        else:
            if library_title.lower() not in [x.lower() for x in whitelist_library]:
                if skip_reason:
                    skip_reason = (
                        skip_reason
                        + " and "
                        + f"{library_title} is not in whitelist_library"
                    )
                else:
                    skip_reason = f"{library_title} is not in whitelist_library"

    return skip_reason


def filter_libaries(
    server_libraries: dict[str, str],
    blacklist_library: list[str],
    blacklist_library_type: list[str],
    whitelist_library: list[str],
    whitelist_library_type: list[str],
    library_mapping: dict[str, str] | None = None,
) -> list[str]:
    filtered_libaries: list[str] = []
    for library in server_libraries:
        skip_reason = check_skip_logic(
            library,
            server_libraries[library],
            blacklist_library,
            whitelist_library,
            blacklist_library_type,
            whitelist_library_type,
            library_mapping,
        )

        if skip_reason:
            logger(f"Skipping library {library}: {skip_reason}", 1)
            continue

        filtered_libaries.append(library)

    return filtered_libaries


def setup_libraries(
    server_1,
    server_2,
    blacklist_library: list[str],
    blacklist_library_type: list[str],
    whitelist_library: list[str],
    whitelist_library_type: list[str],
    library_mapping: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    server_1_libraries = server_1.get_libraries()
    server_2_libraries = server_2.get_libraries()
    logger(f"Server 1 libraries: {server_1_libraries}", 1)
    logger(f"Server 2 libraries: {server_2_libraries}", 1)

    # Filter out all blacklist, whitelist libaries
    filtered_server_1_libraries = filter_libaries(
        server_1_libraries,
        blacklist_library,
        blacklist_library_type,
        whitelist_library,
        whitelist_library_type,
        library_mapping,
    )
    filtered_server_2_libraries = filter_libaries(
        server_2_libraries,
        blacklist_library,
        blacklist_library_type,
        whitelist_library,
        whitelist_library_type,
        library_mapping,
    )

    output_server_1_libaries = match_list(
        filtered_server_1_libraries, filtered_server_2_libraries, library_mapping
    )
    output_server_2_libaries = match_list(
        filtered_server_2_libraries, filtered_server_1_libraries, library_mapping
    )

    return output_server_1_libaries, output_server_2_libaries
