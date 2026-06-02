import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import pytest

# Add the parent directory to sys.path so we can import from src/
current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
sys.path.append(parent)

from src.functions import (
    _json_default,
    configure_logger,
    filename_from_any_path,
    get_env_value,
    to_aware_utc,
)


# ---------------------------------------------------------------------------
# _json_default
# ---------------------------------------------------------------------------


def test_json_default_dataclass():
    @dataclass
    class Point:
        x: int
        y: int

    p = Point(x=1, y=2)
    result = _json_default(p)
    assert result == {"x": 1, "y": 2}


def test_json_default_enum():
    class Color(Enum):
        RED = "red"
        GREEN = "green"

    assert _json_default(Color.RED) == "red"
    assert _json_default(Color.GREEN) == "green"


def test_json_default_other_falls_back_to_str():
    result = _json_default(Path("/some/path"))
    assert isinstance(result, str)
    assert "/some/path" in result


def test_json_default_used_in_json_dumps():
    @dataclass
    class Item:
        name: str
        count: int

    item = Item(name="test", count=5)
    output = json.dumps(item, default=_json_default)
    parsed = json.loads(output)
    assert parsed == {"name": "test", "count": 5}


# ---------------------------------------------------------------------------
# configure_logger
# ---------------------------------------------------------------------------


def test_configure_logger_info_level(tmp_path):
    log_file = tmp_path / "test.log"
    configure_logger(log_file, "INFO")
    # Should not raise; log file path is accepted as Path
    assert True


def test_configure_logger_debug_level(tmp_path):
    log_file = tmp_path / "test.log"
    configure_logger(log_file, "DEBUG")
    assert True


def test_configure_logger_trace_level(tmp_path):
    log_file = tmp_path / "test.log"
    configure_logger(log_file, "TRACE")
    assert True


def test_configure_logger_invalid_level_raises(tmp_path):
    log_file = tmp_path / "test.log"
    with pytest.raises(Exception, match="Invalid DEBUG_LEVEL"):
        configure_logger(log_file, "VERBOSE")


def test_configure_logger_uppercase_conversion(tmp_path):
    log_file = tmp_path / "test.log"
    # Lowercase should be accepted and converted
    configure_logger(log_file, "info")
    assert True


def test_configure_logger_invalid_lowercase_raises(tmp_path):
    log_file = tmp_path / "test.log"
    with pytest.raises(Exception, match="Invalid DEBUG_LEVEL"):
        configure_logger(log_file, "warning")


def test_configure_logger_accepts_path_object(tmp_path):
    log_file = tmp_path / "mylog.log"
    configure_logger(log_file=log_file, debug_level="INFO")
    assert True


# ---------------------------------------------------------------------------
# get_env_value
# ---------------------------------------------------------------------------


def test_get_env_value_from_dict():
    env = {"MY_KEY": "myvalue"}
    assert get_env_value(env, "MY_KEY") == "myvalue"


def test_get_env_value_dict_key_missing_falls_back_to_process_env(monkeypatch):
    monkeypatch.setenv("PROCESS_KEY", "process_value")
    assert get_env_value({}, "PROCESS_KEY") == "process_value"


def test_get_env_value_default_returned_when_missing(monkeypatch):
    monkeypatch.delenv("MISSING_KEY", raising=False)
    result = get_env_value({}, "MISSING_KEY", default="fallback")
    assert result == "fallback"


def test_get_env_value_none_env_falls_back_to_process(monkeypatch):
    monkeypatch.setenv("NONE_ENV_KEY", "hello")
    assert get_env_value(None, "NONE_ENV_KEY") == "hello"


def test_get_env_value_dict_takes_precedence_over_process_env(monkeypatch):
    monkeypatch.setenv("OVERRIDE_KEY", "process_value")
    env = {"OVERRIDE_KEY": "dict_value"}
    assert get_env_value(env, "OVERRIDE_KEY") == "dict_value"


def test_get_env_value_returns_none_by_default_when_missing(monkeypatch):
    monkeypatch.delenv("TOTALLY_MISSING", raising=False)
    assert get_env_value({}, "TOTALLY_MISSING") is None


# ---------------------------------------------------------------------------
# filename_from_any_path
# ---------------------------------------------------------------------------


def test_filename_from_posix_path():
    assert filename_from_any_path("/home/user/movies/BigBuckBunny.mkv") == "BigBuckBunny.mkv"


def test_filename_from_posix_path_no_dir():
    assert filename_from_any_path("movie.mkv") == "movie.mkv"


def test_filename_from_windows_path():
    assert filename_from_any_path("C:\\Movies\\BigBuckBunny.mkv") == "BigBuckBunny.mkv"


def test_filename_from_windows_unc_path():
    assert filename_from_any_path("\\\\server\\share\\BigBuckBunny.mkv") == "BigBuckBunny.mkv"


def test_filename_from_windows_relative_with_backslash():
    assert filename_from_any_path("movies\\BigBuckBunny.mkv") == "BigBuckBunny.mkv"


def test_filename_from_posix_with_extension():
    assert filename_from_any_path("/data/shows/S01E03.mkv") == "S01E03.mkv"


def test_filename_from_windows_drive_letter():
    assert filename_from_any_path("D:\\Shows\\S01E03.mkv") == "S01E03.mkv"


def test_filename_from_path_with_spaces():
    assert filename_from_any_path("/home/user/my movies/Big Buck Bunny.mkv") == "Big Buck Bunny.mkv"


# ---------------------------------------------------------------------------
# to_aware_utc
# ---------------------------------------------------------------------------


def test_to_aware_utc_none_returns_none():
    assert to_aware_utc(None) is None


def test_to_aware_utc_naive_datetime_returns_utc():
    naive = datetime(2024, 1, 15, 10, 30, 0)
    result = to_aware_utc(naive)
    assert result is not None
    assert result.tzinfo is not None
    assert result.tzinfo == timezone.utc
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 15


def test_to_aware_utc_already_utc_returns_same_time():
    utc_dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = to_aware_utc(utc_dt)
    assert result == utc_dt
    assert result.tzinfo == timezone.utc


def test_to_aware_utc_different_timezone_converts_to_utc():
    from datetime import timedelta

    # A timezone offset of +5 hours
    plus5 = timezone(timedelta(hours=5))
    dt_plus5 = datetime(2024, 1, 15, 15, 0, 0, tzinfo=plus5)
    result = to_aware_utc(dt_plus5)
    assert result is not None
    assert result.tzinfo == timezone.utc
    # 15:00 +5 = 10:00 UTC
    assert result.hour == 10
    assert result.day == 15


def test_to_aware_utc_preserves_microseconds():
    naive = datetime(2024, 3, 10, 8, 0, 0, 123456)
    result = to_aware_utc(naive)
    assert result is not None
    assert result.microsecond == 123456