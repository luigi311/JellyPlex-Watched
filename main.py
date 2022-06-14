import copy, os, traceback, json
from dotenv import load_dotenv
from time import sleep

from src.functions import logger, str_to_bool, search_mapping, generate_library_guids_dict
from src.plex import Plex
from src.jellyfin import Jellyfin

load_dotenv(override=True)

def cleanup_watched(watched_list_1, watched_list_2, user_mapping=None, library_mapping=None):
    modified_watched_list_1 = copy.deepcopy(watched_list_1)

    # remove entries from plex_watched that are in jellyfin_watched
    for user_1 in watched_list_1:
        user_other = None
        if user_mapping:
            user_other = search_mapping(user_mapping, user_1)
        if user_1 in modified_watched_list_1:
            if user_1 in watched_list_2:
                user_2 = user_1
            elif user_other in watched_list_2:
                user_2 = user_other
            else:
                logger(f"User {user_1} and {user_other} not found in watched list 2", 1)
                continue

            for library_1 in watched_list_1[user_1]:
                library_other = None
                if library_mapping:
                    library_other = search_mapping(library_mapping, library_1)
                if library_1 in modified_watched_list_1[user_1]:
                    if library_1 in watched_list_2[user_2]:
                        library_2 = library_1
                    elif library_other in watched_list_2[user_2]:
                        library_2 = library_other
                    else:
                        logger(f"library {library_1} and {library_other} not found in watched list 2", 1)
                        continue

                    # Movies
                    if isinstance(watched_list_1[user_1][library_1], list):
                        for item in watched_list_1[user_1][library_1]:
                            for watch_list_1_key, watch_list_1_value in item.items():
                                for watch_list_2_item in watched_list_2[user_2][library_2]:
                                    for watch_list_2_item_key, watch_list_2_item_value in watch_list_2_item.items():
                                        if watch_list_1_key == watch_list_2_item_key and watch_list_1_value == watch_list_2_item_value:
                                            if item in modified_watched_list_1[user_1][library_1]:
                                                logger(f"Removing {item} from {library_1}", 3)
                                                modified_watched_list_1[user_1][library_1].remove(item)


                    # TV Shows
                    elif isinstance(watched_list_1[user_1][library_1], dict):
                        # Generate full list of provider ids for episodes in watch_list_2 to easily compare if they exist in watch_list_1
                        _, episode_watched_list_2_keys_dict, _ = generate_library_guids_dict(watched_list_2[user_2][library_2], 1)

                        for show_key_1 in watched_list_1[user_1][library_1].keys():
                            show_key_dict = dict(show_key_1)
                            for season in watched_list_1[user_1][library_1][show_key_1]:
                                for episode in watched_list_1[user_1][library_1][show_key_1][season]:
                                    for episode_key, episode_item in episode.items():
                                        # If episode_key and episode_item are in episode_watched_list_2_keys_dict exactly, then remove from watch_list_1
                                        if episode_key in episode_watched_list_2_keys_dict.keys():
                                            if episode_item in episode_watched_list_2_keys_dict[episode_key]:
                                                if episode in modified_watched_list_1[user_1][library_1][show_key_1][season]:
                                                    logger(f"Removing {show_key_dict['title']} {episode} from {library_1}", 3)
                                                    modified_watched_list_1[user_1][library_1][show_key_1][season].remove(episode)

                                # Remove empty seasons
                                if len(modified_watched_list_1[user_1][library_1][show_key_1][season]) == 0:
                                    if season in modified_watched_list_1[user_1][library_1][show_key_1]:
                                        logger(f"Removing {season} from {library_1} because it is empty", 3)
                                        del modified_watched_list_1[user_1][library_1][show_key_1][season]

                            # If the show is empty, remove the show
                            if len(modified_watched_list_1[user_1][library_1][show_key_1]) == 0:
                                if show_key_1 in modified_watched_list_1[user_1][library_1]:
                                    logger(f"Removing {show_key_dict['title']} from {library_1} because it is empty", 1)
                                    del modified_watched_list_1[user_1][library_1][show_key_1]

                # If library is empty then remove it
                if len(modified_watched_list_1[user_1][library_1]) == 0:
                    if library_1 in modified_watched_list_1[user_1]:
                        logger(f"Removing {library_1} from {user_1} because it is empty", 1)
                        del modified_watched_list_1[user_1][library_1]

        # If user is empty delete user
        if len(modified_watched_list_1[user_1]) == 0:
            logger(f"Removing {user_1} from watched list 1 because it is empty", 1)
            del modified_watched_list_1[user_1]

    return modified_watched_list_1

