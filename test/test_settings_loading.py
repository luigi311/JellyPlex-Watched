from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import pytest
import yaml
from loguru import logger
from pydantic import SecretStr, ValidationError
from pydantic_settings import SettingsError

from conftest import settings_override
from src.legacy_settings import (
    LEGACY_ENV_VARS,
    legacy_env_to_field_dict,
    resolve_legacy_env,
)
from src.settings import (
    AppSettings,
    _SettingsLoader,
    _dump_for_yaml,
    _migrate_env_to_yaml,
    load_settings,
)


_CONFIGURATION_ENV_NAMES = {
    *AppSettings.model_fields,
    "ENV_FILE",
    "YAML_FILE",
}
_CONFIGURATION_ENV_NAMES_CASEFOLD = {
    name.casefold() for name in _CONFIGURATION_ENV_NAMES
}
_LEGACY_ENV_NAMES_CASEFOLD = {name.casefold() for name in LEGACY_ENV_VARS}


def _base_yaml() -> dict[str, Any]:
    return {
        "plex": [
            {
                "name": "plex-main",
                "baseurl": "http://plex",
                "token": "yaml-token",
                "sync_to": ["jellyfin-main"],
            }
        ],
        "jellyfin": [
            {
                "name": "jellyfin-main",
                "baseurl": "http://jellyfin",
                "token": "jellyfin-token",
                "sync_to": ["plex-main"],
            }
        ],
    }


def _full_yaml() -> dict[str, Any]:
    return {
        "dryrun": False,
        "debug_level": "TRACE",
        "run_only_once": True,
        "sleep_duration": 17,
        "log_file": "/tmp/jpw-settings.log",
        "mark_file": "/tmp/jpw-settings.mark",
        "request_timeout": 23,
        "max_threads": 4,
        "generate_guids": False,
        "generate_locations": True,
        "blacklist_libraries": ["Music"],
        "whitelist_libraries": ["Movies"],
        "blacklist_library_types": ["music"],
        "whitelist_library_types": ["movie"],
        "blacklist_users": ["blocked"],
        "whitelist_users": ["alice"],
        "plex": [
            {
                "name": "plex-main",
                "baseurl": "http://plex-main",
                "token": "plex-token",
                "sync_to": ["jellyfin-main", "emby-main"],
            },
            {
                "name": "plex-account",
                "baseurl": "http://plex-account",
                "username": "plex-user",
                "password": "plex-password",
                "servername": "Plex Account Server",
                "sync_to": [],
            },
        ],
        "jellyfin": [
            {
                "name": "jellyfin-main",
                "baseurl": "http://jellyfin-main",
                "token": "jellyfin-token",
                "sync_to": ["plex-main"],
            },
            {
                "name": "jellyfin-backup",
                "baseurl": "http://jellyfin-backup",
                "token": "jellyfin-backup-token",
                "sync_to": [],
            },
        ],
        "emby": [
            {
                "name": "emby-main",
                "baseurl": "http://emby-main",
                "token": "emby-token",
                "sync_to": ["plex-main"],
            }
        ],
        "user_mappings": [
            {
                "canonical": "alice",
                "aliases": [
                    {"server": "plex-main", "username": "alice-plex"},
                    {"server": "plex-account", "username": "alice"},
                    {"server": "jellyfin-main", "username": "alice-jellyfin"},
                    {"server": "jellyfin-backup", "username": "alice-backup"},
                    {"server": "emby-main", "username": "alice-emby"},
                ],
            },
            {
                "canonical": "family",
                "aliases": [
                    {"server": "plex-main", "username": "family-shared"},
                    {"server": "jellyfin-main", "username": "dad"},
                    {"server": "jellyfin-main", "username": "mom"},
                    {"server": "emby-main", "username": "family"},
                ],
            },
        ],
        "library_mappings": [
            {
                "canonical": "tv",
                "aliases": [
                    {"server": "plex-main", "library": "TV Shows"},
                    {"server": "plex-account", "library": "TV Shows"},
                    {"server": "jellyfin-main", "library": "Shows"},
                    {"server": "jellyfin-backup", "library": "Shows"},
                    {"server": "emby-main", "library": "Television"},
                ],
            }
        ],
        "user_sync_rules": [
            {"users": ["alice"], "from": "plex-account", "to": "jellyfin-main"}
        ],
        "library_sync_rules": [
            {
                "libraries": ["tv"],
                "from": "plex-account",
                "to": "jellyfin-main",
            }
        ],
    }


LEGACY_MULTI_SERVER_ENV = {
    "DRYRUN": "false",
    "DEBUG_LEVEL": "debug",
    "RUN_ONLY_ONCE": "true",
    "SLEEP_DURATION": "17",
    "LOG_FILE": "/tmp/jpw-legacy.log",
    "MARK_FILE": "/tmp/jpw-legacy.mark",
    "REQUEST_TIMEOUT": "23",
    "MAX_THREADS": "4",
    "GENERATE_GUIDS": "false",
    "GENERATE_LOCATIONS": "true",
    "BLACKLIST_LIBRARY": "Music",
    "WHITELIST_LIBRARY": "Movies",
    "BLACKLIST_LIBRARY_TYPE": "music",
    "WHITELIST_LIBRARY_TYPE": "movie",
    "BLACKLIST_USERS": "blocked",
    "WHITELIST_USERS": "alice",
    "PLEX_BASEURL": "http://plex-1,http://plex-2",
    "PLEX_TOKEN": "plex-token-1,plex-token-2",
    "JELLYFIN_BASEURL": "http://jellyfin-1,http://jellyfin-2",
    "JELLYFIN_TOKEN": "jellyfin-token-1,jellyfin-token-2",
    "EMBY_BASEURL": "http://emby-1,http://emby-2",
    "EMBY_TOKEN": "emby-token-1,emby-token-2",
    "USER_MAPPING": '{"alice": "alice-jellyfin"}',
    "LIBRARY_MAPPING": '{"TV Shows": "Shows"}',
    "SYNC_FROM_PLEX_TO_JELLYFIN": "true",
}

LEGACY_PLEX_ACCOUNT_ENV = {
    "PLEX_BASEURL": "http://plex-account",
    "PLEX_USERNAME": "plex-user",
    "PLEX_PASSWORD": "plex-password",
    "PLEX_SERVERNAME": "Plex Account Server",
    "JELLYFIN_BASEURL": "http://jellyfin-main",
    "JELLYFIN_TOKEN": "jellyfin-token",
}

