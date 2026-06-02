import os
import sys

from pydantic_settings import SettingsConfigDict

# getting the name of the directory
# where the this file is present.
current = os.path.dirname(os.path.realpath(__file__))

# Getting the parent directory name
# where the current directory is present.
parent = os.path.dirname(current)

# adding the parent directory to
# the sys.path.
sys.path.append(parent)


from src.settings import AppSettings


class _IsolatedAppSettings(AppSettings):
    """
    AppSettings that ignores all external configuration sources (env vars,
    .env, legacy .env, config.yaml) so tests depend only on the kwargs passed
    in. Without this, constructing AppSettings would read the developer's real
    .env / config.yaml and contaminate the test.
    """

    model_config = SettingsConfigDict(
        yaml_file=None,
        yaml_file_encoding=None,
        nested_model_default_partial_update=True,
        extra="forbid",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (init_settings,)


def settings_override(**overrides) -> AppSettings:
    base = {
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
    return _IsolatedAppSettings(**base)
