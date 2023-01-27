from src.functions import (
    logger,
    search_mapping,
)

def check_skip_logic(
    library_title,
    library_type,
    blacklist_library,
    whitelist_library,
    blacklist_library_type,
    whitelist_library_type,
    library_mapping,
):
    skip_reason = None

    if isinstance(library_type, (list, tuple, set)):
        for library_type_item in library_type:
            if library_type_item.lower() in blacklist_library_type:
                skip_reason = "is blacklist_library_type"
    else:
        if library_type.lower() in blacklist_library_type:
            skip_reason = "is blacklist_library_type"

    if library_title.lower() in [x.lower() for x in blacklist_library]:
        skip_reason = "is blacklist_library"

    library_other = None
    if library_mapping:
        library_other = search_mapping(library_mapping, library_title)
    if library_other:
        if library_other.lower() in [x.lower() for x in blacklist_library]:
            skip_reason = "is blacklist_library"

    if len(whitelist_library_type) > 0:
        if isinstance(library_type, (list, tuple, set)):
            for library_type_item in library_type:
                if library_type_item.lower() not in whitelist_library_type:
                    skip_reason = "is not whitelist_library_type"
        else:
            if library_type.lower() not in whitelist_library_type:
                skip_reason = "is not whitelist_library_type"

    # if whitelist is not empty and library is not in whitelist
    if len(whitelist_library) > 0:
        if library_title.lower() not in [x.lower() for x in whitelist_library]:
            skip_reason = "is not whitelist_library"

        if library_other:
            if library_other.lower() not in [x.lower() for x in whitelist_library]:
                skip_reason = "is not whitelist_library"

    return skip_reason


def generate_library_guids_dict(user_list: dict):
    show_output_dict = {}
    episode_output_dict = {}
    movies_output_dict = {}

    # Handle the case where user_list is empty or does not contain the expected keys and values
    if not user_list:
        return show_output_dict, episode_output_dict, movies_output_dict

    try:
        show_output_keys = user_list.keys()
        show_output_keys = [dict(x) for x in list(show_output_keys)]
        for show_key in show_output_keys:
            for provider_key, provider_value in show_key.items():
                # Skip title
                if provider_key.lower() == "title":
                    continue
                if provider_key.lower() not in show_output_dict:
                    show_output_dict[provider_key.lower()] = []
                if provider_key.lower() == "locations":
                    for show_location in provider_value:
                        show_output_dict[provider_key.lower()].append(show_location)
                else:
                    show_output_dict[provider_key.lower()].append(
                        provider_value.lower()
                    )
    except Exception:
        logger("Generating show_output_dict failed, skipping", 1)

    try:
        for show in user_list:
            for season in user_list[show]:
                for episode in user_list[show][season]:
                    for episode_key, episode_value in episode.items():
                        if episode_key.lower() not in episode_output_dict:
                            episode_output_dict[episode_key.lower()] = []
                        if episode_key == "locations":
                            for episode_location in episode_value:
                                episode_output_dict[episode_key.lower()].append(
                                    episode_location
                                )
                        else:
                            episode_output_dict[episode_key.lower()].append(
                                episode_value.lower()
                            )
    except Exception:
        logger("Generating episode_output_dict failed, skipping", 1)

    try:
        for movie in user_list:
            for movie_key, movie_value in movie.items():
                if movie_key.lower() not in movies_output_dict:
                    movies_output_dict[movie_key.lower()] = []
                if movie_key == "locations":
                    for movie_location in movie_value:
                        movies_output_dict[movie_key.lower()].append(movie_location)
                else:
                    movies_output_dict[movie_key.lower()].append(movie_value.lower())
    except Exception:
        logger("Generating movies_output_dict failed, skipping", 1)

    return show_output_dict, episode_output_dict, movies_output_dict
    