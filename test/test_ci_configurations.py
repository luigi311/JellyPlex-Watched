from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from src.legacy_settings import LEGACY_ENV_VARS
from src.settings import AppSettings, load_settings


ROOT = Path(__file__).resolve().parents[1]

_SCENARIOS = {
    "plex": {
        "plex-main": ["jellyfin-main", "emby-main"],
        "jellyfin-main": [],
        "emby-main": [],
    },
    "jellyfin": {
        "plex-main": [],
        "jellyfin-main": ["plex-main", "emby-main"],
        "emby-main": [],
    },
    "emby": {
        "plex-main": [],
        "jellyfin-main": [],
        "emby-main": ["plex-main", "jellyfin-main"],
    },
    "guids": {
        "plex-main": ["jellyfin-main", "emby-main"],
        "jellyfin-main": ["plex-main", "emby-main"],
        "emby-main": ["plex-main", "jellyfin-main"],
    },
    "locations": {
        "plex-main": ["jellyfin-main", "emby-main"],
        "jellyfin-main": ["plex-main", "emby-main"],
        "emby-main": ["plex-main", "jellyfin-main"],
    },
    "write": {
        "plex-main": ["jellyfin-main", "emby-main"],
        "jellyfin-main": ["plex-main", "emby-main"],
        "emby-main": ["plex-main", "jellyfin-main"],
    },
}

_COMMON_FIELDS = (
    "dryrun",
    "debug_level",
    "run_only_once",
    "sleep_duration",
    "log_file",
    "mark_file",
    "request_timeout",
    "max_threads",
    "generate_guids",
    "generate_locations",
    "blacklist_libraries",
    "whitelist_libraries",
    "blacklist_library_types",
    "whitelist_library_types",
    "blacklist_users",
    "whitelist_users",
)

_USER_ALIASES = [
    {"server": "plex-main", "username": "jellyplex_watched"},
    {"server": "jellyfin-main", "username": "JellyUser"},
    {"server": "emby-main", "username": "jellyplex_watched"},
]

_LIBRARY_ALIASES = [
    {"server": "plex-main", "library": "TV Shows"},
    {"server": "jellyfin-main", "library": "Shows"},
    {"server": "emby-main", "library": "TV Shows"},
]


def _clear_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    recognized_names = {
        *AppSettings.model_fields,
        *LEGACY_ENV_VARS,
        "ENV_FILE",
        "YAML_FILE",
    }
    recognized_names = {name.casefold() for name in recognized_names}
    for key in list(os.environ):
        if key.casefold() in recognized_names or key.casefold().startswith("jpw_"):
            monkeypatch.delenv(key, raising=False)


def _secret_value(value: SecretStr | None) -> str:
    assert value is not None
    return value.get_secret_value()


def _common_values(settings: AppSettings) -> tuple[object, ...]:
    return tuple(getattr(settings, name) for name in _COMMON_FIELDS)


def _server_values(settings: AppSettings) -> dict[str, tuple[object, ...]]:
    return {
        server.name: (
            server.baseurl,
            _secret_value(getattr(server, "token", None)),
            tuple(sorted(server.sync_to)),
            getattr(server, "ssl_bypass", None),
        )
        for server in settings.all_servers
    }


def _assert_explicit_mappings(settings: AppSettings) -> None:
    assert settings.user_mappings[0].model_dump() == {
        "canonical": "JellyUser",
        "aliases": _USER_ALIASES,
        "legacy": False,
    }
    assert settings.library_mappings[0].model_dump() == {
        "canonical": "Shows",
        "aliases": _LIBRARY_ALIASES,
        "legacy": False,
    }

    user_targets = (
        ("plex-main", "jellyplex_watched", "jellyfin-main", ["JellyUser"]),
        ("jellyfin-main", "JellyUser", "plex-main", ["jellyplex_watched"]),
        ("emby-main", "jellyplex_watched", "jellyfin-main", ["JellyUser"]),
        ("jellyfin-main", "JellyUser", "emby-main", ["jellyplex_watched"]),
    )
    for source, username, target, expected in user_targets:
        assert settings.sync_targets_for_user(source, username, target) == expected

    library_targets = (
        ("plex-main", "TV Shows", "jellyfin-main", ["Shows"]),
        ("jellyfin-main", "Shows", "plex-main", ["TV Shows"]),
        ("emby-main", "TV Shows", "jellyfin-main", ["Shows"]),
        ("jellyfin-main", "Shows", "emby-main", ["TV Shows"]),
    )
    for source, library, target, expected in library_targets:
        assert settings.sync_targets_for_library(source, library, target) == expected


def test_authored_ci_yaml_matches_legacy_fixtures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_settings_environment(monkeypatch)

    for stem, expected_directions in _SCENARIOS.items():
        legacy = load_settings(
            env_file=ROOT / "test" / f"ci_{stem}.env",
            yaml_file=tmp_path / f"missing-{stem}.yaml",
            auto_migrate=False,
        )
        authored = load_settings(
            env_file=tmp_path / f"missing-{stem}.env",
            yaml_file=ROOT / "test" / f"ci_{stem}.yaml",
            auto_migrate=False,
        )

        assert _common_values(authored) == _common_values(legacy), stem
        assert _server_values(authored) == _server_values(legacy), stem
        assert {
            server.name: sorted(server.sync_to)
            for server in authored.all_servers
        } == {
            name: sorted(targets) for name, targets in expected_directions.items()
        }, stem
        _assert_explicit_mappings(authored)

    prefixed = load_settings(
        env_file=ROOT / "test" / "ci_prefixed.env",
        yaml_file=ROOT / "test" / "ci_plex.yaml",
        auto_migrate=False,
    )
    assert prefixed.max_threads == 1
    assert _secret_value(prefixed.plex[0].token) == "6S28yhwKg4y-vAXYMi1c"
