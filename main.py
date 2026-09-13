import sys

from pydantic import ValidationError
from pydantic_settings import SettingsError
from yaml import YAMLError


def _format_startup_error(error: Exception) -> str:
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

    return "configuration failed to load"


if __name__ == "__main__":
    # Check python version 3.12 or higher
    if not (3, 12) <= tuple(map(int, sys.version_info[:2])):
        print("This script requires Python 3.12 or higher")
        sys.exit(1)

    from src.main import main

    try:
        main()
    except (ValidationError, SettingsError, YAMLError) as error:
        print(f"Startup error: {_format_startup_error(error)}", file=sys.stderr)
        sys.exit(1)
