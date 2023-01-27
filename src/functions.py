import os
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