LEGACY_EQUIVALENT_YAML = {
    "dryrun": False,
    "debug_level": "DEBUG",
    "run_only_once": True,
    "sleep_duration": 17,
    "log_file": "/tmp/jpw-legacy.log",
    "mark_file": "/tmp/jpw-legacy.mark",
    "request_timeout": 23,
    "max_threads": 4,
    "generate_guids": False,
    "generate_locations": True,
    "blacklist_libraries": ["Music"],
    "whitelist_libraries": ["Movies"],
    "blacklist_library_types": ["music"],
    "whitelist_library_types": ["movie"],
    "blacklist_users": ["blocked"],
    "whitelist_users": ["alice"],
    "plex": [
        {
            "name": "plex-1",
            "baseurl": "http://plex-1",
            "token": "plex-token-1",
            "sync_to": ["jellyfin-1", "jellyfin-2"],
        },
        {
            "name": "plex-2",
            "baseurl": "http://plex-2",
            "token": "plex-token-2",
            "sync_to": ["jellyfin-1", "jellyfin-2"],
        },
    ],
    "jellyfin": [
        {
            "name": "jellyfin-1",
            "baseurl": "http://jellyfin-1",
            "token": "jellyfin-token-1",
            "sync_to": [],
        },
        {
            "name": "jellyfin-2",
            "baseurl": "http://jellyfin-2",
            "token": "jellyfin-token-2",
            "sync_to": [],
        },
    ],
    "emby": [
        {
            "name": "emby-1",
            "baseurl": "http://emby-1",
            "token": "emby-token-1",
            "sync_to": [],
        },
        {
            "name": "emby-2",
            "baseurl": "http://emby-2",
            "token": "emby-token-2",
            "sync_to": [],
        },
    ],
    "user_mappings": [
        {
            "canonical": "alice",
            "aliases": [
                {"server": "plex-1", "username": "alice"},
                {"server": "plex-1", "username": "alice-jellyfin"},
                {"server": "plex-2", "username": "alice"},
                {"server": "plex-2", "username": "alice-jellyfin"},
                {"server": "jellyfin-1", "username": "alice"},
                {"server": "jellyfin-1", "username": "alice-jellyfin"},
                {"server": "jellyfin-2", "username": "alice"},
                {"server": "jellyfin-2", "username": "alice-jellyfin"},
                {"server": "emby-1", "username": "alice"},
                {"server": "emby-1", "username": "alice-jellyfin"},
                {"server": "emby-2", "username": "alice"},
                {"server": "emby-2", "username": "alice-jellyfin"},
            ],
        }
    ],
    "library_mappings": [
        {
            "canonical": "TV Shows",
            "aliases": [
                {"server": "plex-1", "library": "TV Shows"},
                {"server": "plex-1", "library": "Shows"},
                {"server": "plex-2", "library": "TV Shows"},
                {"server": "plex-2", "library": "Shows"},
                {"server": "jellyfin-1", "library": "TV Shows"},
                {"server": "jellyfin-1", "library": "Shows"},
                {"server": "jellyfin-2", "library": "TV Shows"},
                {"server": "jellyfin-2", "library": "Shows"},
                {"server": "emby-1", "library": "TV Shows"},
                {"server": "emby-1", "library": "Shows"},
                {"server": "emby-2", "library": "TV Shows"},
                {"server": "emby-2", "library": "Shows"},
            ],
        }
    ],
}


def _clear_configuration_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every environment spelling recognized by the settings loader."""
    for key in list(os.environ):
        key_casefold = key.casefold()
        if (
            key_casefold in _CONFIGURATION_ENV_NAMES_CASEFOLD
            or key_casefold in _LEGACY_ENV_NAMES_CASEFOLD
            or key_casefold.startswith("jpw_")
        ):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def controlled_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove configuration inputs outside the temporary test fixtures."""
    _clear_configuration_environment(monkeypatch)


def test_environment_fixture_clears_case_insensitive_field_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("BLACKLIST_LIBRARIES", "blacklist_libraries", "PLEX", "plex"):
        monkeypatch.setenv(key, "not-json")
    monkeypatch.setenv("env_file", "unrelated.env")
    monkeypatch.setenv("jPw_dRyRuN", "not-a-bool")

    _clear_configuration_environment(monkeypatch)

    assert all(
        key not in os.environ
        for key in (
            "BLACKLIST_LIBRARIES",
            "blacklist_libraries",
            "PLEX",
            "plex",
            "env_file",
            "jPw_dRyRuN",
        )
    )


