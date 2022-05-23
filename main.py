import copy, os
from dotenv import load_dotenv

from src.functions import logger, str_to_bool
from src.plex import Plex
from src.jellyfin import Jellyfin

load_dotenv(override=True)

def cleanup_watched(watched_list_1, watched_list_2):
    modified_watched_list_1 = copy.deepcopy(watched_list_1)
    
    # remove entries from plex_watched that are in jellyfin_watched
    for user in watched_list_1:
        if user in modified_watched_list_1:
            for library in watched_list_1[user]:
                if library in modified_watched_list_1[user]:
                    for item in watched_list_1[user][library]:
                        if item in modified_watched_list_1[user][library]:
                            if user in watched_list_2 and library in watched_list_2[user]:
                                # Movies
                                if isinstance(watched_list_1[user][library], list):
                                    for watch_list_1_key, watch_list_1_value in item.items():
                                        for watch_list_2_item in watched_list_2[user][library]:
                                            for watch_list_2_item_key, watch_list_2_item_value in watch_list_2_item.items():
                                                if watch_list_1_key == watch_list_2_item_key and watch_list_1_value == watch_list_2_item_value:
                                                    if item in modified_watched_list_1[user][library]:
                                                        modified_watched_list_1[user][library].remove(item)
                                
                                # TV Shows
                                elif isinstance(watched_list_1[user][library], dict):
                                    if item in watched_list_2[user][library]:
                                        for season in watched_list_1[user][library][item]:
                                            if season in watched_list_2[user][library][item]:
                                                for episode in watched_list_1[user][library][item][season]:
                                                    for watch_list_1_episode_key, watch_list_1_episode_value in episode.items():
                                                        for watch_list_2_episode in watched_list_2[user][library][item][season]:
                                                            for watch_list_2_episode_key, watch_list_2_episode_value in watch_list_2_episode.items():
                                                                if watch_list_1_episode_key == watch_list_2_episode_key and watch_list_1_episode_value == watch_list_2_episode_value:
                                                                    if episode in modified_watched_list_1[user][library][item][season]:
                                                                        modified_watched_list_1[user][library][item][season].remove(episode)
                                        
                                            # If season is empty, remove season
                                            if len(modified_watched_list_1[user][library][item][season]) == 0:
                                                if season in modified_watched_list_1[user][library][item]:
                                                    del modified_watched_list_1[user][library][item][season]

                                    # If the show is empty, remove the show    
                                    if len(modified_watched_list_1[user][library][item]) == 0:
                                        if item in modified_watched_list_1[user][library]:
                                            del modified_watched_list_1[user][library][item]
                                
                    # If library is empty then remove it
                    if len(modified_watched_list_1[user][library]) == 0:
                        if library in modified_watched_list_1[user]:
                            del modified_watched_list_1[user][library]
        
        # If user is empty delete user
        if len(modified_watched_list_1[user]) == 0:
            del modified_watched_list_1[user]

    return modified_watched_list_1

def main():
    logfile = os.getenv("LOGFILE","log.log")
    # Delete logfile if it exists
    if os.path.exists(logfile):
        os.remove(logfile)

    dryrun = str_to_bool(os.getenv("DRYRUN", "False"))
    logger(f"Dryrun: {dryrun}", 1)
    plex = Plex()
    jellyfin = Jellyfin()

    blacklist_library = os.getenv("BLACKLIST_LIBRARY")
    if blacklist_library:
        if len(blacklist_library) > 0:
            blacklist_library = blacklist_library.split(",")
            blacklist_library = [x.lower().trim() for x in blacklist_library]
    else:
        blacklist_library = []
    logger(f"Blacklist Library: {blacklist_library}", 1)

    whitelist_library = os.getenv("WHITELIST_LIBRARY")
    if whitelist_library:
        if len(whitelist_library) > 0:
            whitelist_library = whitelist_library.split(",")
            whitelist_library = [x.lower().strip() for x in whitelist_library]
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
    # print whitelist_users object type
    if whitelist_users:
        if len(whitelist_users) > 0:
            whitelist_users = whitelist_users.split(",")
            whitelist_users = [x.lower().strip() for x in whitelist_users]
        else:
            whitelist_users = []
    else:
        whitelist_users = []
    logger(f"Whitelist Users: {whitelist_users}", 1)

    # generate list of users from plex.users
    plex_users = [ x.title.lower() for x in plex.users ]
    jellyfin_users = [ key.lower() for key in jellyfin.users.keys() ]
    
    # combined list of overlapping users from plex and jellyfin
    users = [x for x in plex_users if x in jellyfin_users]
    logger(f"User list that exist on both servers {users}", 1)
 
    users_filtered = []
    for user in users:
        # whitelist_user is not empty and user lowercase is not in whitelist lowercase
        if len(whitelist_users) > 0 and user.lower() not in whitelist_users:
            logger(f"{user} is not in whitelist", 1)
        else:
            if user.lower() not in blacklist_users:
                users_filtered.append(user)

    plex_users = []
    for plex_user in plex.users:
        if plex_user.title.lower() in users_filtered:
            plex_users.append(plex_user)
    
    jellyfin_users = {}
    for jellyfin_user, jellyfin_id in jellyfin.users.items():
        if jellyfin_user.lower() in users_filtered:
            jellyfin_users[jellyfin_user] = jellyfin_id

    logger(f"plex_users: {plex_users}", 1)
    logger(f"jellyfin_users: {jellyfin_users}", 1)

    if len(plex_users) == 0:
        logger("No users found", 2)
        raise Exception("No users found")

    if len(jellyfin_users) == 0:
        logger("No users found", 2)
        raise Exception("No users found")

    plex_watched = plex.get_plex_watched(plex_users, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type)
    jellyfin_watched = jellyfin.get_jellyfin_watched(jellyfin_users, blacklist_library, whitelist_library, blacklist_library_type, whitelist_library_type)

    # clone watched so it isnt modified in the cleanup function so all duplicates are actually removed
    plex_watched_filtered = copy.deepcopy(plex_watched)
    jellyfin_watched_filtered = copy.deepcopy(jellyfin_watched)

    plex_watched = cleanup_watched(plex_watched_filtered, jellyfin_watched_filtered)
    logger(f"plex_watched that needs to be synced to jellyfin:\n{plex_watched}", 1)

    jellyfin_watched = cleanup_watched(jellyfin_watched_filtered, plex_watched_filtered)
    logger(f"jellyfin_watched that needs to be synced to plex:\n{jellyfin_watched}", 1)

    # Update watched status
    plex.update_watched(jellyfin_watched, dryrun)
    jellyfin.update_watched(plex_watched, dryrun)
    

if __name__ == "__main__":
    sleep_timer = float(os.getenv("SLEEP_TIMER", "3600"))
    while(True):
        main()
        sleep(sleep_timer)