from __future__ import annotations

import json
import os
import re
from io import StringIO
from pathlib import Path

import pytest
import yaml
from dotenv import dotenv_values

from src.legacy_settings import LEGACY_ENV_VARS, legacy_env_to_field_dict
from src.settings import AppSettings, load_settings


ROOT = Path(__file__).resolve().parents[1]


def _readme_dotenv_blocks() -> list[dict[str, str | None]]:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    return [
        dict(dotenv_values(stream=StringIO(block)))
        for block in re.findall(r"```dotenv\n(.*?)```", readme, re.DOTALL)
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


def test_sample_configuration_validates_without_server_connections() -> None:
    sample = yaml.safe_load(
        (ROOT / "sample.config.yaml").read_text(encoding="utf-8")
    )

    settings = AppSettings.model_validate(sample)

    assert [server.name for server in settings.all_servers] == [
        "plex-main",
        "plex-readonly",
        "jellyfin-main",
        "emby-main",
    ]
    # The sample's Alice and Movies rules add permissions independently.
    assert settings.should_sync_scope(
        "alice",
        "TV Shows",
        "plex-readonly",
        "jellyfin-main",
        library_type="show",
        target_library_type="tvshows",
    )
    assert settings.should_sync_scope(
        "family_shared",
        "Movies",
        "plex-readonly",
        "jellyfin-main",
        library_type="movie",
        target_library_type="movies",
    )
    assert not settings.should_sync_scope(
        "family_shared",
        "TV Shows",
        "plex-readonly",
        "jellyfin-main",
        library_type="show",
        target_library_type="tvshows",
    )


def test_readme_legacy_configuration_snippet_is_supported() -> None:
    blocks = _readme_dotenv_blocks()
    legacy_blocks = [block for block in blocks if "PLEX_BASEURL" in block]
    assert len(legacy_blocks) == 1
    legacy = legacy_blocks[0]

    assert set(legacy) <= LEGACY_ENV_VARS

    settings = AppSettings.model_validate(legacy_env_to_field_dict(legacy))

    assert [server.name for server in settings.all_servers] == [
        "plex-main",
        "jellyfin-main",
    ]
    assert settings.plex[0].sync_to == ["jellyfin-main"]


def test_readme_prefixed_configuration_snippet_loads_against_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocks = _readme_dotenv_blocks()
    prefixed_blocks = [block for block in blocks if "JPW_DRYRUN" in block]
    assert len(prefixed_blocks) == 1
    prefixed = prefixed_blocks[0]
    _clear_settings_environment(monkeypatch)

    assert prefixed
    assert all(key.startswith("JPW_") for key in prefixed)
    for value in prefixed.values():
        assert value is not None
        json.loads(value)

    env_path = tmp_path / "readme.env"
    env_path.write_text(
        "\n".join(f"{key}={value}" for key, value in prefixed.items()) + "\n",
        encoding="utf-8",
    )
    settings = load_settings(
        env_file=env_path,
        yaml_file=ROOT / "sample.config.yaml",
        auto_migrate=False,
    )

    assert settings.dryrun is False
    assert settings.whitelist_users == ["alice", "bob"]
    token = settings.plex[0].token
    assert token is not None
    assert token.get_secret_value() == "replacement-token"
