"""Unit tests for the 飞牛影视 (TrimMedia) adapter and its configuration."""

from __future__ import annotations

from loguru import logger

import hashlib
import json
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pytest
import yaml
from dotenv import dotenv_values

from conftest import settings_override
from src.legacy_settings import legacy_env_to_field_dict, resolve_legacy_env
from src.settings import (
    TRIMMEDIA_DEFAULT_API_KEY,
    AppSettings,
    TrimMediaSettings,
)
from src.trimmedia import (
    TRIMMEDIA_SIGNING_SECRET,
    TrimMedia,
    TrimMediaApiError,
    TrimMediaClient,
    _series_folder_from_path,
)
from src.watched import LibraryData, MediaIdentifiers, MediaItem, WatchedStatus

ROOT = Path(__file__).resolve().parents[1]

MOVIE_LIBRARY = "lib-movies"
TV_LIBRARY = "lib-tv"
ADMIN_GUID = "user-admin"


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, payload: dict | None, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Records requests and replays canned responses keyed by path."""

    def __init__(self, responses: dict[str, dict]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append({"url": url, "method": "GET", **kwargs})
        return FakeResponse(self.responses.get("GET " + url, {"code": 0, "data": None}))

    def request(self, method: str, url: str, **kwargs) -> FakeResponse:
        self.calls.append({"url": url, "method": method, **kwargs})
        key = f"{method.upper()} {url}"
        if key not in self.responses:
            pytest.fail(f"unexpected request {key}")
        return FakeResponse(self.responses[key])

    def close(self) -> None:
        pass


class FakeClient:
    """Adapter-level stub for the native API client.

    Mirrors ``TrimMediaClient.request``: responses are registered as full
    ``{"code": 0, "data": ...}`` envelopes and the ``data`` payload is returned.
    """

    def __init__(self, responses: dict[str, object] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str, object]] = []

    def request(self, api, method="get", data=None, params=None, base_path="/v/api/v1"):
        self.calls.append((api, method, data))
        payload = self.responses.get(api)
        if payload is None:
            raise TrimMediaApiError(-1, f"no canned response for {api}")
        if callable(payload):
            payload = payload(data)
        if not isinstance(payload, dict):
            return payload
        code = int(payload.get("code", -1))
        if code != 0:
            raise TrimMediaApiError(code, str(payload.get("msg", "")))
        return payload.get("data")

    def called(self, api: str, method: str | None = None) -> list[object]:
        return [
            data
            for path, verb, data in self.calls
            if path == api and (method is None or verb == method)
        ]


class FakeSecret:
    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


def make_server_settings(**overrides) -> TrimMediaSettings:
    payload = {
        "name": "trimmedia-main",
        "baseurl": "http://fnos.lan:5666",
        "username": "fnos-admin",
        "password": "secret",
    }
    payload.update(overrides)
    return TrimMediaSettings(**payload)


def make_adapter(
    client: FakeClient,
    *,
    settings: AppSettings | None = None,
    server_settings: TrimMediaSettings | None = None,
    users: dict[str, str] | None = None,
    user_libraries: dict[str, set[str]] | None = None,
    libraries: dict[str, tuple[str, str]] | None = None,
) -> TrimMedia:
    adapter = object.__new__(TrimMedia)
    adapter.app_settings = settings if settings is not None else settings_override()
    adapter.server_settings = server_settings or make_server_settings()
    adapter.server_type = "TrimMedia"
    adapter.server_name = adapter.server_settings.name
    adapter.update_partial = True
    adapter.server_version = "test"
    adapter._client = client
    adapter.users = users if users is not None else {"fnos-admin": ADMIN_GUID}
    adapter._user_libraries = user_libraries or {}
    adapter._libraries = (
        libraries
        if libraries is not None
        else {MOVIE_LIBRARY: ("Movies", "movies"), TV_LIBRARY: ("Shows", "tvshows")}
    )
    adapter._locations = {}
    adapter._location_lookups = 0
    adapter._clients = {}
    return adapter


def movie_item(
    guid: str,
    *,
    title: str = "Movie",
    watched: int = 0,
    ts: int = 0,
    duration: int = 6000,
    trim_id: str | None = "tm1391021",
    imdb_id: str = "tt1234567",
) -> dict:
    return {
        "guid": guid,
        "title": title,
        "type": "Movie",
        "watched": watched,
        "ts": ts,
        "duration": duration,
        "trim_id": trim_id,
        "imdb_id": imdb_id,
    }


def episode_item(
    guid: str,
    *,
    series: str = "Show",
    watched: int = 0,
    ts: int = 0,
    season: int = 1,
    number: int = 1,
    trim_id: str = "tt297982",
    imdb_id: str = "tt37819415",
) -> dict:
    return {
        "guid": guid,
        "title": f"Episode {number}",
        "type": "Episode",
        "tv_title": series,
        "ancestor_guid": TV_LIBRARY,
        "watched": watched,
        "ts": ts,
        "duration": 2400,
        "season_number": season,
        "episode_number": number,
        "trim_id": trim_id,
        "imdb_id": imdb_id,
    }


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_trimmedia_settings_default_to_the_client_api_key() -> None:
    server = make_server_settings()
    assert server.api_key == TRIMMEDIA_DEFAULT_API_KEY
    assert server.access_code is None
    assert server.user_credentials == {}


def test_trimmedia_settings_are_part_of_all_servers() -> None:
    settings = settings_override(
        trimmedia=[
            {
                "name": "trimmedia-main",
                "baseurl": "http://fnos.lan:5666",
                "username": "fnos-admin",
                "password": "secret",
            }
        ]
    )
    assert [server.name for server in settings.all_servers] == [
        "plex-main",
        "jellyfin-main",
        "trimmedia-main",
    ]


def test_server_token_override_replaces_the_trimmedia_password() -> None:
    settings = AppSettings.model_validate(
        {
            "jellyfin": [
                {"name": "jellyfin-main", "baseurl": "http://jellyfin", "token": "x"}
            ],
            "trimmedia": [
                {
                    "name": "trimmedia-main",
                    "baseurl": "http://fnos.lan:5666",
                    "username": "fnos-admin",
                    "password": "from-yaml",
                    "sync_to": ["jellyfin-main"],
                }
            ],
            "_server_token_overrides": (("trimmedia-main", "from-env"),),
        }
    )
    server = settings.trimmedia[0]
    assert server.password.get_secret_value() == "from-env"
    assert server.username == "fnos-admin"


def test_server_token_override_rejects_unknown_names() -> None:
    with pytest.raises(Exception):
        AppSettings.model_validate(
            {
                "jellyfin": [
                    {"name": "jellyfin-main", "baseurl": "http://jellyfin", "token": "x"}
                ],
                "trimmedia": [
                    {
                        "name": "trimmedia-main",
                        "baseurl": "http://fnos.lan:5666",
                        "username": "fnos-admin",
                        "password": "from-yaml",
                    }
                ],
                "_server_token_overrides": (("missing-server", "x"),),
            }
        )


def test_legacy_environment_builds_trimmedia_server_and_directions() -> None:
    resolved = resolve_legacy_env(
        {},
        {
            "TRIMMEDIA_BASEURL": "http://fnos.lan:5666",
            "TRIMMEDIA_USERNAME": "fnos-admin",
            "TRIMMEDIA_PASSWORD": "secret",
            "JELLYFIN_BASEURL": "http://jellyfin.lan:8096",
            "JELLYFIN_TOKEN": "token",
            "SYNC_FROM_TRIMMEDIA_TO_JELLYFIN": "true",
            "SYNC_FROM_JELLYFIN_TO_TRIMMEDIA": "True",
        },
    )
    settings = AppSettings.model_validate(legacy_env_to_field_dict(resolved))

    assert [server.name for server in settings.all_servers] == [
        "jellyfin-main",
        "trimmedia-main",
    ]
    trimmedia = settings.trimmedia[0]
    assert trimmedia.username == "fnos-admin"
    assert trimmedia.password.get_secret_value() == "secret"
    assert trimmedia.sync_to == ["jellyfin-main"]
    assert settings.jellyfin[0].sync_to == ["trimmedia-main"]


def test_unrecognized_sync_flag_warns_and_stays_inert() -> None:
    messages: list[str] = []
    sink = logger.add(messages.append, level="WARNING")
    try:
        resolved = resolve_legacy_env({}, {"SYNC_FROM_EMBY_TO_FNOS": "true"})
    finally:
        logger.remove(sink)

    assert resolved == {}
    assert any("SYNC_FROM_EMBY_TO_FNOS" in message for message in messages)


def test_readme_trimmedia_legacy_snippet_is_supported() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    import re

    blocks = [
        dict(dotenv_values(stream=StringIO(block)))
        for block in re.findall(r"```dotenv\n(.*?)```", readme, re.DOTALL)
    ]
    trimmedia_blocks = [block for block in blocks if "TRIMMEDIA_BASEURL" in block]
    assert len(trimmedia_blocks) == 1

    settings = AppSettings.model_validate(
        legacy_env_to_field_dict(trimmedia_blocks[0])
    )
    assert settings.trimmedia[0].username == "fnos-admin"
    assert settings.trimmedia[0].password.get_secret_value() == (
        "replace-with-the-account-password"
    )


def test_sample_configuration_documents_trimmedia() -> None:
    sample = yaml.safe_load((ROOT / "sample.config.yaml").read_text(encoding="utf-8"))
    settings = AppSettings.model_validate(sample)
    server = settings.trimmedia[0]
    assert server.name == "trimmedia-main"
    assert server.username == "fnos-admin"
    assert settings._server_sync_to_index["trimmedia-main"] == set()
    assert "trimmedia-main" in settings._server_names


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #


def test_login_uses_v2_and_keeps_a_single_request() -> None:
    session = FakeSession(
        {"POST http://fnos.lan:5666/v/api/v2/user/loginByPassword": {"code": 0, "data": {"token": "T2"}}}
    )
    client = TrimMediaClient("http://fnos.lan:5666", 10)
    client.session = session

    assert client.login("fnos-admin", "secret") == "T2"
    assert len(session.calls) == 1
    body = json.loads(session.calls[0]["data"])
    assert body["password"] == hashlib.sha256(b"secret").hexdigest()


def test_login_falls_back_to_v1_when_v2_is_missing() -> None:
    session = FakeSession(
        {
            "POST http://fnos.lan:5666/v/api/v2/user/loginByPassword": {
                "message": "Not Implemented, please update."
            },
            "POST http://fnos.lan:5666/v/api/v1/login": {
                "code": 0,
                "data": {"token": "T1"},
            },
        }
    )
    client = TrimMediaClient("http://fnos.lan:5666", 10)
    client.session = session

    assert client.login("fnos-admin", "secret") == "T1"
    legacy_body = json.loads(session.calls[1]["data"])
    assert legacy_body["password"] == "secret"


def test_login_reports_v2_credential_failures_without_falling_back() -> None:
    session = FakeSession(
        {
            "POST http://fnos.lan:5666/v/api/v2/user/loginByPassword": {
                "code": -1,
                "msg": "username or password error",
            }
        }
    )
    client = TrimMediaClient("http://fnos.lan:5666", 10)
    client.session = session

    with pytest.raises(TrimMediaApiError) as error:
        client.login("fnos-admin", "wrong")

    assert error.value.code == -1
    assert len(session.calls) == 1


def test_authx_signs_the_exact_body_that_is_sent() -> None:
    session = FakeSession(
        {"POST http://fnos.lan:5666/v/api/v1/item/watched": {"code": 0, "data": True}}
    )
    client = TrimMediaClient("http://fnos.lan:5666", 10)
    client.session = session
    client.token = "T"

    client.request("/item/watched", "post", {"item_guid": "abc"})

    headers = session.calls[0]["headers"]
    body = session.calls[0]["data"]
    assert body == '{"item_guid":"abc","nonce_placeholder":0}'.replace(
        ',"nonce_placeholder":0', ""
    )
    fields = dict(
        part.split("=", 1) for part in str(headers["authx"]).split("&")
    )
    expected = hashlib.md5(
        "_".join(
            [
                TRIMMEDIA_SIGNING_SECRET,
                "/v/api/v1/item/watched",
                fields["nonce"],
                fields["timestamp"],
                hashlib.md5(body.encode()).hexdigest(),
                TRIMMEDIA_DEFAULT_API_KEY,
            ]
        ).encode()
    ).hexdigest()
    assert fields["sign"] == expected


def test_signed_get_uses_unencoded_query_string() -> None:
    session = FakeSession(
        {"GET http://fnos.lan:5666/v/api/v1/search/list": {"code": 0, "data": []}}
    )
    client = TrimMediaClient("http://fnos.lan:5666", 10)
    client.session = session
    client.token = "T"

    client.request("/search/list", "get", params={"q": "飞驰"})

    headers = session.calls[0]["headers"]
    params = session.calls[0]["params"]
    fields = dict(part.split("=", 1) for part in str(headers["authx"]).split("&"))
    expected = hashlib.md5(
        "_".join(
            [
                TRIMMEDIA_SIGNING_SECRET,
                "/v/api/v1/search/list",
                fields["nonce"],
                fields["timestamp"],
                hashlib.md5("q=飞驰".encode()).hexdigest(),
                TRIMMEDIA_DEFAULT_API_KEY,
            ]
        ).encode()
    ).hexdigest()
    assert fields["sign"] == expected
    assert params == {"q": "飞驰"}


# --------------------------------------------------------------------------- #
# Reading history
# --------------------------------------------------------------------------- #


def test_libraries_without_category_are_inferred_from_contents() -> None:
    def item_list(data):
        movies = data["tags"]["type"] == ["Movie"]
        total = 0
        if data["ancestor_guid"] == "lib-a":
            total = 5 if movies else 0
        elif data["ancestor_guid"] == "lib-b":
            total = 0 if movies else 12
        return {"code": 0, "data": {"total": total, "list": []}}

    client = FakeClient(
        {
            "/mdb/list": {"code": -5, "msg": "Permission Error"},
            "/mediadb/list": {
                "code": 0,
                "data": [{"guid": "lib-a", "title": "Movies"}, {"guid": "lib-b", "title": "Shows"}],
            },
            "/item/list": item_list,
        }
    )
    adapter = make_adapter(client, libraries={})

    libraries = adapter.get_libraries()

    assert libraries == {"Movies": "movies", "Shows": "tvshows"}


def test_get_watched_reads_completed_and_in_progress_movies() -> None:
    client = FakeClient(
        {
            "/item/list": lambda data: {
                "code": 0,
                "data": {
                    "total": 3,
                    "list": [
                        movie_item("m1", title="Done", watched=1, ts=0),
                        movie_item("m2", title="Half", watched=0, ts=3600),
                        movie_item("m3", title="Barely", watched=0, ts=5, trim_id=None, imdb_id=""),
                    ],
                },
            },
            "/stream/list/m1": {
                "code": 0,
                "data": {"files": [{"path": "/vol1/media/Movies/Done/Done - 1080p.mkv"}]},
            },
            "/stream/list/m2": {
                "code": 0,
                "data": {"files": [{"path": "/vol1/media/Movies/Half/Half - 1080p.mkv"}]},
            },
        }
    )
    adapter = make_adapter(
        client,
        libraries={MOVIE_LIBRARY: ("Movies", "movies")},
        users={"fnos-admin": ADMIN_GUID},
    )

    watched = adapter.get_watched({"fnos-admin": ADMIN_GUID}, [MOVIE_LIBRARY])

    movies = watched["fnos-admin"].libraries[MOVIE_LIBRARY].movies
    assert [movie.identifiers.title for movie in movies] == ["Done", "Half"]
    done, half = movies
    assert done.status.completed is True
    assert done.status.time == 0
    assert done.identifiers.tmdb_id == "1391021"
    assert done.identifiers.imdb_id == "tt1234567"
    assert done.identifiers.locations == ("Done - 1080p.mkv",)
    assert half.status.completed is False
    assert half.status.time == 3600 * 1000
    assert half.identifiers.locations == ("Half - 1080p.mkv",)


def test_get_watched_scopes_history_to_the_requested_user() -> None:
    seen: list[dict] = []

    def item_list(data):
        seen.append(data)
        return {"code": 0, "data": {"total": 0, "list": []}}

    adapter = make_adapter(FakeClient({"/item/list": item_list}))
    adapter.get_watched({"other-user": "guid-other"}, [MOVIE_LIBRARY])

    assert seen[0]["user_guid"] == "guid-other"


def test_get_watched_groups_episodes_and_uses_series_folder_locations() -> None:
    client = FakeClient(
        {
            "/item/list": {
                "code": 0,
                "data": {
                    "total": 3,
                    "list": [
                        episode_item("e1", series="兰香如故", watched=1, season=1, number=36),
                        episode_item("e2", series="兰香如故", watched=0, ts=120, season=1, number=35),
                        episode_item("e3", series="Other", watched=0, ts=0),
                    ],
                },
            },
            "/stream/list/e1": {
                "code": 0,
                "data": {
                    "files": [
                        {"path": "/vol1/1000/media/Shows/兰香如故/Season 1/兰香如故 S01E36.mkv"}
                    ]
                },
            },
            "/stream/list/e2": {
                "code": 0,
                "data": {
                    "files": [
                        {"path": "/vol1/1000/media/Shows/兰香如故/Season 1/兰香如故 S01E35.mkv"}
                    ]
                },
            },
        }
    )
    adapter = make_adapter(
        client,
        libraries={TV_LIBRARY: ("Shows", "tvshows")},
    )

    watched = adapter.get_watched({"fnos-admin": ADMIN_GUID}, [TV_LIBRARY])

    series = watched["fnos-admin"].libraries[TV_LIBRARY].series
    assert len(series) == 1
    assert series[0].identifiers.tmdb_id == "297982"
    assert series[0].identifiers.locations == ("兰香如故",)
    assert [episode.identifiers.locations for episode in series[0].episodes] == [
        ("兰香如故 S01E36.mkv",),
        ("兰香如故 S01E35.mkv",),
    ]
    assert [episode.status.completed for episode in series[0].episodes] == [True, False]
    # Episodes must not inherit series-level provider ids: every episode of a
    # series shares them, so they would match each other across servers.
    assert series[0].episodes[0].identifiers.tmdb_id is None
    assert series[0].episodes[0].identifiers.imdb_id is None


def test_get_watched_skips_libraries_without_user_permission() -> None:
    client = FakeClient(
        {
            "/item/list": {"code": 0, "data": {"total": 0, "list": []}},
        }
    )
    adapter = make_adapter(
        client,
        users={"test": "guid-test"},
        user_libraries={"test": {"Movies"}},
    )

    adapter.get_watched({"test": "guid-test"}, [MOVIE_LIBRARY, TV_LIBRARY])

    requested = [path for path, _, _ in client.calls if path == "/item/list"]
    assert len(requested) == 1
    assert client.calls[0][2]["ancestor_guid"] == "Movies"


def test_location_lookups_are_cached_per_item() -> None:
    client = FakeClient(
        {
            "/item/list": {
                "code": 0,
                "data": {"total": 1, "list": [movie_item("m1", watched=1)]},
            },
            "/stream/list/m1": {
                "code": 0,
                "data": {"files": [{"path": "/m/Movie.mkv"}]},
            },
        }
    )
    adapter = make_adapter(client, libraries={MOVIE_LIBRARY: ("Movies", "movies")})

    adapter.get_watched({"fnos-admin": ADMIN_GUID}, [MOVIE_LIBRARY])
    adapter.get_watched({"fnos-admin": ADMIN_GUID}, [MOVIE_LIBRARY])

    stream_calls = [path for path, _, _ in client.calls if path.startswith("/stream/list/")]
    assert stream_calls == ["/stream/list/m1"]


def test_series_folder_derivation_handles_flat_libraries() -> None:
    assert (
        _series_folder_from_path(["/media/Shows/兰香如故/Season 1/ep.mkv"])
        == "兰香如故"
    )
    assert _series_folder_from_path(["/media/Shows/Dark/ep.mkv"]) == "Dark"
    assert _series_folder_from_path([]) is None


# --------------------------------------------------------------------------- #
# Writing state
# --------------------------------------------------------------------------- #


def stored_movie(completed: bool, time_ms: int = 0) -> MediaItem:
    return MediaItem(
        identifiers=MediaIdentifiers(
            title="Movie", locations=("Movie.mkv",), tmdb_id="1391021"
        ),
        status=WatchedStatus(
            completed=completed,
            time=time_ms,
            viewed_date=datetime.now(timezone.utc),
        ),
    )


def update_for(movies: list[MediaItem]) -> tuple[LibraryData, object]:
    from src.watched import WatchedUpdate

    data = LibraryData(title=MOVIE_LIBRARY, library_type="movies", movies=movies)
    return data, WatchedUpdate(
        source_user="alice",
        target_user="fnos-admin",
        source_library=MOVIE_LIBRARY,
        target_library=MOVIE_LIBRARY,
        library_data=data,
    )


def write_settings(*, trimmedia_user: str = "fnos-admin") -> AppSettings:
    return settings_override(
        dryrun=False,
        mark_file=Path("/tmp/jpw-trimmedia-test-mark.log"),
        plex=[
            {
                "name": "plex-main",
                "baseurl": "http://plex",
                "token": "x",
                "sync_to": ["trimmedia-main"],
            }
        ],
        trimmedia=[
            {
                "name": "trimmedia-main",
                "baseurl": "http://fnos.lan:5666",
                "username": "fnos-admin",
                "password": "secret",
                "sync_to": ["plex-main"],
            }
        ],
        user_mappings=[
            {
                "canonical": "alice",
                "aliases": [
                    {"server": "plex-main", "username": "alice"},
                    {"server": "trimmedia-main", "username": trimmedia_user},
                ],
            }
        ],
    )


def test_update_watched_marks_completed_movies() -> None:
    client = FakeClient(
        {
            "/item/list": {
                "code": 0,
                "data": {
                    "total": 1,
                    "list": [movie_item("m1", watched=0, trim_id="tm1391021")],
                },
            },
            "/stream/list/m1": {
                "code": 0,
                "data": {"files": [{"path": "/m/Movie.mkv"}]},
            },
            "/item/watched": {"code": 0, "data": True},
        }
    )
    adapter = make_adapter(
        client,
        settings=write_settings(),
        users={"fnos-admin": ADMIN_GUID},
        libraries={MOVIE_LIBRARY: ("Movies", "movies")},
    )

    _data, update = update_for([stored_movie(completed=True)])
    outcomes = adapter.update_watched([update], "plex-main")

    assert [outcome.status for outcome in outcomes] == ["applied"]
    assert client.called("/item/watched", "post") == [{"item_guid": "m1"}]
    assert outcomes[0].target_user_id == ADMIN_GUID
    assert outcomes[0].target_item_id == "m1"


def test_update_watched_records_partial_progress() -> None:
    client = FakeClient(
        {
            "/item/list": {
                "code": 0,
                "data": {
                    "total": 1,
                    "list": [movie_item("m1", duration=6000, trim_id="tm1391021")],
                },
            },
            "/stream/list/m1": {
                "code": 0,
                "data": {"files": [{"path": "/m/Movie.mkv"}]},
            },
            "/play/info": {
                "code": 0,
                "data": {
                    "media_guid": "media-1",
                    "video_guid": "video-1",
                    "audio_guid": "audio-1",
                    "subtitle_guid": "",
                },
            },
            "/play/record": {"code": 0, "data": True},
        }
    )
    adapter = make_adapter(
        client,
        settings=write_settings(),
        users={"fnos-admin": ADMIN_GUID},
        libraries={MOVIE_LIBRARY: ("Movies", "movies")},
    )

    _data, update = update_for([stored_movie(completed=False, time_ms=90_000)])
    outcomes = adapter.update_watched([update], "plex-main")

    assert [outcome.status for outcome in outcomes] == ["applied"]
    assert client.called("/item/watched", "post") == []
    payloads = client.called("/play/record", "post")
    assert payloads == [
        {
            "item_guid": "m1",
            "media_guid": "media-1",
            "video_guid": "video-1",
            "audio_guid": "audio-1",
            "subtitle_guid": "",
            "play_link": "",
            "ts": 90,
            "duration": 6000,
        }
    ]


def test_update_watched_dryrun_does_not_touch_the_server() -> None:
    client = FakeClient(
        {
            "/item/list": {
                "code": 0,
                "data": {"total": 1, "list": [movie_item("m1", trim_id="tm1391021")]},
            },
            "/stream/list/m1": {
                "code": 0,
                "data": {"files": [{"path": "/m/Movie.mkv"}]},
            },
        }
    )
    settings = write_settings()
    adapter = make_adapter(
        client,
        settings=settings.model_copy(update={"dryrun": True}),
        users={"fnos-admin": ADMIN_GUID},
        libraries={MOVIE_LIBRARY: ("Movies", "movies")},
    )

    _data, update = update_for([stored_movie(completed=True)])
    outcomes = adapter.update_watched([update], "plex-main")

    assert [outcome.status for outcome in outcomes] == ["skipped"]
    assert outcomes[0].reason == "dry-run"
    assert client.called("/item/watched", "post") == []


def test_update_watched_reports_users_without_credentials() -> None:
    client = FakeClient({})
    adapter = make_adapter(
        client,
        settings=write_settings(trimmedia_user="bob"),
        users={"bob": "guid-bob"},
        libraries={MOVIE_LIBRARY: ("Movies", "movies")},
    )

    _data, update = update_for([stored_movie(completed=True)])
    update = update.__class__(
        source_user="alice",
        target_user="bob",
        source_library=MOVIE_LIBRARY,
        target_library=MOVIE_LIBRARY,
        library_data=update.library_data,
    )
    outcomes = adapter.update_watched([update], "plex-main")

    assert [outcome.status for outcome in outcomes] == ["unsupported"]
    assert "no credentials" in (outcomes[0].reason or "")
    assert client.calls == []


def test_update_watched_matches_episodes_by_file_name() -> None:
    client = FakeClient(
        {
            "/item/list": {
                "code": 0,
                "data": {
                    "total": 3,
                    "list": [
                        episode_item("e1", series="兰香如故", season=1, number=36),
                        episode_item("e2", series="兰香如故", season=1, number=35),
                        episode_item(
                            "e9",
                            series="Other",
                            season=1,
                            number=1,
                            trim_id="tt111111",
                            imdb_id="tt9999999",
                        ),
                    ],
                },
            },
            "/stream/list/e1": {
                "code": 0,
                "data": {
                    "files": [
                        {"path": "/vol1/media/Shows/兰香如故/Season 1/兰香如故 S01E36.mkv"}
                    ]
                },
            },
            "/item/watched": {"code": 0, "data": True},
        }
    )
    adapter = make_adapter(
        client,
        settings=write_settings(),
        users={"fnos-admin": ADMIN_GUID},
        libraries={"Shows": (TV_LIBRARY, "tvshows")},
    )

    from src.watched import Series, WatchedUpdate

    show = Series(
        identifiers=MediaIdentifiers(
            title="兰香如故",
            locations=("兰香如故",),
            tmdb_id="297982",
            imdb_id="tt32500958",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Episode 36",
                    locations=("兰香如故 S01E36.mkv",),
                ),
                status=WatchedStatus(
                    completed=True, time=0, viewed_date=datetime.now(timezone.utc)
                ),
            )
        ],
    )
    data = LibraryData(title="Shows", library_type="tvshows", series=[show])
    update = WatchedUpdate(
        source_user="alice",
        target_user="fnos-admin",
        source_library="Shows",
        target_library="Shows",
        library_data=data,
    )

    outcomes = adapter.update_watched([update], "plex-main")

    assert [outcome.status for outcome in outcomes] == ["applied"]
    assert client.called("/item/watched", "post") == [{"item_guid": "e1"}]
    # Only the matched series is resolved to file names, not the whole library.
    stream_calls = [path for path, _, _ in client.calls if path.startswith("/stream/list/")]
    assert stream_calls == ["/stream/list/e1"]


def test_update_watched_reports_unmatched_episodes() -> None:
    client = FakeClient(
        {
            "/item/list": {
                "code": 0,
                "data": {"total": 1, "list": [episode_item("e1", watched=0)]},
            },
            "/stream/list/e1": {
                "code": 0,
                "data": {
                    "files": [{"path": "/vol1/media/Shows/Show/Season 1/other.mkv"}]
                },
            },
        }
    )
    adapter = make_adapter(
        client,
        settings=write_settings(),
        users={"fnos-admin": ADMIN_GUID},
        libraries={"Shows": (TV_LIBRARY, "tvshows")},
    )

    from src.watched import Series, WatchedUpdate

    show = Series(
        identifiers=MediaIdentifiers(title="Show", tmdb_id="297982"),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(locations=("Show S01E01.mkv",)),
                status=WatchedStatus(
                    completed=True, time=0, viewed_date=datetime.now(timezone.utc)
                ),
            )
        ],
    )
    data = LibraryData(title="Shows", library_type="tvshows", series=[show])
    update = WatchedUpdate(
        source_user="alice",
        target_user="fnos-admin",
        source_library="Shows",
        target_library="Shows",
        library_data=data,
    )

    outcomes = adapter.update_watched([update], "plex-main")

    assert [outcome.status for outcome in outcomes] == ["skipped"]
    assert outcomes[0].reason == "media not found"
    assert client.called("/item/watched", "post") == []


def test_update_watched_reports_missing_destination_media() -> None:
    client = FakeClient(
        {
            "/item/list": {"code": 0, "data": {"total": 0, "list": []}},
            "/stream/list/m1": {"code": 0, "data": {"files": []}},
        }
    )
    adapter = make_adapter(
        client,
        settings=write_settings(),
        users={"fnos-admin": ADMIN_GUID},
        libraries={MOVIE_LIBRARY: ("Movies", "movies")},
    )

    _data, update = update_for([stored_movie(completed=True)])
    outcomes = adapter.update_watched([update], "plex-main")

    assert [outcome.status for outcome in outcomes] == ["skipped"]
    assert outcomes[0].reason == "media not found"
    assert client.called("/item/watched", "post") == []