def setup_black_white_lists(library_mapping=None):
    blacklist_library = os.getenv("BLACKLIST_LIBRARY")
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

    whitelist_library = os.getenv("WHITELIST_LIBRARY")
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

    blacklist_library_type = os.getenv("BLACKLIST_LIBRARY_TYPE")
    if blacklist_library_type:
        if len(blacklist_library_type) > 0:
            blacklist_library_type = blacklist_library_type.split(",")
            blacklist_library_type = [x.lower().strip() for x in blacklist_library_type]
    else:
        blacklist_library_type = []
    logger(f"Blacklist Library Type: {blacklist_library_type}", 1)

    whitelist_library_type = os.getenv("WHITELIST_LIBRARY_TYPE")
    if whitelist_library_type:
        if len(whitelist_library_type) > 0:
            whitelist_library_type = whitelist_library_type.split(",")
            whitelist_library_type = [x.lower().strip() for x in whitelist_library_type]
    else:
        whitelist_library_type = []
    logger(f"Whitelist Library Type: {whitelist_library_type}", 1)

    blacklist_users = os.getenv("BLACKLIST_USERS")
    if blacklist_users:
        if len(blacklist_users) > 0:
            blacklist_users = blacklist_users.split(",")
            blacklist_users = [x.lower().strip() for x in blacklist_users]
    else:
        blacklist_users = []
    logger(f"Blacklist Users: {blacklist_users}", 1)

    whitelist_users = os.getenv("WHITELIST_USERS")
    if whitelist_users:
        if len(whitelist_users) > 0:
            whitelist_users = whitelist_users.split(",")
            whitelist_users = [x.lower().strip() for x in whitelist_users]
        else:
            whitelist_users = []
    else:
        whitelist_users = []
    logger(f"Whitelist Users: {whitelist_users}", 1)

    return blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, blacklist_users, whitelist_users

def setup_users(plex, jellyfin, blacklist_users, whitelist_users, user_mapping=None):

    # generate list of users from plex.users
    plex_users = [ x.title.lower() for x in plex.users ]
    jellyfin_users = [ key.lower() for key in jellyfin.users.keys() ]

    # combined list of overlapping users from plex and jellyfin
    users = {}

    for plex_user in plex_users:
        if user_mapping:
            jellyfin_plex_mapped_user =  search_mapping(user_mapping, plex_user)
            if jellyfin_plex_mapped_user:
                users[plex_user] = jellyfin_plex_mapped_user
                continue

        if plex_user in jellyfin_users:
            users[plex_user] = plex_user

    for jellyfin_user in jellyfin_users:
        if user_mapping:
            plex_jellyfin_mapped_user =  search_mapping(user_mapping, jellyfin_user)
            if plex_jellyfin_mapped_user:
                users[plex_jellyfin_mapped_user] = jellyfin_user
                continue

        if jellyfin_user in plex_users:
            users[jellyfin_user] = jellyfin_user

    logger(f"User list that exist on both servers {users}", 1)

    users_filtered = {}
    for user in users:
        # whitelist_user is not empty and user lowercase is not in whitelist lowercase
        if len(whitelist_users) > 0:
            if user not in whitelist_users and users[user] not in whitelist_users:
                logger(f"{user} or {users[user]} is not in whitelist", 1)
                continue

        if user not in blacklist_users and users[user] not in blacklist_users:
            users_filtered[user] = users[user]

    logger(f"Filtered user list {users_filtered}", 1)

    plex_users = []
    for plex_user in plex.users:
        if plex_user.title.lower() in users_filtered.keys() or plex_user.title.lower() in users_filtered.values():
            plex_users.append(plex_user)

    jellyfin_users = {}
    for jellyfin_user, jellyfin_id in jellyfin.users.items():
        if jellyfin_user.lower() in users_filtered.keys() or jellyfin_user.lower() in users_filtered.values():
            jellyfin_users[jellyfin_user] = jellyfin_id

    if len(plex_users) == 0:
        raise Exception(f"No plex users found, users found {users} filtered users {users_filtered}")

    if len(jellyfin_users) == 0:
        raise Exception(f"No jellyfin users found, users found {users} filtered users {users_filtered}")

    logger(f"plex_users: {plex_users}", 1)
    logger(f"jellyfin_users: {jellyfin_users}", 1)

    return plex_users, jellyfin_users

