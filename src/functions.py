import os
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

load_dotenv(override=True)

logfile = os.getenv("LOGFILE", "log.log")
markfile = os.getenv("MARKFILE", "mark.log")


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
    elif log_type == 5:
        output = f"[MARK]: {output}"
    elif log_type == 6:
        output = f"[DRYRUN]: {output}"
    else:
        output = None

    if output is not None:
        print(output)
        file = open(logfile, "a", encoding="utf-8")
        file.write(output + "\n")


def log_marked(
    username: str, library: str, movie_show: str, episode: str = None, duration=None
):
    if markfile is None:
        return

    output = f"{username}/{library}/{movie_show}"

    if episode:
        output += f"/{episode}"

    if duration:
        output += f"/{duration}"

    file = open(f"{markfile}", "a", encoding="utf-8")
    file.write(output + "\n")


# Reimplementation of distutils.util.strtobool due to it being deprecated
# Source: https://github.com/PostHog/posthog/blob/01e184c29d2c10c43166f1d40a334abbc3f99d8a/posthog/utils.py#L668
def str_to_bool(value: any) -> bool:
    if not value:
        return False
    return str(value).lower() in ("y", "yes", "t", "true", "on", "1")


# Search for nested element in list
def contains_nested(element, lst):
    if lst is None:
        return None

    for i, item in enumerate(lst):
        if item is None:
            continue
        if element in item:
            return i
        elif element == item:
            return i
    return None


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


def future_thread_executor(
    args: list, threads: int = None, override_threads: bool = False
):
    futures_list = []
    results = []

    workers = min(int(os.getenv("MAX_THREADS", 32)), os.cpu_count() * 2)
    if threads:
        workers = min(threads, workers)

    if override_threads:
        workers = threads

    # If only one worker, run in main thread to avoid overhead
    if workers == 1:
        results = []
        for arg in args:
            results.append(arg[0](*arg[1:]))
        return results

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
