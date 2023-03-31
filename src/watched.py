import copy

from src.functions import (
    logger,
    search_mapping,
)

from src.library import generate_library_guids_dict


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


def check_remove_entry(video, library, video_index, library_watched_list_2):
    if video_index is not None:
        if (
            library_watched_list_2["completed"][video_index]
            == video["status"]["completed"]
        ) and (library_watched_list_2["time"][video_index] == video["status"]["time"]):
            logger(
                f"Removing {video['title']} from {library} due to exact match",
                3,
            )
            return True
        elif (
            library_watched_list_2["completed"][video_index] == True
            and video["status"]["completed"] == False
        ):
            logger(
                f"Removing {video['title']} from {library} due to being complete in one library and not the other",
                3,
            )
            return True
        elif (
            library_watched_list_2["completed"][video_index] == False
            and video["status"]["completed"] == False
        ) and (video["status"]["time"] < library_watched_list_2["time"][video_index]):
            logger(
                f"Removing {video['title']} from {library} due to more time watched in one library than the other",
                3,
            )
            return True
        elif (
            library_watched_list_2["completed"][video_index] == True
            and video["status"]["completed"] == True
        ):
            logger(
                f"Removing {video['title']} from {library} due to being complete in both libraries",
                3,
            )
            return True

    return False


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
                    movie_index = get_movie_index_in_dict(
                        movie, movies_watched_list_2_keys_dict
                    )
                    if movie_index is not None:
                        if check_remove_entry(
                            movie,
                            library_1,
                            movie_index,
                            movies_watched_list_2_keys_dict,
                        ):
                            modified_watched_list_1[user_1][library_1].remove(movie)

            # TV Shows
            elif isinstance(watched_list_1[user_1][library_1], dict):
                for show_key_1 in watched_list_1[user_1][library_1].keys():
                    show_key_dict = dict(show_key_1)
                    for season in watched_list_1[user_1][library_1][show_key_1]:
                        for episode in watched_list_1[user_1][library_1][show_key_1][
                            season
                        ]:
                            episode_index = get_episode_index_in_dict(
                                episode, episode_watched_list_2_keys_dict
                            )
                            if episode_index is not None:
                                if check_remove_entry(
                                    episode,
                                    library_1,
                                    episode_index,
                                    episode_watched_list_2_keys_dict,
                                ):
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


def get_other(watched_list, object_1, object_2):
    if object_1 in watched_list:
        return object_1
    elif object_2 in watched_list:
        return object_2
    else:
        logger(f"{object_1} and {object_2} not found in watched list 2", 1)
        return None


def get_movie_index_in_dict(movie, movies_watched_list_2_keys_dict):
    # Iterate through the keys and values of the movie dictionary
    for movie_key, movie_value in movie.items():
        # If the key is "locations", check if the "locations" key is present in the movies_watched_list_2_keys_dict dictionary
        if movie_key == "locations":
            if "locations" in movies_watched_list_2_keys_dict.keys():
                # Iterate through the locations in the movie dictionary
                for location in movie_value:
                    # If the location is in the movies_watched_list_2_keys_dict dictionary, return index of the key
                    if location in movies_watched_list_2_keys_dict["locations"]:
                        return movies_watched_list_2_keys_dict["locations"].index(
                            location
                        )

        # If the key is not "locations", check if the movie_key is present in the movies_watched_list_2_keys_dict dictionary
        else:
            if movie_key in movies_watched_list_2_keys_dict.keys():
                # If the movie_value is in the movies_watched_list_2_keys_dict dictionary, return True
                if movie_value in movies_watched_list_2_keys_dict[movie_key]:
                    return movies_watched_list_2_keys_dict[movie_key].index(movie_value)

    # If the loop completes without finding a match, return False
    return None


def get_episode_index_in_dict(episode, episode_watched_list_2_keys_dict):
    # Iterate through the keys and values of the episode dictionary
    for episode_key, episode_value in episode.items():
        # If the key is "locations", check if the "locations" key is present in the episode_watched_list_2_keys_dict dictionary
        if episode_key == "locations":
            if "locations" in episode_watched_list_2_keys_dict.keys():
                # Iterate through the locations in the episode dictionary
                for location in episode_value:
                    # If the location is in the episode_watched_list_2_keys_dict dictionary, return index of the key
                    if location in episode_watched_list_2_keys_dict["locations"]:
                        return episode_watched_list_2_keys_dict["locations"].index(
                            location
                        )
        # If the key is not "locations", check if the episode_key is present in the episode_watched_list_2_keys_dict dictionary
        else:
            if episode_key in episode_watched_list_2_keys_dict.keys():
                # If the episode_value is in the episode_watched_list_2_keys_dict dictionary, return True
                if episode_value in episode_watched_list_2_keys_dict[episode_key]:
                    return episode_watched_list_2_keys_dict[episode_key].index(
                        episode_value
                    )

    # If the loop completes without finding a match, return False
    return None