def _write_yaml(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _write_env(tmp_path: Path, values: dict[str, str]) -> Path:
    path = tmp_path / "settings.env"
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    return path


def _load_yaml(tmp_path: Path, data: dict[str, Any]):
    return load_settings(
        env_file=tmp_path / "missing.env",
        yaml_file=_write_yaml(tmp_path, data),
        auto_migrate=False,
    )


def _secret_value(value: object) -> str | None:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return None


def _server_snapshot(server: Any) -> dict[str, Any]:
    return {
        "name": server.name,
        "baseurl": server.baseurl,
        "sync_to": list(server.sync_to),
        "token": _secret_value(getattr(server, "token", None)),
        "username": getattr(server, "username", None),
        "password": _secret_value(getattr(server, "password", None)),
        "servername": getattr(server, "servername", None),
        "ssl_bypass": getattr(server, "ssl_bypass", False),
    }


def _effective_settings(settings: AppSettings) -> dict[str, Any]:
    return {
        "operational": {
            "dryrun": settings.dryrun,
            "debug_level": settings.debug_level,
            "run_only_once": settings.run_only_once,
            "sleep_duration": settings.sleep_duration,
            "log_file": str(settings.log_file),
            "mark_file": str(settings.mark_file),
            "request_timeout": settings.request_timeout,
            "max_threads": settings.max_threads,
            "generate_guids": settings.generate_guids,
            "generate_locations": settings.generate_locations,
        },
        "filters": {
            "blacklist_libraries": list(settings.blacklist_libraries),
            "whitelist_libraries": list(settings.whitelist_libraries),
            "blacklist_library_types": list(settings.blacklist_library_types),
            "whitelist_library_types": list(settings.whitelist_library_types),
            "blacklist_users": list(settings.blacklist_users),
            "whitelist_users": list(settings.whitelist_users),
        },
        "plex": [_server_snapshot(server) for server in settings.plex],
        "jellyfin": [_server_snapshot(server) for server in settings.jellyfin],
        "emby": [_server_snapshot(server) for server in settings.emby],
        "user_mappings": [
            {
                "canonical": mapping.canonical,
                "aliases": [
                    {"server": alias.server, "username": alias.username}
                    for alias in mapping.aliases
                ],
            }
            for mapping in settings.user_mappings
        ],
        "library_mappings": [
            {
                "canonical": mapping.canonical,
                "aliases": [
                    {"server": alias.server, "library": alias.library}
                    for alias in mapping.aliases
                ],
            }
            for mapping in settings.library_mappings
        ],
        "user_sync_rules": [
            {"users": list(rule.users), "from": rule.from_, "to": rule.to}
            for rule in settings.user_sync_rules
        ],
        "library_sync_rules": [
            {
                "libraries": list(rule.libraries),
                "from": rule.from_,
                "to": rule.to,
            }
            for rule in settings.library_sync_rules
        ],
    }


def _policy_snapshot(settings: AppSettings) -> dict[str, Any]:
    user_cases = [
        ("alice", "plex-1", "jellyfin-1"),
        ("alice-jellyfin", "jellyfin-1", "plex-1"),
        ("blocked", "plex-1", "jellyfin-1"),
        ("blocked", "jellyfin-1", "plex-1"),
    ]
    library_cases = [
        ("TV Shows", "plex-1", "jellyfin-1"),
        ("Shows", "jellyfin-1", "plex-1"),
        ("Movies", "plex-1", "jellyfin-1"),
        ("Movies", "jellyfin-1", "plex-1"),
        ("Music", "plex-1", "jellyfin-1"),
        ("Music", "jellyfin-1", "plex-1"),
    ]

    return {
        "users": [
            {
                "case": case,
                "allowed": settings.should_sync_user(*case),
                "targets": settings.sync_targets_for_user(case[1], case[0], case[2]),
            }
            for case in user_cases
        ],
        "libraries": [
            {
                "case": case,
                "allowed": settings.should_sync_library(*case),
                "targets": settings.sync_targets_for_library(
                    case[1], case[0], case[2]
                ),
            }
            for case in library_cases
        ],
        "library_types": {
            "movie": settings.is_library_type_allowed("movie"),
            "music": settings.is_library_type_allowed("music"),
        },
    }


def test_yaml_fixture_covers_supported_configuration_shape(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    settings = _load_yaml(tmp_path, _full_yaml())

    assert [server.name for server in settings.all_servers] == [
        "plex-main",
        "plex-account",
        "jellyfin-main",
        "jellyfin-backup",
        "emby-main",
    ]
    assert settings.plex[0].token.get_secret_value() == "plex-token"
    assert settings.plex[1].username == "plex-user"
    assert settings.plex[1].password.get_secret_value() == "plex-password"
    assert settings.jellyfin[1].name == "jellyfin-backup"
    assert settings.emby[0].token.get_secret_value() == "emby-token"
    assert settings.dryrun is False
    assert settings.debug_level == "TRACE"
    assert settings.run_only_once is True
    assert settings.sleep_duration == 17
    assert settings.log_file == Path("/tmp/jpw-settings.log")
    assert settings.mark_file == Path("/tmp/jpw-settings.mark")
    assert settings.request_timeout == 23
    assert settings.max_threads == 4
    assert settings.generate_guids is False
    assert settings.generate_locations is True
    assert settings.blacklist_libraries == ["Music"]
    assert settings.whitelist_libraries == ["Movies"]
    assert settings.blacklist_library_types == ["music"]
    assert settings.whitelist_library_types == ["movie"]
    assert settings.blacklist_users == ["blocked"]
    assert settings.whitelist_users == ["alice"]
    assert settings.sync_targets_for_user(
        "plex-main", "family-shared", "jellyfin-main"
    ) == ["dad", "mom"]
    assert settings.sync_targets_for_user(
        "jellyfin-main", "dad", "plex-main"
    ) == ["family-shared"]
    assert settings.sync_targets_for_library(
        "plex-main", "TV Shows", "jellyfin-main"
    ) == ["Shows"]
    assert settings.should_sync_user("alice-plex", "plex-main", "jellyfin-main")
    assert not settings.should_sync_user("family-shared", "plex-main", "jellyfin-main")
    assert settings.should_sync_user("alice", "plex-account", "jellyfin-main")
    assert not settings.should_sync_user(
        "alice-jellyfin", "jellyfin-main", "plex-account"
    )
    assert settings.should_sync_library(
        "Movies",
        "plex-main",
        "jellyfin-main",
        library_type="movie",
        target_library_type="movie",
    )
    assert not settings.should_sync_library("TV Shows", "plex-main", "jellyfin-main")
    assert settings.is_library_type_allowed("movie")
    assert not settings.is_library_type_allowed("music")
    assert settings.user_sync_rules[0].from_ == "plex-account"
    assert settings.library_sync_rules[0].libraries == ["tv"]


def test_yaml_fixture_uses_field_defaults(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    settings = _load_yaml(tmp_path, _base_yaml())

    assert settings.dryrun is True
    assert settings.debug_level == "INFO"
    assert settings.run_only_once is False
    assert settings.sleep_duration == 3600
    assert settings.request_timeout == 300
    assert settings.max_threads == 1
    assert settings.generate_guids is True
    assert settings.generate_locations is True
    assert settings.blacklist_users == []


def test_legacy_fixture_covers_all_server_types_and_multiple_entries(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    settings = load_settings(
        env_file=_write_env(tmp_path, LEGACY_MULTI_SERVER_ENV),
        yaml_file=tmp_path / "missing.yaml",
        auto_migrate=False,
    )

    assert [server.name for server in settings.plex] == ["plex-1", "plex-2"]
    assert [server.name for server in settings.jellyfin] == [
        "jellyfin-1",
        "jellyfin-2",
    ]
    assert [server.name for server in settings.emby] == ["emby-1", "emby-2"]
    assert settings.plex[0].token is not None
    assert settings.plex[0].token.get_secret_value() == "plex-token-1"
    assert settings.jellyfin[1].token.get_secret_value() == "jellyfin-token-2"
    assert settings.emby[1].token.get_secret_value() == "emby-token-2"
    assert settings.plex[0].sync_to == ["jellyfin-1", "jellyfin-2"]
    assert settings.whitelist_users == ["alice"]
    assert settings.whitelist_libraries == ["Movies"]


def test_legacy_indexed_credentials_preserve_empty_slots() -> None:
    translated = legacy_env_to_field_dict(
        {
            "PLEX_BASEURL": "http://plex-1,http://plex-2,http://plex-3",
            "PLEX_TOKEN": "plex-token-1,,plex-token-3",
            "PLEX_USERNAME": "plex-user-1,plex-user-2,plex-user-3",
            "PLEX_PASSWORD": "plex-password-1,plex-password-2,plex-password-3",
            "PLEX_SERVERNAME": "Plex 1,Plex 2,Plex 3",
            "JELLYFIN_BASEURL": "http://jellyfin-1,http://jellyfin-2,http://jellyfin-3",
            "JELLYFIN_TOKEN": "jellyfin-token-1,,jellyfin-token-3",
        }
    )

    plex = translated["plex"]
    assert plex[0]["token"] == "plex-token-1"
    assert plex[1]["username"] == "plex-user-2"
    assert plex[1]["password"] == "plex-password-2"
    assert plex[1]["servername"] == "Plex 2"
    assert plex[2]["token"] == "plex-token-3"
    assert "token" not in plex[1]

    assert translated["jellyfin"] == [
        {
            "name": "jellyfin-1",
            "baseurl": "http://jellyfin-1",
            "token": "jellyfin-token-1",
            "sync_to": ["plex-1", "plex-2", "plex-3", "jellyfin-3"],
        },
        {
            "name": "jellyfin-3",
            "baseurl": "http://jellyfin-3",
            "token": "jellyfin-token-3",
            "sync_to": ["plex-1", "plex-2", "plex-3", "jellyfin-1"],
        },
    ]


def test_legacy_indexed_baseurls_preserve_credential_positions() -> None:
    translated = legacy_env_to_field_dict(
        {
            "PLEX_BASEURL": "http://plex-1,,http://plex-3",
            "PLEX_TOKEN": "plex-token-1,unused-token,plex-token-3",
            "JELLYFIN_BASEURL": "http://jellyfin-1,,http://jellyfin-3",
            "JELLYFIN_TOKEN": "jellyfin-token-1,unused-token,jellyfin-token-3",
        }
    )

    assert translated["plex"] == [
        {
            "name": "plex-1",
            "baseurl": "http://plex-1",
            "token": "plex-token-1",
            "sync_to": ["plex-3", "jellyfin-1", "jellyfin-3"],
        },
        {
            "name": "plex-3",
            "baseurl": "http://plex-3",
            "token": "plex-token-3",
            "sync_to": ["plex-1", "jellyfin-1", "jellyfin-3"],
        },
    ]
    assert [server["name"] for server in translated["jellyfin"]] == [
        "jellyfin-1",
        "jellyfin-3",
    ]
    assert [server["token"] for server in translated["jellyfin"]] == [
        "jellyfin-token-1",
        "jellyfin-token-3",
    ]


def test_legacy_credential_warnings_render_skipped_server() -> None:
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        legacy_env_to_field_dict(
            {
                "JELLYFIN_BASEURL": "http://jellyfin-1,http://jellyfin-2",
                "JELLYFIN_TOKEN": "jellyfin-token-1",
            }
        )
        legacy_env_to_field_dict(
            {
                "EMBY_BASEURL": "http://emby-1,http://emby-2",
                "EMBY_TOKEN": "emby-token-1,",
            }
        )
    finally:
        logger.remove(sink_id)

    assert any(
        "JELLYFIN_BASEURL has 2 entries but JELLYFIN_TOKEN only has 1. "
        "Server #2 skipped." in message
        for message in messages
    )
    assert any(
        "EMBY_TOKEN has an empty credential at position 2. Server #2 skipped."
        in message
        for message in messages
    )
    assert all("%s" not in message and "%d" not in message for message in messages)


@pytest.mark.parametrize(
    "mapping_key",
    ["USER_MAPPING", "LIBRARY_MAPPING"],
)
def test_legacy_overlapping_transitive_mapping_is_rejected_as_ambiguous(
    tmp_path: Path,
    controlled_environment: None,
    mapping_key: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        load_settings(
            env_file=_write_env(
                tmp_path,
                {
                    "PLEX_BASEURL": "http://plex",
                    "PLEX_TOKEN": "plex-token",
                    "JELLYFIN_BASEURL": "http://jellyfin",
                    "JELLYFIN_TOKEN": "jellyfin-token",
                    mapping_key: "{\"a\": \"b\", \"b\": \"c\"}",
                },
            ),
            yaml_file=tmp_path / "missing.yaml",
            auto_migrate=False,
        )

    assert "claimed by both" in str(error.value)


def test_legacy_mapping_markers_survive_yaml_migration(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    env_path = _write_env(
        tmp_path,
        {
            "PLEX_BASEURL": "http://plex",
            "PLEX_TOKEN": "plex-token",
            "JELLYFIN_BASEURL": "http://jellyfin",
            "JELLYFIN_TOKEN": "jellyfin-token",
            "USER_MAPPING": '{"plex-user":"jellyfin-user"}',
            "LIBRARY_MAPPING": '{"plex-library":"jellyfin-library"}',
        },
    )
    generated_yaml = tmp_path / "generated.yaml"

    effective = load_settings(
        env_file=env_path,
        yaml_file=generated_yaml,
        auto_migrate=True,
    )
    generated = yaml.safe_load(generated_yaml.read_text(encoding="utf-8"))

    assert effective.user_mappings[0].legacy is True
    assert effective.library_mappings[0].legacy is True
    assert generated["user_mappings"][0]["legacy"] is True
    assert generated["library_mappings"][0]["legacy"] is True

    yaml_only = load_settings(
        env_file=tmp_path / "missing.env",
        yaml_file=generated_yaml,
        auto_migrate=False,
    )

    assert yaml_only.user_mappings[0].legacy is True
    assert yaml_only.library_mappings[0].legacy is True


def test_legacy_and_yaml_fixtures_have_equivalent_effective_behavior(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    legacy = load_settings(
        env_file=_write_env(tmp_path, LEGACY_MULTI_SERVER_ENV),
        yaml_file=tmp_path / "missing.yaml",
        auto_migrate=False,
    )
    yaml_settings = _load_yaml(tmp_path, LEGACY_EQUIVALENT_YAML)

    assert _effective_settings(legacy) == _effective_settings(yaml_settings)
    assert _policy_snapshot(legacy) == _policy_snapshot(yaml_settings)


def test_migration_round_trip_preserves_effective_settings_and_policy(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    env_path = _write_env(tmp_path, LEGACY_MULTI_SERVER_ENV)
    missing_yaml = tmp_path / "missing.yaml"
    generated_yaml = tmp_path / "generated.yaml"

    legacy = load_settings(
        env_file=env_path,
        yaml_file=missing_yaml,
        auto_migrate=False,
    )
    load_settings(
        env_file=env_path,
        yaml_file=generated_yaml,
        auto_migrate=True,
    )
    yaml_only = load_settings(
        env_file=tmp_path / "missing.env",
        yaml_file=generated_yaml,
        auto_migrate=False,
    )

    assert _effective_settings(legacy) == _effective_settings(yaml_only)
    assert _policy_snapshot(legacy) == _policy_snapshot(yaml_only)
    assert generated_yaml.stat().st_mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR


def test_migration_preserves_mixed_prefixed_server_token_override(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    env_path = _write_env(
        tmp_path,
        {
            "PLEX_BASEURL": "http://plex",
            "PLEX_TOKEN": "legacy-token",
            "JELLYFIN_BASEURL": "http://jellyfin",
            "JELLYFIN_TOKEN": "jellyfin-token",
            "JPW_SERVER_TOKENS": '{"plex-main":"replacement-token"}',
        },
    )
    generated_yaml = tmp_path / "generated.yaml"

    effective = load_settings(
        env_file=env_path,
        yaml_file=tmp_path / "missing.yaml",
        auto_migrate=False,
    )
    assert effective.plex[0].token is not None
    assert effective.plex[0].token.get_secret_value() == "replacement-token"

    load_settings(
        env_file=env_path,
        yaml_file=generated_yaml,
        auto_migrate=True,
    )
    generated = yaml.safe_load(generated_yaml.read_text(encoding="utf-8"))
    assert generated["plex"][0]["token"] == "replacement-token"
    assert "legacy-token" not in generated_yaml.read_text(encoding="utf-8")

    yaml_only = load_settings(
        env_file=tmp_path / "missing.env",
        yaml_file=generated_yaml,
        auto_migrate=False,
    )
    assert _effective_settings(effective) == _effective_settings(yaml_only)


def test_migration_preserves_mixed_prefixed_settings(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    env_path = _write_env(
        tmp_path,
        {
            "DRYRUN": "false",
            "PLEX_BASEURL": "http://legacy-plex",
            "PLEX_TOKEN": "legacy-plex-token",
            "JELLYFIN_BASEURL": "http://legacy-jellyfin",
            "JELLYFIN_TOKEN": "legacy-jellyfin-token",
            "JPW_DRYRUN": "true",
            "JPW_SLEEP_DURATION": "42",
            "JPW_BLACKLIST_LIBRARIES": "'[\"Movies\"]'",
            "JPW_WHITELIST_USERS": "'[\"alice\"]'",
            "JPW_PLEX": (
                "'[{\"name\":\"plex-main\","
                "\"baseurl\":\"http://prefixed-plex\","
                "\"token\":\"prefixed-plex-token\","
                "\"sync_to\":[\"jellyfin-main\"]}]'"
            ),
        },
    )
    generated_yaml = tmp_path / "generated.yaml"

    effective = load_settings(
        env_file=env_path,
        yaml_file=tmp_path / "missing.yaml",
        auto_migrate=False,
    )
    assert effective.dryrun is True
    assert effective.sleep_duration == 42
    assert effective.blacklist_libraries == ["Movies"]
    assert effective.whitelist_users == ["alice"]
    assert effective.plex[0].baseurl == "http://prefixed-plex"
    assert effective.plex[0].token is not None
    assert effective.plex[0].token.get_secret_value() == "prefixed-plex-token"

    load_settings(
        env_file=env_path,
        yaml_file=generated_yaml,
        auto_migrate=True,
    )
    generated = yaml.safe_load(generated_yaml.read_text(encoding="utf-8"))
    assert generated["dryrun"] is True
    assert generated["sleep_duration"] == 42
    assert generated["blacklist_libraries"] == ["Movies"]
    assert generated["whitelist_users"] == ["alice"]
    assert generated["plex"][0]["baseurl"] == "http://prefixed-plex"
    assert generated["plex"][0]["token"] == "prefixed-plex-token"

    yaml_only = load_settings(
        env_file=tmp_path / "missing.env",
        yaml_file=generated_yaml,
        auto_migrate=False,
    )
    assert _effective_settings(effective) == _effective_settings(yaml_only)


def test_migration_serializes_external_rule_aliases() -> None:
    settings = settings_override(
        user_sync_rules=[
            {"users": ["alice"], "from": "plex-main", "to": "jellyfin-main"}
        ],
        library_sync_rules=[
            {
                "libraries": ["Movies"],
                "from": "plex-main",
                "to": "jellyfin-main",
            }
        ],
    )

    dumped = _dump_for_yaml(settings)

    assert dumped["user_sync_rules"] == [
        {"users": ["alice"], "from": "plex-main", "to": "jellyfin-main"}
    ]
    assert dumped["library_sync_rules"] == [
        {
            "libraries": ["Movies"],
            "from": "plex-main",
            "to": "jellyfin-main",
        }
    ]


def test_migration_keeps_existing_destination(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    env_path = _write_env(tmp_path, LEGACY_MULTI_SERVER_ENV)
    destination = tmp_path / "generated.yaml"
    destination.write_text("existing", encoding="utf-8")

    assert _migrate_env_to_yaml(env_path, destination) is False
    assert destination.read_text(encoding="utf-8") == "existing"


def test_migration_diagnostics_redact_legacy_token(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    token = "migration-synthetic-secret"
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        result = _migrate_env_to_yaml(
            _write_env(tmp_path, {"PLEX_TOKEN": token}),
            tmp_path / "generated.yaml",
        )
    finally:
        logger.remove(sink_id)

    assert result is False
    assert messages
    assert all(token not in message for message in messages)


def test_legacy_fixture_covers_plex_username_password_auth(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    settings = load_settings(
        env_file=_write_env(tmp_path, LEGACY_PLEX_ACCOUNT_ENV),
        yaml_file=tmp_path / "missing.yaml",
        auto_migrate=False,
    )

    assert settings.plex[0].token is None
    assert settings.plex[0].username == "plex-user"
    assert settings.plex[0].password is not None
    assert settings.plex[0].password.get_secret_value() == "plex-password"
    assert settings.plex[0].servername == "Plex Account Server"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("true", True),
        ("yes", True),
        ("on", True),
        ("t", True),
        ("y", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
        ("f", False),
        ("n", False),
        ("  Y  ", True),
        ("  n  ", False),
    ],
)
def test_r08_legacy_boolean_aliases_are_preserved(
    tmp_path: Path,
    controlled_environment: None,
    raw: str,
    expected: bool,
) -> None:
    settings = load_settings(
        env_file=_write_env(tmp_path, {"DRYRUN": raw}),
        yaml_file=_write_yaml(tmp_path, _base_yaml()),
        auto_migrate=False,
    )

    assert settings.dryrun is expected


@pytest.mark.parametrize("raw", [None, "", "  "])
def test_r08_empty_legacy_boolean_is_unset(raw: str | None) -> None:
    translated = legacy_env_to_field_dict({"DRYRUN": raw})

    assert "dryrun" not in translated


@pytest.mark.parametrize("raw", ["tru", "maybe", "2", "not-a-bool"])
def test_r08_invalid_legacy_boolean_fails_before_loading_settings(
    tmp_path: Path,
    controlled_environment: None,
    raw: str,
) -> None:
    with pytest.raises(ValueError, match="invalid boolean value for DRYRUN") as error:
        load_settings(
            env_file=_write_env(tmp_path, {"DRYRUN": raw}),
            yaml_file=_write_yaml(tmp_path, _base_yaml()),
            auto_migrate=False,
        )

    assert raw not in str(error.value)


def test_c01_legacy_csv_isolated_from_new_environment_parsing(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WHITELIST_USERS", "alice,bob")

    settings = _load_yaml(tmp_path, _base_yaml())

    assert settings.whitelist_users == ["alice", "bob"]


def test_c01_prefixed_process_accepts_json_lists(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JPW_WHITELIST_USERS", '["alice", "bob"]')

    settings = _load_yaml(tmp_path, _base_yaml())

    assert settings.whitelist_users == ["alice", "bob"]


def test_c02_process_legacy_values_override_selected_dotenv(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = _write_env(
        tmp_path,
        {"PLEX_BASEURL": "http://legacy-plex", "PLEX_TOKEN": "file-token"},
    )
    monkeypatch.setenv("PLEX_TOKEN", "process-token")

    settings = load_settings(
        env_file=env_path,
        yaml_file=_write_yaml(tmp_path, _base_yaml()),
        auto_migrate=False,
    )

    assert settings.plex[0].token is not None
    assert settings.plex[0].token.get_secret_value() == "process-token"


def test_c02_legacy_translation_uses_only_supplied_values(
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLEX_TOKEN", "process-token")

    translated = legacy_env_to_field_dict(
        {"PLEX_BASEURL": "http://legacy-plex", "PLEX_TOKEN": "file-token"}
    )

    assert translated["plex"][0]["token"] == "file-token"


def test_c02_process_presence_wins_even_when_empty_or_valueless() -> None:
    assert resolve_legacy_env(
        {"PLEX_TOKEN": "file-token"}, {"PLEX_TOKEN": ""}
    ) == {"PLEX_TOKEN": ""}
    assert resolve_legacy_env(
        {"PLEX_TOKEN": "file-token"}, {"PLEX_TOKEN": None}
    ) == {"PLEX_TOKEN": None}
    assert resolve_legacy_env({"PLEX_TOKEN": None}, {}) == {"PLEX_TOKEN": None}


def test_c02_legacy_file_values_override_yaml_values(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    settings = load_settings(
        env_file=_write_env(tmp_path, {"WHITELIST_USERS": "legacy-file"}),
        yaml_file=_write_yaml(
            tmp_path,
            {**_base_yaml(), "whitelist_users": ["yaml-value"]},
        ),
        auto_migrate=False,
    )

    assert settings.whitelist_users == ["legacy-file"]


def test_c02_empty_legacy_process_value_does_not_fall_back_to_file(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WHITELIST_USERS", "")

    settings = load_settings(
        env_file=_write_env(tmp_path, {"WHITELIST_USERS": "legacy-file"}),
        yaml_file=_write_yaml(
            tmp_path,
            {**_base_yaml(), "whitelist_users": ["yaml-value"]},
        ),
        auto_migrate=False,
    )

    assert settings.whitelist_users == ["yaml-value"]


def test_c02_process_aliases_beat_file_aliases_as_a_group(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOGFILE", "process.log")
    monkeypatch.setenv("MARKFILE", "process.mark")
    monkeypatch.setenv("DEBUG", "true")

    settings = load_settings(
        env_file=_write_env(
            tmp_path,
            {
                "LOG_FILE": "file.log",
                "MARK_FILE": "file.mark",
                "DEBUG_LEVEL": "TRACE",
            },
        ),
        yaml_file=_write_yaml(tmp_path, _base_yaml()),
        auto_migrate=False,
    )

    assert settings.log_file == Path("process.log")
    assert settings.mark_file == Path("process.mark")
    assert settings.debug_level == "DEBUG"


@pytest.mark.parametrize(
    ("process_key", "file_key", "yaml_field", "yaml_value"),
    [
        ("LOG_FILE", "LOGFILE", "log_file", "yaml.log"),
        ("MARK_FILE", "MARKFILE", "mark_file", "yaml.mark"),
        ("DEBUG_LEVEL", "DEBUG", "debug_level", "TRACE"),
    ],
)
def test_c02_empty_process_alias_does_not_fall_back_to_file_alias(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    process_key: str,
    file_key: str,
    yaml_field: str,
    yaml_value: str,
) -> None:
    monkeypatch.setenv(process_key, "")

    settings = load_settings(
        env_file=_write_env(tmp_path, {file_key: "file-value"}),
        yaml_file=_write_yaml(
            tmp_path,
            {**_base_yaml(), yaml_field: yaml_value},
        ),
        auto_migrate=False,
    )

    assert getattr(settings, yaml_field) == (
        Path(yaml_value) if yaml_field != "debug_level" else yaml_value
    )


def test_c03_selected_dotenv_loads_prefixed_new_fields(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    env_path = _write_env(
        tmp_path,
        {"JPW_BLACKLIST_LIBRARIES": "'[\"Movies\"]'"},
    )

    settings = load_settings(
        env_file=env_path,
        yaml_file=_write_yaml(tmp_path, _base_yaml()),
        auto_migrate=False,
    )

    assert settings.blacklist_libraries == ["Movies"]


def test_c03_selected_dotenv_partitions_new_and_legacy_values(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    env_path = _write_env(
        tmp_path,
        {
            "JPW_BLACKLIST_LIBRARIES": "'[\"Movies\"]'",
            "WHITELIST_USERS": "alice,bob",
        },
    )

    settings = load_settings(
        env_file=env_path,
        yaml_file=_write_yaml(tmp_path, _base_yaml()),
        auto_migrate=False,
    )

    assert settings.blacklist_libraries == ["Movies"]
    assert settings.whitelist_users == ["alice", "bob"]


def test_c03_empty_prefixed_list_overrides_yaml(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    config = _base_yaml()
    config["blacklist_libraries"] = ["YAML Movies"]
    env_path = _write_env(
        tmp_path,
        {"JPW_BLACKLIST_LIBRARIES": "'[]'"},
    )

    settings = load_settings(
        env_file=env_path,
        yaml_file=_write_yaml(tmp_path, config),
        auto_migrate=False,
    )

    assert settings.blacklist_libraries == []


def test_c03_empty_prefixed_process_value_is_unset(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JPW_BLACKLIST_LIBRARIES", "")

    settings = _load_yaml(
        tmp_path,
        {**_base_yaml(), "blacklist_libraries": ["YAML Movies"]},
    )

    assert settings.blacklist_libraries == ["YAML Movies"]


def test_c03_empty_prefixed_dotenv_value_is_unset(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    env_path = _write_env(tmp_path, {"JPW_BLACKLIST_LIBRARIES": ""})

    settings = load_settings(
        env_file=env_path,
        yaml_file=_write_yaml(
            tmp_path,
            {**_base_yaml(), "blacklist_libraries": ["YAML Movies"]},
        ),
        auto_migrate=False,
    )

    assert settings.blacklist_libraries == ["YAML Movies"]


def test_c03_valueless_prefixed_dotenv_value_is_unset(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    env_path = tmp_path / "settings.env"
    env_path.write_text("JPW_BLACKLIST_LIBRARIES\n", encoding="utf-8")

    settings = load_settings(
        env_file=env_path,
        yaml_file=_write_yaml(
            tmp_path,
            {**_base_yaml(), "blacklist_libraries": ["YAML Movies"]},
        ),
        auto_migrate=False,
    )

    assert settings.blacklist_libraries == ["YAML Movies"]


def test_c03_constructor_values_override_prefixed_process_values(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JPW_BLACKLIST_LIBRARIES", '["process"]')
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "JPW_UNKNOWN_SETTING=local-only\n",
        encoding="utf-8",
    )

    constructor_options: dict[str, Any] = {
        **_base_yaml(),
        "blacklist_libraries": ["constructor"],
        "_env_file": None,
    }
    settings = _SettingsLoader(**constructor_options)

    assert settings.blacklist_libraries == ["constructor"]


def test_c03_constructor_source_options_are_preserved(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = _write_env(tmp_path, {"OTHER_DRYRUN": "false"})
    monkeypatch.setenv("JPW_DRYRUN", "true")

    constructor_options: dict[str, Any] = {
        **_base_yaml(),
        "_env_file": env_path,
        "_env_prefix": "OTHER_",
    }
    settings = _SettingsLoader(**constructor_options)

    assert settings.dryrun is False


def test_c03_constructor_encoding_is_preserved_for_legacy_source(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    env_path = tmp_path / "settings-latin1.env"
    env_path.write_text(
        "JPW_WHITELIST_USERS='[\"café\"]'\n",
        encoding="latin-1",
    )
    constructor_options: dict[str, Any] = {
        **_base_yaml(),
        "_env_file": env_path,
        "_env_file_encoding": "latin-1",
    }

    settings = _SettingsLoader(**constructor_options)

    assert settings.whitelist_users == ["café"]


def test_c03_prefixed_process_wins_over_prefixed_dotenv(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = _write_env(tmp_path, {"JPW_DRYRUN": "false"})
    monkeypatch.setenv("JPW_DRYRUN", "true")

    settings = load_settings(
        env_file=env_path,
        yaml_file=_write_yaml(tmp_path, _base_yaml()),
        auto_migrate=False,
    )

    assert settings.dryrun is True


def test_c03_prefixed_dotenv_wins_over_legacy_process(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = _write_env(
        tmp_path,
        {"JPW_BLACKLIST_LIBRARIES": "'[\"dotenv\"]'"},
    )
    monkeypatch.setenv("BLACKLIST_LIBRARY", "legacy-process")

    settings = load_settings(
        env_file=env_path,
        yaml_file=_write_yaml(tmp_path, _base_yaml()),
        auto_migrate=False,
    )

    assert settings.blacklist_libraries == ["dotenv"]


def test_c03_malformed_prefixed_dotenv_value_reports_field_without_value(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    env_path = _write_env(
        tmp_path,
        {"JPW_BLACKLIST_LIBRARIES": "not-json"},
    )

    with pytest.raises(SettingsError) as error:
        load_settings(
            env_file=env_path,
            yaml_file=_write_yaml(tmp_path, _base_yaml()),
            auto_migrate=False,
        )

    assert "blacklist_libraries" in str(error.value)
    assert "not-json" not in str(error.value)


def test_c03_unknown_prefixed_dotenv_field_is_rejected_without_value(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    env_path = _write_env(
        tmp_path,
        {"JPW_UNKNOWN_SETTING": "synthetic-secret"},
    )

    with pytest.raises(ValidationError) as error:
        load_settings(
            env_file=env_path,
            yaml_file=_write_yaml(tmp_path, _base_yaml()),
            auto_migrate=False,
        )

    assert "unknown_setting" in str(error.value)
    assert "synthetic-secret" not in str(error.value)


def test_c03_unknown_prefixed_process_field_is_rejected_without_value(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("jPw_UNKNOWN_SETTING", "synthetic-secret")

    with pytest.raises(SettingsError) as error:
        load_settings(
            env_file=tmp_path / "missing.env",
            yaml_file=_write_yaml(tmp_path, _base_yaml()),
            auto_migrate=False,
        )

    assert "unknown_setting" in str(error.value).lower()
    assert "synthetic-secret" not in str(error.value)


def test_c03_unprefixed_new_dotenv_field_emits_migration_warning(
    tmp_path: Path,
    controlled_environment: None,
) -> None:
    env_path = _write_env(
        tmp_path,
        {"BLACKLIST_LIBRARIES": "'[\"Movies\"]'"},
    )
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        settings = load_settings(
            env_file=env_path,
            yaml_file=_write_yaml(tmp_path, _base_yaml()),
            auto_migrate=False,
        )
    finally:
        logger.remove(sink_id)

    assert settings.blacklist_libraries == []
    assert any(
        "unprefixed new-style setting" in message
        and "JPW_BLACKLIST_LIBRARIES" in message
        for message in messages
    )


def test_c04_single_legacy_token_can_override_one_yaml_server(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLEX_TOKEN", "process-only-token")

    settings = load_settings(
        env_file=tmp_path / "missing.env",
        yaml_file=_write_yaml(tmp_path, _base_yaml()),
        auto_migrate=False,
    )

    assert settings.plex[0].token is not None
    assert settings.plex[0].token.get_secret_value() == "process-only-token"


def test_c04_named_server_token_override_preserves_server_metadata(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _load_yaml(tmp_path, _full_yaml())
    monkeypatch.setenv(
        "JPW_SERVER_TOKENS",
        '{"plex-account":"replacement-plex-token",'
        '"jellyfin-main":"replacement-jellyfin-token"}',
    )

    settings = _load_yaml(tmp_path, _full_yaml())

    plex = next(server for server in settings.plex if server.name == "plex-account")
    jellyfin = next(
        server for server in settings.jellyfin if server.name == "jellyfin-main"
    )

    assert plex.baseurl == "http://plex-account"
    assert plex.sync_to == []
    assert plex.token is not None
    assert plex.token.get_secret_value() == "replacement-plex-token"
    assert plex.username is None
    assert plex.password is None
    assert plex.servername is None
    assert jellyfin.baseurl == "http://jellyfin-main"
    assert jellyfin.sync_to == ["plex-main"]
    assert jellyfin.token.get_secret_value() == "replacement-jellyfin-token"
    assert settings.user_mappings == baseline.user_mappings
    assert settings.library_mappings == baseline.library_mappings
    assert settings.user_sync_rules == baseline.user_sync_rules
    assert settings.library_sync_rules == baseline.library_sync_rules


def test_c04_process_named_server_token_map_replaces_dotenv_map(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JPW_SERVER_TOKENS", '{"jellyfin-main":"process-token"}')

    settings = load_settings(
        env_file=_write_env(
            tmp_path,
            {"JPW_SERVER_TOKENS": '{"plex-main":"dotenv-token"}'},
        ),
        yaml_file=_write_yaml(tmp_path, _base_yaml()),
        auto_migrate=False,
    )

    assert settings.plex[0].token is not None
    assert settings.plex[0].token.get_secret_value() == "yaml-token"
    assert settings.jellyfin[0].token.get_secret_value() == "process-token"


@pytest.mark.parametrize(
    "override_value",
    [
        "not-json",
        '{"plex-main":""}',
    ],
)
def test_c04_malformed_named_token_override_is_redacted(
    tmp_path: Path,
    controlled_environment: None,
    override_value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JPW_SERVER_TOKENS", override_value)

    with pytest.raises(SettingsError) as error:
        _load_yaml(tmp_path, _base_yaml())

    assert "server_tokens" in str(error.value)
    assert override_value not in str(error.value)


def test_c04_unknown_named_token_override_is_redacted(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JPW_SERVER_TOKENS", '{"missing":"synthetic-secret"}')

    with pytest.raises(ValidationError) as error:
        _load_yaml(tmp_path, _base_yaml())

    assert "unknown server name" in str(error.value)
    assert "synthetic-secret" not in str(error.value)


def test_c04_legacy_token_only_requires_one_plex_target(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLEX_TOKEN", "synthetic-secret")

    with pytest.raises(ValidationError) as error:
        load_settings(
            env_file=tmp_path / "missing.env",
            yaml_file=_write_yaml(
                tmp_path,
                {
                    "jellyfin": [
                        {
                            "name": "jellyfin-main",
                            "baseurl": "http://jellyfin",
                            "token": "jellyfin-token",
                            "sync_to": ["emby-main"],
                        }
                    ],
                    "emby": [
                        {
                            "name": "emby-main",
                            "baseurl": "http://emby",
                            "token": "emby-token",
                            "sync_to": ["jellyfin-main"],
                        }
                    ],
                },
            ),
            auto_migrate=False,
        )

    assert "exactly one" in str(error.value)
    assert "synthetic-secret" not in str(error.value)


def test_c04_legacy_token_only_rejects_multiple_plex_targets(
    tmp_path: Path,
    controlled_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLEX_TOKEN", "synthetic-secret")

    with pytest.raises(ValidationError) as error:
        _load_yaml(tmp_path, _full_yaml())

    assert "exactly one" in str(error.value)
    assert "synthetic-secret" not in str(error.value)


def test_c05_wildcard_rule_applies_to_unmapped_users(
    controlled_environment: None,
) -> None:
    settings = settings_override(
        plex=[
            {
                "name": "plex-main",
                "baseurl": "http://plex",
                "token": "x",
                "sync_to": [],
            }
        ],
        jellyfin=[
            {
                "name": "jellyfin-main",
                "baseurl": "http://jellyfin",
                "token": "x",
                "sync_to": [],
            }
        ],
        user_sync_rules=[
            {"users": ["*"], "from": "plex-main", "to": "jellyfin-main"}
        ],
        library_sync_rules=[
            {"libraries": ["*"], "from": "plex-main", "to": "jellyfin-main"}
        ],
    )

    assert settings.should_sync_server("plex-main", "jellyfin-main") is True
    assert settings.should_sync_server("jellyfin-main", "plex-main") is False
    assert settings.should_sync_user("alice", "plex-main", "jellyfin-main") is True
    assert settings.should_sync_user("alice", "jellyfin-main", "plex-main") is False
    assert (
        settings.should_sync_library("Movies", "plex-main", "jellyfin-main") is True
    )
    assert (
        settings.should_sync_library("Movies", "jellyfin-main", "plex-main") is False
    )


def test_c05_wildcards_skip_partial_and_unrelated_mappings(
    controlled_environment: None,
) -> None:
    """Wildcards do not require every mapped identity on both servers."""
    settings = settings_override(
        plex=[
            {
                "name": "plex-main",
                "baseurl": "http://plex",
                "token": "x",
                "sync_to": [],
            }
        ],
        jellyfin=[
            {
                "name": "jellyfin-main",
                "baseurl": "http://jellyfin",
                "token": "x",
                "sync_to": [],
            }
        ],
        emby=[
            {
                "name": "emby-main",
                "baseurl": "http://emby",
                "token": "x",
                "sync_to": [],
            }
        ],
        user_mappings=[
            {
                "canonical": "partial",
                "aliases": [
                    {"server": "plex-main", "username": "partial"},
                ],
            },
            {
                "canonical": "unrelated",
                "aliases": [
                    {"server": "emby-main", "username": "elsewhere"},
                ],
            },
        ],
        library_mappings=[
            {
                "canonical": "partial-library",
                "aliases": [
                    {"server": "plex-main", "library": "Partial"},
                ],
            },
            {
                "canonical": "unrelated-library",
                "aliases": [
                    {"server": "emby-main", "library": "Elsewhere"},
                ],
            },
        ],
        user_sync_rules=[
            {"users": ["*"], "from": "plex-main", "to": "jellyfin-main"}
        ],
        library_sync_rules=[
            {
                "libraries": ["*"],
                "from": "plex-main",
                "to": "jellyfin-main",
            }
        ],
    )

    assert settings.should_sync_user("partial", "plex-main", "jellyfin-main")
    assert (
        settings.sync_targets_for_user("plex-main", "partial", "jellyfin-main")
        == []
    )
    assert settings.should_sync_user("implicit", "plex-main", "jellyfin-main")
    assert settings.sync_targets_for_user(
        "plex-main", "implicit", "jellyfin-main"
    ) == ["implicit"]

    assert settings.should_sync_library(
        "Partial", "plex-main", "jellyfin-main"
    )
    assert settings.sync_targets_for_library(
        "plex-main", "Partial", "jellyfin-main"
    ) == []
    assert settings.should_sync_library(
        "Implicit", "plex-main", "jellyfin-main"
    )
    assert settings.sync_targets_for_library(
        "plex-main", "Implicit", "jellyfin-main"
    ) == ["Implicit"]


def test_r06_explicit_target_ownership_blocks_implicit_fallback(
    controlled_environment: None,
) -> None:
    settings = settings_override(
        user_mappings=[
            {
                "canonical": "owner",
                "aliases": [
                    {"server": "plex-main", "username": "owner"},
                    {"server": "jellyfin-main", "username": "shared"},
                ],
            }
        ],
        library_mappings=[
            {
                "canonical": "owned-library",
                "aliases": [
                    {"server": "plex-main", "library": "Owned"},
                    {"server": "jellyfin-main", "library": "Shared"},
                ],
            }
        ],
    )

    assert (
        settings.sync_targets_for_user(
            "plex-main", "shared", "jellyfin-main"
        )
        == []
    )
    assert (
        settings.sync_targets_for_library(
            "plex-main", "Shared", "jellyfin-main"
        )
        == []
    )
    assert settings.sync_targets_for_user(
        "jellyfin-main", "shared", "plex-main"
    ) == ["owner"]
    assert settings.sync_targets_for_library(
        "jellyfin-main", "Shared", "plex-main"
    ) == ["Owned"]

    # An unowned name still uses the ordinary same-name fallback.
    assert settings.sync_targets_for_user(
        "plex-main", "unmapped", "jellyfin-main"
    ) == ["unmapped"]
    assert settings.sync_targets_for_library(
        "plex-main", "Unmapped", "jellyfin-main"
    ) == ["Unmapped"]


@pytest.mark.parametrize(
    ("field", "rule"),
    [
        ("user_sync_rules", {"users": ["*", "alice"]}),
        ("library_sync_rules", {"libraries": ["*", "Movies"]}),
    ],
)
def test_c05_wildcard_rule_must_not_mix_literal_entries(
    controlled_environment: None,
    field: str,
    rule: dict[str, list[str]],
) -> None:
    with pytest.raises(ValidationError, match="must be the only entry"):
        settings_override(
            **{
                field: [
                    {
                        **rule,
                        "from": "plex-main",
                        "to": "jellyfin-main",
                    }
                ]
            }
        )


def test_phase3_casefolds_identity_validation_indexes_and_lookups(
    controlled_environment: None,
) -> None:
    settings = settings_override(
        plex=[
            {
                "name": "plex-main",
                "baseurl": "http://plex",
                "token": "x",
                "sync_to": [],
            }
        ],
        jellyfin=[
            {
                "name": "jellyfin-main",
                "baseurl": "http://jellyfin",
                "token": "x",
                "sync_to": [],
            }
        ],
        user_mappings=[
            {
                "canonical": "Person",
                "aliases": [
                    {"server": "plex-main", "username": "Straße"},
                    {"server": "jellyfin-main", "username": "target-user"},
                ],
            }
        ],
        library_mappings=[
            {
                "canonical": "Library",
                "aliases": [
                    {"server": "plex-main", "library": "Straße"},
                    {"server": "jellyfin-main", "library": "target-library"},
                ],
            }
        ],
        user_sync_rules=[
            {"users": ["PERSON"], "from": "plex-main", "to": "jellyfin-main"}
        ],
        library_sync_rules=[
            {
                "libraries": ["LIBRARY"],
                "from": "plex-main",
                "to": "jellyfin-main",
            }
        ],
    )

    assert settings.lookup_user("plex-main", "STRASSE") == "person"
    assert settings.lookup_library("plex-main", "STRASSE") == "library"
    assert settings.sync_targets_for_user(
        "plex-main", "STRASSE", "jellyfin-main"
    ) == ["target-user"]
    assert settings.sync_targets_for_library(
        "plex-main", "STRASSE", "jellyfin-main"
    ) == ["target-library"]
    assert settings.should_sync_user("STRASSE", "plex-main", "jellyfin-main") is True
    assert (
        settings.should_sync_library("STRASSE", "plex-main", "jellyfin-main") is True
    )
    assert settings.should_sync_user("STRASSE", "jellyfin-main", "plex-main") is False
    assert (
        settings.should_sync_library("STRASSE", "jellyfin-main", "plex-main") is False
    )


def test_c06_user_filters_keep_same_name_identities_separate(
    controlled_environment: None,
) -> None:
    settings = settings_override(
        user_mappings=[
            {
                "canonical": "first",
                "aliases": [
                    {"server": "plex-main", "username": "shared"},
                    {"server": "jellyfin-main", "username": "first-jf"},
                ],
            },
            {
                "canonical": "second",
                "aliases": [
                    {"server": "plex-main", "username": "second-plex"},
                    {"server": "jellyfin-main", "username": "shared"},
                ],
            },
        ],
        whitelist_users=["first"],
    )

    assert settings.should_sync_user("shared", "plex-main", "jellyfin-main") is True
    assert (
        settings.should_sync_user("shared", "jellyfin-main", "plex-main") is False
    )
    assert settings.is_user_allowed("shared", "plex-main") is True
    assert settings.is_user_allowed("shared", "jellyfin-main") is False


def test_c07_library_whitelist_takes_precedence_over_blacklist(
    controlled_environment: None,
) -> None:
    settings = settings_override(
        blacklist_libraries=["Movies"],
        whitelist_libraries=["Movies"],
    )

    assert settings.should_sync_library("Movies", "plex-main", "jellyfin-main") is True
