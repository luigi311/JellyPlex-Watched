import os, copy
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

load_dotenv(override=True)

logfile = os.getenv("LOGFILE", "log.log")


def logger(message: str, log_type=0):
    debug = str_to_bool(os.getenv("DEBUG", "False"))
    debug_level = os.getenv("DEBUG_LEVEL", "info").lower()

    output = str(message)
    if log_type == 0:
        pass
    elif log_type == 1 and (debug and debug_level in ("info", "debug")):
        output = f"[INFO]: {output}"
    elif log_type == 2:
        output = f"[ERROR]: {output}"
    elif log_type == 3 and (debug and debug_level == "debug"):
        output = f"[DEBUG]: {output}"
    elif log_type == 4:
        output = f"[WARNING]: {output}"
    else:
        output = None

    if output is not None:
        print(output)
        file = open(logfile, "a", encoding="utf-8")
        file.write(output + "\n")


# Reimplementation of distutils.util.strtobool due to it being deprecated
# Source: https://github.com/PostHog/posthog/blob/01e184c29d2c10c43166f1d40a334abbc3f99d8a/posthog/utils.py#L668
def str_to_bool(value: any) -> bool:
    if not value:
        return False
    return str(value).lower() in ("y", "yes", "t", "true", "on", "1")


# Get mapped value
def search_mapping(dictionary: dict, key_value: str):
    if key_value in dictionary.keys():
        return dictionary[key_value]
    elif key_value.lower() in dictionary.keys():
        return dictionary[key_value.lower()]
    elif key_value in dictionary.values():
        return list(dictionary.keys())[list(dictionary.values()).index(key_value)]
    elif key_value.lower() in dictionary.values():
        return list(dictionary.keys())[
            list(dictionary.values()).index(key_value.lower())
        ]
    else:
        return None


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

    if blacklist_library_type:
        if len(blacklist_library_type) > 0:
            blacklist_library_type = blacklist_library_type.split(",")
            blacklist_library_type = [x.lower().strip() for x in blacklist_library_type]
    else:
        blacklist_library_type = []
    logger(f"Blacklist Library Type: {blacklist_library_type}", 1)

    if whitelist_library_type:
        if len(whitelist_library_type) > 0:
            whitelist_library_type = whitelist_library_type.split(",")
            whitelist_library_type = [x.lower().strip() for x in whitelist_library_type]
    else:
        whitelist_library_type = []
    logger(f"Whitelist Library Type: {whitelist_library_type}", 1)

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

    return (
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        blacklist_users,
        whitelist_users,
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


def combine_watched_dicts(dicts: list):
    combined_dict = {}
    for single_dict in dicts:
        for key, value in single_dict.items():
            if key not in combined_dict:
                combined_dict[key] = {}
            for subkey, subvalue in value.items():
                if subkey in combined_dict[key]:
                    # If the subkey already exists in the combined dictionary,
                    # check if the values are different and raise an exception if they are
                    if combined_dict[key][subkey] != subvalue:
                        raise ValueError(
                            f"Conflicting values for subkey '{subkey}' under key '{key}'"
                        )
                else:
                    # If the subkey does not exist in the combined dictionary, add it
                    combined_dict[key][subkey] = subvalue

    return combined_dict


def cleanup_watched(
    watched_list_1, watched_list_2, user_mapping=None, library_mapping=None
):
    modified_watched_list_1 = copy.deepcopy(watched_list_1)

    # remove entries from watched_list_1 that are in watched_list_2
    for user_1 in watched_list_1:
        user_other = None
        if user_mapping:
            user_other = search_mapping(user_mapping, user_1)
        user_2 = get_other(watched_list_2, user_1, user_other)
        if user_2 is None:
            continue

        for library_1 in watched_list_1[user_1]:
            library_other = None
            if library_mapping:
                library_other = search_mapping(library_mapping, library_1)
            library_2 = get_other(watched_list_2[user_2], library_1, library_other)
            if library_2 is None:
                continue

            (
                _,
                episode_watched_list_2_keys_dict,
                movies_watched_list_2_keys_dict,
            ) = generate_library_guids_dict(watched_list_2[user_2][library_2])

            # Movies
            if isinstance(watched_list_1[user_1][library_1], list):
                for movie in watched_list_1[user_1][library_1]:
                    if is_movie_in_dict(movie, movies_watched_list_2_keys_dict):
                        logger(f"Removing {movie} from {library_1}", 3)
                        modified_watched_list_1[user_1][library_1].remove(movie)

            # TV Shows
            elif isinstance(watched_list_1[user_1][library_1], dict):
                for show_key_1 in watched_list_1[user_1][library_1].keys():
                    show_key_dict = dict(show_key_1)
                    for season in watched_list_1[user_1][library_1][show_key_1]:
                        for episode in watched_list_1[user_1][library_1][show_key_1][
                            season
                        ]:
                            if is_episode_in_dict(
                                episode, episode_watched_list_2_keys_dict
                            ):
                                if (
                                    episode
                                    in modified_watched_list_1[user_1][library_1][
                                        show_key_1
                                    ][season]
                                ):
                                    logger(
                                        f"Removing {episode} from {show_key_dict['title']}",
                                        3,
                                    )
                                    modified_watched_list_1[user_1][library_1][
                                        show_key_1
                                    ][season].remove(episode)

                        # Remove empty seasons
                        if (
                            len(
                                modified_watched_list_1[user_1][library_1][show_key_1][
                                    season
                                ]
                            )
                            == 0
                        ):
                            if (
                                season
                                in modified_watched_list_1[user_1][library_1][
                                    show_key_1
                                ]
                            ):
                                logger(
                                    f"Removing {season} from {show_key_dict['title']} because it is empty",
                                    3,
                                )
                                del modified_watched_list_1[user_1][library_1][
                                    show_key_1
                                ][season]

                    # Remove empty shows
                    if len(modified_watched_list_1[user_1][library_1][show_key_1]) == 0:
                        if show_key_1 in modified_watched_list_1[user_1][library_1]:
                            logger(
                                f"Removing {show_key_dict['title']} because it is empty",
                                3,
                            )
                            del modified_watched_list_1[user_1][library_1][show_key_1]

    for user_1 in watched_list_1:
        for library_1 in watched_list_1[user_1]:
            if library_1 in modified_watched_list_1[user_1]:
                # If library is empty then remove it
                if len(modified_watched_list_1[user_1][library_1]) == 0:
                    logger(f"Removing {library_1} from {user_1} because it is empty", 1)
                    del modified_watched_list_1[user_1][library_1]

        if user_1 in modified_watched_list_1:
            # If user is empty delete user
            if len(modified_watched_list_1[user_1]) == 0:
                logger(f"Removing {user_1} from watched list 1 because it is empty", 1)
                del modified_watched_list_1[user_1]

    return modified_watched_list_1


def get_other(watched_list_2, object_1, object_2):
    if object_1 in watched_list_2:
        return object_1
    elif object_2 in watched_list_2:
        return object_2
    else:
        logger(f"{object_1} and {object_2} not found in watched list 2", 1)
        return None


def is_movie_in_dict(movie, movies_watched_list_2_keys_dict):
    # Iterate through the keys and values of the movie dictionary
    for movie_key, movie_value in movie.items():
        # If the key is "locations", check if the "locations" key is present in the movies_watched_list_2_keys_dict dictionary
        if movie_key == "locations":
            if "locations" in movies_watched_list_2_keys_dict.keys():
                # Iterate through the locations in the movie dictionary
                for location in movie_value:
                    # If the location is in the movies_watched_list_2_keys_dict dictionary, return True
                    if location in movies_watched_list_2_keys_dict["locations"]:
                        return True
        # If the key is not "locations", check if the movie_key is present in the movies_watched_list_2_keys_dict dictionary
        else:
            if movie_key in movies_watched_list_2_keys_dict.keys():
                # If the movie_value is in the movies_watched_list_2_keys_dict dictionary, return True
                if movie_value in movies_watched_list_2_keys_dict[movie_key]:
                    return True

    # If the loop completes without finding a match, return False
    return False


def is_episode_in_dict(episode, episode_watched_list_2_keys_dict):
    # Iterate through the keys and values of the episode dictionary
    for episode_key, episode_value in episode.items():
        # If the key is "locations", check if the "locations" key is present in the episode_watched_list_2_keys_dict dictionary
        if episode_key == "locations":
            if "locations" in episode_watched_list_2_keys_dict.keys():
                # Iterate through the locations in the episode dictionary
                for location in episode_value:
                    # If the location is in the episode_watched_list_2_keys_dict dictionary, return True
                    if location in episode_watched_list_2_keys_dict["locations"]:
                        return True
        # If the key is not "locations", check if the episode_key is present in the episode_watched_list_2_keys_dict dictionary
        else:
            if episode_key in episode_watched_list_2_keys_dict.keys():
                # If the episode_value is in the episode_watched_list_2_keys_dict dictionary, return True
                if episode_value in episode_watched_list_2_keys_dict[episode_key]:
                    return True

    # If the loop completes without finding a match, return False
    return False


def generate_user_list(server):
    # generate list of users from server 1 and server 2
    server_type = server[0]
    server_connection = server[1]
    
    server_users = []
    if server_type == "plex":
        server_users = [x.title.lower() for x in server_connection.users]
    elif server_type == "jellyfin":
        server_users = [key.lower() for key in server_connection.users.keys()]

    return server_users

def combine_user_lists(server_1_users, server_2_users, user_mapping):
    # combined list of overlapping users from plex and jellyfin
    users = {}

    for server_1_user in server_1_users:
        if user_mapping:
            jellyfin_plex_mapped_user = search_mapping(user_mapping, server_1_user)
            if jellyfin_plex_mapped_user:
                users[server_1_user] = jellyfin_plex_mapped_user
                continue

        if server_1_user in server_2_users:
            users[server_1_user] = server_1_user

    for server_2_user in server_2_users:
        if user_mapping:
            plex_jellyfin_mapped_user = search_mapping(user_mapping, server_2_user)
            if plex_jellyfin_mapped_user:
                users[plex_jellyfin_mapped_user] = server_2_user
                continue

        if server_2_user in server_1_users:
            users[server_2_user] = server_2_user

    return users

def filter_user_lists(users, blacklist_users, whitelist_users):
    users_filtered = {}
    for user in users:
        # whitelist_user is not empty and user lowercase is not in whitelist lowercase
        if len(whitelist_users) > 0:
            if user not in whitelist_users and users[user] not in whitelist_users:
                logger(f"{user} or {users[user]} is not in whitelist", 1)
                continue

        if user not in blacklist_users and users[user] not in blacklist_users:
            users_filtered[user] = users[user]

    return users_filtered

def generate_server_users(server, users):
    server_users = None

    if server[0] == "plex":
        server_users = []
        for plex_user in server[1].users:
            if (
                plex_user.title.lower() in users.keys()
                or plex_user.title.lower() in users.values()
            ):
                server_users.append(plex_user)
    elif server[0] == "jellyfin":
        server_users = {}
        for jellyfin_user, jellyfin_id in server[1].users.items():
            if (
                jellyfin_user.lower() in users.keys()
                or jellyfin_user.lower() in users.values()
            ):
                server_users[jellyfin_user] = jellyfin_id
    
    return server_users

def future_thread_executor(args: list, workers: int = -1):
    futures_list = []
    results = []

    if workers == -1:
        workers = min(32, os.cpu_count() * 2)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for arg in args:
            # * arg unpacks the list into actual arguments
            futures_list.append(executor.submit(*arg))

        for future in futures_list:
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                raise Exception(e)

    return results
