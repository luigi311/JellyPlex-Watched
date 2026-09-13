"""Resolve runtime file paths before the container drops privileges."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import ValidationError
from pydantic_settings import SettingsError
from yaml import YAMLError

from src.settings import load_settings


def _format_configuration_error(error: Exception) -> str:
    if isinstance(error, ValidationError):
        details = []
        for detail in error.errors(include_context=False, include_input=False):
            location = ".".join(str(part) for part in detail["loc"]) or "configuration"
            details.append(f"{location}: {detail['msg']}")
        return "configuration validation failed: " + "; ".join(details)

    if isinstance(error, SettingsError):
        return "configuration source error; check environment, dotenv, and YAML values"

    if isinstance(error, YAMLError):
        mark = getattr(error, "problem_mark", None)
        if mark is not None:
            return (
                "invalid YAML configuration at "
                f"line {mark.line + 1}, column {mark.column + 1}"
            )
        return "invalid YAML configuration"

    if isinstance(error, ValueError):
        return "invalid runtime file path configuration"

    return "configuration could not be loaded"


def _resolve_runtime_file(path: Path) -> Path:
    resolved = Path(os.path.abspath(path))
    if any(character in str(resolved) for character in "\r\n\t"):
        raise ValueError("runtime file paths cannot contain control characters")
    if resolved == resolved.parent:
        raise ValueError("runtime file paths must name files")
    return resolved


def _runtime_files() -> tuple[Path, ...]:
    settings = load_settings(auto_migrate=False)
    paths = (
        _resolve_runtime_file(settings.log_file),
        _resolve_runtime_file(settings.mark_file),
    )
    return tuple(dict.fromkeys(paths))


def main() -> int:
    try:
        paths = _runtime_files()
    except (OSError, ValueError, ValidationError, SettingsError, YAMLError) as error:
        print(f"Startup error: {_format_configuration_error(error)}", file=sys.stderr)
        return 1

    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
