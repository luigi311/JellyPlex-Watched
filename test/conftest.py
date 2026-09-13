import os
import sys
from typing import Any

# getting the name of the directory
# where the this file is present.
current = os.path.dirname(os.path.realpath(__file__))

# Getting the parent directory name
# where the current directory is present.
parent = os.path.dirname(current)

# adding the parent directory to
# the sys.path.
sys.path.append(parent)


from src.settings import AppSettings  # noqa: E402


def settings_override(**overrides) -> AppSettings:
    base: dict[str, Any] = {
        "plex": [
            {
                "name": "plex-main",
                "baseurl": "http://plex",
                "token": "x",
                "sync_to": ["jellyfin-main"],
            }
        ],
        "jellyfin": [
            {
                "name": "jellyfin-main",
                "baseurl": "http://jellyfin",
                "token": "x",
                "sync_to": ["plex-main"],
            }
        ],
    }
    base.update(overrides)
    return AppSettings(**base)
