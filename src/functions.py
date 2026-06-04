import json
import os
import re
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

from loguru import logger
from loguru._defaults import LOGURU_FORMAT
from pydantic import BaseModel


def _json_default(o):
    # dataclasses
    if is_dataclass(o):
        return asdict(o)
    # enums
    if isinstance(o, Enum):
        return o.value  # or o.name
    # anything else: fallback to string
    return str(o)


def formatter(record) -> str:
    def_format = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
        "{level: <8} | "
        "{name}:{function}:{line} - "
        "{message}"
    )
    base = def_format.format_map(record)
    data = record["extra"].get("data", "")

    # normalize pydantic models to dicts
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")

    if isinstance(data, dict) or hasattr(data, "__dataclass_fields__"):
        data_str = json.dumps(data, indent=4, default=_json_default)
        lines = [line.rstrip() for line in data_str.splitlines()]
        lines.insert(0, "")
    elif isinstance(data, list):
        lines = [f"{item}" for item in data]
        lines.insert(0, "")
    else:
        lines = [str(data)]

    indent = "\n  " + (" " * (len(base.replace(record["message"], "").strip()) + 1))
    record["extra"]["formatted_data"] = indent.join(lines)
    return LOGURU_FORMAT + "{extra[formatted_data]}\n{exception}"


def configure_logger(
    log_file: Path = Path("log.log"), debug_level: str = "INFO"
) -> None:
    # Remove default logger to configure our own
    logger.remove()

    # Choose log level based on environment
    # If in debug mode with a "debug" level, use DEBUG; otherwise, default to INFO.
    debug_level = debug_level.upper()

    if debug_level not in ["INFO", "DEBUG", "TRACE"]:
        logger.add(sys.stdout)
        msg = f"Invalid DEBUG_LEVEL {debug_level}, please choose between INFO, DEBUG, TRACE"
        raise Exception(msg)

    # Add a sink for file logging and the console.
    logger.add(sink=log_file, level=debug_level, mode="w", format=formatter)
    logger.add(sink=sys.stdout, level=debug_level, format=formatter)


def log_marked(
    server_type: str,
    server_name: str,
    username: str,
    library: str,
    movie_show: str,
    episode: str | None = None,
    duration: float | None = None,
    mark_file: Path = Path("mark.log"),
) -> None:
    output = f"{server_type}/{server_name}/{username}/{library}/{movie_show}"

    if episode:
        output += f"/{episode}"

    if duration:
        output += f"/{duration}"

    with open(mark_file, "a", encoding="utf-8") as file:
        file.write(output + "\n")


def get_env_value(env, key: str, default: Any = None):
    if env and key in env:
        return env[key]
    elif os.getenv(key):
        return os.getenv(key)
    else:
        return default


def future_thread_executor(
    args: list[tuple[Callable[..., Any], ...]],
    threads: int | None = None,
    override_threads: bool = False,
    max_threads: int | None = None,
) -> list[Any]:
    results: list[Any] = []

    # Determine the number of workers, defaulting to 1 if os.cpu_count() returns None
    cpu_threads: int = os.cpu_count() or 1  # Default to 1 if os.cpu_count() is None
    workers: int = min(max_threads, cpu_threads * 2) if max_threads else cpu_threads * 2

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


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")  # e.g. C: D:


def filename_from_any_path(p: str) -> str:
    # Windows-y if UNC (\\server\share), drive letter, or has backslashes
    if p.startswith("\\\\") or _WINDOWS_DRIVE.match(p) or ("\\" in p and "/" not in p):
        return PureWindowsPath(p).name
    return PurePosixPath(p).name


def to_aware_utc(dt: datetime | None) -> datetime | None:
    """Return a timezone-aware UTC datetime or None."""
    if dt is None:
        return None
    # If naive, decide what it *means* in your app. Here we treat naive as UTC.
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