def main():
    logfile = os.getenv("LOGFILE","log.log")
    # Delete logfile if it exists
    if os.path.exists(logfile):
        os.remove(logfile)

    dryrun = str_to_bool(os.getenv("DRYRUN", "False"))
    logger(f"Dryrun: {dryrun}", 1)

    user_mapping = os.getenv("USER_MAPPING")
    if user_mapping:
        user_mapping = json.loads(user_mapping.lower())
        logger(f"User Mapping: {user_mapping}", 1)

    library_mapping = os.getenv("LIBRARY_MAPPING")
    if library_mapping:
        library_mapping = json.loads(library_mapping)
        logger(f"Library Mapping: {library_mapping}", 1)

    plex = Plex()
    jellyfin = Jellyfin()

    # Create (black/white)lists
    blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, blacklist_users, whitelist_users = setup_black_white_lists(library_mapping)

    # Create users list
    plex_users, jellyfin_users = setup_users(plex, jellyfin, blacklist_users, whitelist_users, user_mapping)

    plex_watched = plex.get_plex_watched(plex_users, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, library_mapping)
    jellyfin_watched = jellyfin.get_jellyfin_watched(jellyfin_users, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type, library_mapping)

    # clone watched so it isnt modified in the cleanup function so all duplicates are actually removed
    plex_watched_filtered = copy.deepcopy(plex_watched)
    jellyfin_watched_filtered = copy.deepcopy(jellyfin_watched)

    logger("Cleaning Plex Watched", 1)
    plex_watched = cleanup_watched(plex_watched_filtered, jellyfin_watched_filtered, user_mapping, library_mapping)

    logger("Cleaning Jellyfin Watched", 1)
    jellyfin_watched = cleanup_watched(jellyfin_watched_filtered, plex_watched_filtered, user_mapping, library_mapping)

    logger(f"plex_watched that needs to be synced to jellyfin:\n{plex_watched}", 1)
    logger(f"jellyfin_watched that needs to be synced to plex:\n{jellyfin_watched}", 1)

    # Update watched status
    plex.update_watched(jellyfin_watched, user_mapping, library_mapping, dryrun)
    jellyfin.update_watched(plex_watched, user_mapping, library_mapping, dryrun)


if __name__ == "__main__":
    sleep_timer = float(os.getenv("SLEEP_TIMER", "3600"))

    while(True):
        try:
            main()
            logger(f"Looping in {sleep_timer}")
        except Exception as error:
            if isinstance(error, list):
                for message in error:
                    logger(message, log_type=2)
            else:
                logger(error, log_type=2)


            logger(traceback.format_exc(), 2)
            logger(f"Retrying in {sleep_timer}", log_type=0)

        except KeyboardInterrupt:
            logger("Exiting", log_type=0)
            os._exit(0)

        sleep(sleep_timer)
