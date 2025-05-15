import os
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable
from dotenv import load_dotenv

load_dotenv(override=True)

mark_file = os.getenv("MARK_FILE", os.getenv("MARKFILE", "mark.log"))


def log_marked(
    server_type: str,
    server_name: str,
    username: str,
    library: str,
    movie_show: str,
    episode: str | None = None,
    duration: float | None = None,
) -> None:
    output = f"{server_type}/{server_name}/{username}/{library}/{movie_show}"

    if episode:
        output += f"/{episode}"

    if duration:
        output += f"/{duration}"

    with open(mark_file, "a", encoding="utf-8") as file:
        file.write(output + "\n")


# Reimplementation of distutils.util.strtobool due to it being deprecated
# Source: https://github.com/PostHog/posthog/blob/01e184c29d2c10c43166f1d40a334abbc3f99d8a/posthog/utils.py#L668
def str_to_bool(value: str) -> bool:
    if not value:
        return False
    return str(value).lower() in ("y", "yes", "t", "true", "on", "1")


# Get mapped value
def search_mapping(dictionary: dict[str, str], key_value: str) -> str | None:
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


# Return list of objects that exist in both lists including mappings
def match_list(
    list1: list[str], list2: list[str], list_mapping: dict[str, str] | None = None
) -> list[str]:
    output: list[str] = []
    for element in list1:
        if element in list2:
            output.append(element)
        elif list_mapping:
            element_other = search_mapping(list_mapping, element)
            if element_other in list2:
                output.append(element)

    return output


def future_thread_executor(
    args: list[tuple[Callable[..., Any], ...]],
    threads: int | None = None,
    override_threads: bool = False,
) -> list[Any]:
    results: list[Any] = []

    # Determine the number of workers, defaulting to 1 if os.cpu_count() returns None
    max_threads_env: int = int(os.getenv("MAX_THREADS", 32))
    cpu_threads: int = os.cpu_count() or 1  # Default to 1 if os.cpu_count() is None
    workers: int = min(max_threads_env, cpu_threads * 2)

    # Adjust workers based on threads parameter and override_threads flag
    if threads is not None:
        workers = min(threads, workers)
    if override_threads:
        workers = threads if threads is not None else workers

    # If only one worker, run in main thread to avoid overhead
    if workers == 1:
        for arg in args:
            results.append(arg[0](*arg[1:]))
        return results

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures_list: list[Future[Any]] = []

        for arg in args:
            # * arg unpacks the list into actual arguments
            futures_list.append(executor.submit(*arg))

        for out in futures_list:
            try:
                result = out.result()
                results.append(result)
            except Exception as e:
                raise Exception(e)

    return results


def parse_string_to_list(string: str | None) -> list[str]:
    output: list[str] = []
    if string and len(string) > 0:
        output = string.split(",")

    return output
