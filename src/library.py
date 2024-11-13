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


def show_title_dict(user_list) -> dict[str, list[tuple[str] | None]]:
    try:
        if not isinstance(user_list, dict):
            return {}

        show_output_dict: dict[str, list[tuple[str] | None]] = {}
        show_output_dict["locations"] = []
        show_counter = 0  # Initialize a counter for the current show position

        show_output_keys = [dict(x) for x in list(user_list.keys())]
        for show_key in show_output_keys:
            for provider_key, provider_value in show_key.items():
                # Skip title
                if provider_key.lower() == "title":
                    continue
                if provider_key.lower() not in show_output_dict:
                    show_output_dict[provider_key.lower()] = [None] * show_counter
                if provider_key.lower() == "locations":
                    show_output_dict[provider_key.lower()].append(provider_value)
                else:
                    show_output_dict[provider_key.lower()].append(
                        provider_value.lower()
                    )

            show_counter += 1
            for key in show_output_dict:
                if len(show_output_dict[key]) < show_counter:
                    show_output_dict[key].append(None)

        return show_output_dict
    except Exception:
        return {}


def episode_title_dict(
    user_list,
) -> dict[
    str, list[str | bool | int | tuple[str] | dict[str, str | tuple[str]] | None]
]:
    try:
        if not isinstance(user_list, dict):
            return {}

        episode_output_dict: dict[
            str,
            list[str | bool | int | tuple[str] | dict[str, str | tuple[str]] | None],
        ] = {}
        episode_output_dict["completed"] = []
        episode_output_dict["time"] = []
        episode_output_dict["locations"] = []
        episode_output_dict["show"] = []
        episode_counter = 0  # Initialize a counter for the current episode position

        # Iterate through the shows and episodes in user_list
        for show in user_list:

            for episode in user_list[show]:
                # Add the show title to the episode_output_dict if it doesn't exist
                if "show" not in episode_output_dict:
                    episode_output_dict["show"] = [None] * episode_counter

                # Add the show title to the episode_output_dict
                episode_output_dict["show"].append(dict(show))

                # Iterate through the keys and values in each episode
                for episode_key, episode_value in episode.items():
                    # If the key is not "status", add the key to episode_output_dict if it doesn't exist
                    if episode_key != "status":
                        if episode_key.lower() not in episode_output_dict:
                            # Initialize the list with None values up to the current episode position
                            episode_output_dict[episode_key.lower()] = [
                                None
                            ] * episode_counter

                    # If the key is "locations", append each location to the list
                    if episode_key == "locations":
                        episode_output_dict[episode_key.lower()].append(episode_value)

                    # If the key is "status", append the "completed" and "time" values
                    elif episode_key == "status":
                        episode_output_dict["completed"].append(
                            episode_value["completed"]
                        )
                        episode_output_dict["time"].append(episode_value["time"])

                    # For other keys, append the value to the list
                    else:
                        episode_output_dict[episode_key.lower()].append(
                            episode_value.lower()
                        )

                # Increment the episode_counter
                episode_counter += 1

                # Extend the lists in episode_output_dict with None values to match the current episode_counter
                for key in episode_output_dict:
                    if len(episode_output_dict[key]) < episode_counter:
                        episode_output_dict[key].append(None)

        return episode_output_dict
    except Exception:
        return {}


def movies_title_dict(
    user_list,
) -> dict[str, list[str | bool | int | tuple[str] | None]]:
    try:
        if not isinstance(user_list, list):
            return {}

        movies_output_dict: dict[str, list[str | bool | int | tuple[str] | None]] = {
            "completed": [],
            "time": [],
            "locations": [],
        }
        movie_counter = 0  # Initialize a counter for the current movie position

        for movie in user_list:
            for movie_key, movie_value in movie.items():
                if movie_key != "status":
                    if movie_key.lower() not in movies_output_dict:
                        movies_output_dict[movie_key.lower()] = []

                if movie_key == "locations":
                    movies_output_dict[movie_key.lower()].append(movie_value)
                elif movie_key == "status":
                    movies_output_dict["completed"].append(movie_value["completed"])
                    movies_output_dict["time"].append(movie_value["time"])
                else:
                    movies_output_dict[movie_key.lower()].append(movie_value.lower())

            movie_counter += 1
            for key in movies_output_dict:
                if len(movies_output_dict[key]) < movie_counter:
                    movies_output_dict[key].append(None)

        return movies_output_dict
    except Exception:
        return {}


def generate_library_guids_dict(user_list) -> tuple[
    dict[str, list[tuple[str] | None]],
    dict[str, list[str | bool | int | tuple[str] | dict[str, str | tuple[str]] | None]],
    dict[str, list[str | bool | int | tuple[str] | None]],
]:
    # Handle the case where user_list is empty or does not contain the expected keys and values
    if not user_list:
        return {}, {}, {}

    show_output_dict = show_title_dict(user_list)
    episode_output_dict = episode_title_dict(user_list)
    movies_output_dict = movies_title_dict(user_list)

    return show_output_dict, episode_output_dict, movies_output_dict
