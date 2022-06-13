import os
from dotenv import load_dotenv
load_dotenv(override=True)

logfile = os.getenv("LOGFILE","log.log")

def logger(message, log_type=0):
    debug = str_to_bool(os.getenv("DEBUG", "True"))

    output = str(message)
    if log_type == 0:
        pass
    elif log_type == 1 and debug:
        output = f"[INFO]: {output}"
    elif log_type == 2:
        output = f"[ERROR]: {output}"
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
        return dictionary[key_value]
    elif key_value in dictionary.values():
        return list(dictionary.keys())[list(dictionary.values()).index(key_value)]
    elif key_value.lower() in dictionary.values():
        return list(dictionary.keys())[list(dictionary.values()).index(key_value)]
    else:
        return None


def check_skip_logic(library_title, library_type, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, library_mapping):
    skip_reason = None

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


def generate_library_guids_dict(user_list: dict, generate_output: int):
    # if generate_output is 0 then only generate shows, if 1 then only generate episodes, if 2 then generate movies, if 3 then generate shows and episodes
    show_output_dict = {}
    episode_output_dict = {}
    movies_output_dict = {}

    if generate_output in (0, 3):
        show_output_keys = user_list.keys()
        show_output_keys = ([ dict(x) for x in list(show_output_keys) ])
        for show_key in show_output_keys:
            for provider_key, prvider_value in show_key.items():
                # Skip title
                if provider_key.lower() == "title":
                    continue
                if provider_key.lower() not in show_output_dict:
                    show_output_dict[provider_key.lower()] = []
                show_output_dict[provider_key.lower()].append(prvider_value.lower())
    
    if generate_output in (1, 3):
        for show in user_list:
            for season in user_list[show]:
                for episode in user_list[show][season]:
                    for episode_key, episode_value in episode.items():
                        if episode_key.lower() not in episode_output_dict:
                            episode_output_dict[episode_key.lower()] = []
                        episode_output_dict[episode_key.lower()].append(episode_value.lower())
    
    if generate_output == 2:
        for movie in user_list:
            for movie_key, movie_value in movie.items():
                if movie_key.lower() not in movies_output_dict:
                    movies_output_dict[movie_key.lower()] = []
                movies_output_dict[movie_key.lower()].append(movie_value.lower())

    return show_output_dict, episode_output_dict, movies_output_dict

