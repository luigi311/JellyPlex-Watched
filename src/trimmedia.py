"""飞牛影视 (fnOS TrimMedia) integration.

Implements the watched-state contract used by the sync engine against the
native 飞牛影视 HTTP API (``<baseurl>/v/api/v1``).

Behaviours this adapter relies on, verified against fnOS 影视 0.9.8 /
mediasrv 0.8.37:

* ``POST /item/list`` is the only listing endpoint. It requires an explicit
  ``page_size`` and reports the authenticated user's watch state; an admin
  account can read another user's state by passing ``user_guid``.
* ``watched`` is the completed flag and ``ts`` is the resume position in
  seconds, both scoped to the queried user.
* Writes always land on the authenticated account: ``user_guid`` is ignored by
  ``/item/watched`` and ``/play/record``. Writing to another account needs that
  account's credentials (see ``user_credentials``).
* ``GET /stream/list/{guid}`` is the only source of real file paths; both
  ``item/list`` and ``episode/list`` leave ``file_name`` empty.
* Series report ``watched`` = 0 permanently, so completion is derived from
  episodes.
* Provider ids are movie/series level only: ``trim_id`` encodes a TMDB id with
  a ``tm`` (movie) or ``tt`` (TV) prefix and ``imdb_id`` is a real IMDb id.
  Episodes expose no episode-level ids, so episode matching uses file names.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import requests
from loguru import logger

from src.functions import filename_from_any_path, log_marked, normalize_name
from src.settings import (
    TRIMMEDIA_DEFAULT_API_KEY,
    AppSettings,
    TrimMediaSettings,
)
from src.watched import (
    LibraryData,
    MediaIdentifiers,
    MediaItem,
    Series,
    UserData,
    WatchedStatus,
    WatchedUpdate,
    WatchedWriteOutcome,
    WriteOutcomeStatus,
    check_same_identifiers,
    expand_watched_updates,
    resulting_media_item,
)

# Constant factor of the client signature. It is embedded in the 飞牛影视 web
# bundle; ``api_key`` is exposed as configuration because it is shown to
# administrators in the web client.
TRIMMEDIA_SIGNING_SECRET = "NDzZTVxnRKP8Z0jXg1VAMonaG8akvh"

_APP_NAME = "trimemedia-web"
_API_V1 = "/v/api/v1"
_API_V2 = "/v/api/v2"

# Matches the Jellyfin/Emby adapters: a playback position above one minute
# counts as partially watched.
_MIN_PROGRESS_SECONDS = 60

# Path segment that looks like a season folder rather than a series folder.
_SEASON_DIRECTORY = re.compile(
    r"^(?:s\d{1,3}|season[\s._-]*\d{1,3}|specials?|第\s*\d{1,3}\s*季|特别篇)$",
    re.IGNORECASE,
)

_TRIM_ID_PREFIXES = ("tm", "tt")

# Upper bound on per-item ``stream/list`` lookups used to resolve file names
# for a single library in one pass. Provider-id matching normally avoids this
# path entirely; the cap only protects against pathologically large libraries
# when a source item carries no provider ids.
_MAX_LOCATION_LOOKUPS = 500


class TrimMediaError(Exception):
    """Base class for 飞牛影视 integration failures."""


class TrimMediaApiError(TrimMediaError):
    """A 飞牛影视 API call returned a non-zero response code."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"TrimMedia API error {code}: {message}")


class TrimMediaPermissionError(TrimMediaApiError):
    """The authenticated account cannot access the requested library."""


def _parse_trim_id(trim_id: object) -> str | None:
    """Return the TMDB id encoded in a ``trim_id`` (``tm``/``tt`` + digits)."""
    if not isinstance(trim_id, str) or len(trim_id) < 3:
        return None
    if trim_id[:2] not in _TRIM_ID_PREFIXES or not trim_id[2:].isdigit():
        return None
    return trim_id[2:]


def _series_folder_from_path(paths: list[str]) -> str | None:
    """Derive a series folder name from an episode file path.

    ``/Shows/<series>/Season 1/<file>`` yields ``<series>``; a path without a
    recognizable season folder falls back to the file's parent directory.
    """
    for path in paths:
        normalized = path.replace("\\", "/").rstrip("/")
        parts = [part for part in normalized.split("/") if part]
        if len(parts) < 2:
            continue
        parent = parts[-2]
        if _SEASON_DIRECTORY.match(parent) and len(parts) >= 3:
            return parts[-3]
        return parent
    return None


class TrimMediaClient:
    """Signed transport for the 飞牛影视 native API."""

    def __init__(
        self,
        baseurl: str,
        request_timeout: int,
        api_key: str = TRIMMEDIA_DEFAULT_API_KEY,
        access_code: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        root = baseurl.rstrip("/")
        if root.endswith("/v"):
            root = root[: -len("/v")]
        self.root = root.rstrip("/")
        self.api_key = api_key
        self.access_code = access_code
        self.request_timeout = request_timeout
        self.session = session if session is not None else requests.Session()
        self.token: str | None = None
        self.username: str | None = None

    # ------------------------------------------------------------------ #
    # Transport                                                            #
    # ------------------------------------------------------------------ #

    def _authx(self, api_path: str, payload: str | None) -> str:
        nonce = str(random.randint(100000, 999999))
        timestamp = str(int(time.time() * 1000))
        body_hash = hashlib.md5((payload or "").encode()).hexdigest()
        signature = hashlib.md5(
            "_".join(
                [
                    TRIMMEDIA_SIGNING_SECRET,
                    api_path,
                    nonce,
                    timestamp,
                    body_hash,
                    self.api_key,
                ]
            ).encode()
        ).hexdigest()
        return f"nonce={nonce}&timestamp={timestamp}&sign={signature}"

    @staticmethod
    def _serialize(data: dict[str, Any]) -> str:
        # The server hashes the exact bytes it receives, so this must stay the
        # single source of truth for both the request body and the signature.
        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)

    def _send(
        self,
        method: str,
        api: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        base_path: str = _API_V1,
    ) -> dict[str, Any] | None:
        """Perform one signed request; returns the raw response or None.

        ``None`` means the endpoint is not implemented by this server version
        (the service answers unknown ``/v`` paths without a response code).
        """
        api = api if api.startswith("/") else f"/{api}"
        api_path = base_path + api
        body: str | None = None
        if method != "get" and data is not None:
            body = self._serialize(data)
        elif method == "get" and params:
            body = "&".join(f"{key}={value}" for key, value in params.items())

        headers = {
            "Accept": "application/json",
            "Referer": self.root,
            "authx": self._authx(api_path, body),
        }
        if self.token:
            headers["Authorization"] = self.token
        if body is not None and method != "get":
            headers["Content-Type"] = "application/json"

        try:
            response = self.session.request(
                method.upper(),
                self.root + api_path,
                headers=headers,
                params=params if method == "get" else None,
                data=body,
                timeout=self.request_timeout,
            )
        except requests.RequestException as error:
            raise TrimMediaError(f"request to {api_path} failed: {error}") from error

        if response.status_code >= 400:
            raise TrimMediaError(
                f"request to {api_path} failed with status {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def request(
        self,
        api: str,
        method: str = "get",
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        base_path: str = _API_V1,
    ) -> Any:
        """Perform a signed request and return its ``data`` payload."""
        payload = self._send(method, api, data, params, base_path)
        if payload is None or "code" not in payload:
            return None
        code = int(payload.get("code", -1))
        if code == 0:
            return payload.get("data")
        if code == -2:
            raise TrimMediaError(
                "TrimMedia session expired; re-authenticate the configured account"
            )
        if code == -5:
            raise TrimMediaPermissionError(code, str(payload.get("msg", "")))
        raise TrimMediaApiError(code, str(payload.get("msg", "")))

    # ------------------------------------------------------------------ #
    # Authentication                                                        #
    # ------------------------------------------------------------------ #

    def verify_access_code(self) -> None:
        """Validate the optional NAS access code and store its session cookie."""
        if not self.access_code:
            return
        response = self.session.get(
            f"{self.root}/c/{self.access_code}",
            timeout=self.request_timeout,
            allow_redirects=True,
        )
        if response.status_code == 404:
            raise TrimMediaError("TrimMedia access code was rejected")
        if not response.ok:
            raise TrimMediaError(
                f"TrimMedia access code check failed with status {response.status_code}"
            )

    def login(self, username: str, password: str) -> str:
        """Log in and return the session token.

        Newer servers expose ``/v/api/v2/user/loginByPassword`` with a SHA256
        password digest; older servers only have the v1 plaintext endpoint.
        """
        self.verify_access_code()

        payload = {
            "username": username,
            "password": hashlib.sha256(password.encode()).hexdigest(),
            "app_name": _APP_NAME,
        }
        response = self._send("post", "/user/loginByPassword", payload, base_path=_API_V2)
        if response is not None and "code" in response:
            code = int(response.get("code", -1))
            if code == 0:
                token = (response.get("data") or {}).get("token")
                if not token:
                    raise TrimMediaError("TrimMedia login returned no token")
                self.token = str(token)
                self.username = username
                return self.token
            raise TrimMediaApiError(code, str(response.get("msg", "")))

        # v2 is unavailable on this server version; fall back to the legacy
        # plaintext endpoint.
        legacy = {
            "username": username,
            "password": password,
            "app_name": _APP_NAME,
        }
        response = self._send("post", "/login", legacy)
        if response is None or "code" not in response:
            raise TrimMediaError("TrimMedia login endpoint is unavailable")
        code = int(response.get("code", -1))
        if code != 0:
            raise TrimMediaApiError(code, str(response.get("msg", "")))
        token = (response.get("data") or {}).get("token")
        if not token:
            raise TrimMediaError("TrimMedia login returned no token")
        self.token = str(token)
        self.username = username
        return self.token

    def close(self) -> None:
        self.session.close()


class TrimMedia:
    """Sync-engine adapter for a 飞牛影视 server."""

    def __init__(
        self,
        app_settings: AppSettings,
        server_settings: TrimMediaSettings,
    ) -> None:
        self.app_settings = app_settings
        self.server_settings = server_settings
        self.server_type = "TrimMedia"
        self.server_name = server_settings.name
        self.update_partial = True

        self._client = self._new_client(
            server_settings.username,
            server_settings.password.get_secret_value(),
        )
        self.server_version = self._fetch_version()
        self.users: dict[str, str] = {}
        self._user_libraries: dict[str, set[str]] = {}
        self._load_users()

        self._libraries: dict[str, tuple[str, str]] = {}
        self._locations: dict[tuple[str, str], tuple[tuple[str, ...], list[str]]] = {}
        self._location_lookups = 0
        self._clients: dict[str, TrimMediaClient] = {}

    # ------------------------------------------------------------------ #
    # Client plumbing                                                       #
    # ------------------------------------------------------------------ #

    def _new_client(self, username: str, password: str) -> TrimMediaClient:
        client = TrimMediaClient(
            baseurl=self.server_settings.baseurl,
            request_timeout=self.app_settings.request_timeout,
            api_key=self.server_settings.api_key,
            access_code=(
                self.server_settings.access_code.get_secret_value()
                if self.server_settings.access_code is not None
                else None
            ),
        )
        client.login(username, password)
        return client

    def _credentials_for(self, username: str) -> tuple[TrimMediaClient, str] | None:
        """Return a client able to write as ``username``.

        Writes always apply to the authenticated account, so only the
        configured account (and accounts listed in ``user_credentials``) can
        receive updates.
        """
        normalized = normalize_name(username)
        configured = normalize_name(self.server_settings.username)
        if normalized == configured:
            return self._client, self.server_settings.username

        for target, secret in self.server_settings.user_credentials.items():
            if normalize_name(target) != normalized:
                continue
            client = self._clients.setdefault(
                normalize_name(target),
                self._new_client(target, secret.get_secret_value()),
            )
            return client, target
        return None

    def _fetch_version(self) -> str:
        try:
            data = self._client.request("/sys/version")
        except TrimMediaError as error:
            logger.debug(f"TrimMedia: failed to read server version, {error}")
            return "unknown"
        if not isinstance(data, dict):
            return "unknown"
        frontend = data.get("version") or "unknown"
        backend = data.get("mediasrvVersion")
        return f"{frontend} (mediasrv {backend})" if backend else str(frontend)

    def _load_users(self) -> None:
        """Populate ``users`` and per-user library permissions.

        ``/manager/user/list`` needs an administrator account; a non-admin
        credential can only ever act on itself.
        """
        try:
            entries = self._client.request("/manager/user/list")
        except TrimMediaError as error:
            logger.debug(f"TrimMedia: user list unavailable, {error}")
            entries = None

        if isinstance(entries, list) and entries:
            for entry in entries:
                name = entry.get("username")
                guid = entry.get("guid")
                if not name or not guid:
                    continue
                self.users[str(name)] = str(guid)
                granted = {
                    str(library.get("guid"))
                    for library in (entry.get("mediadb_list") or [])
                    if library.get("guid")
                }
                self._user_libraries[normalize_name(str(name))] = granted
            return

        info = self._client.request("/user/info")
        if isinstance(info, dict) and info.get("username") and info.get("guid"):
            name = str(info["username"])
            self.users[name] = str(info["guid"])
        else:
            self.users[str(self.server_settings.username)] = ""
            logger.warning(
                "TrimMedia: could not enumerate users; only the configured "
                "account will be available for sync",
            )

    # ------------------------------------------------------------------ #
    # Libraries                                                             #
    # ------------------------------------------------------------------ #

    def info(self) -> str:
        """Return a human-readable description of this server."""
        return f"{self.server_type} {self.server_name}: {self.server_version}"

    def _ensure_libraries(self) -> None:
        if self._libraries:
            return
        entries = None
        try:
            # The administrator view carries the library category; the plain
            # /mediadb/list view omits it.
            entries = self._client.request("/mdb/list")
        except TrimMediaPermissionError:
            entries = None
        except TrimMediaError as error:
            logger.debug(f"TrimMedia: /mdb/list failed, {error}")
        if not isinstance(entries, list):
            try:
                entries = self._client.request("/mediadb/list")
            except TrimMediaError as error:
                logger.error(f"TrimMedia: failed to list libraries, {error}")
                entries = []

        for entry in entries or []:
            guid = entry.get("guid")
            name = entry.get("name") or entry.get("title")
            category = str(entry.get("category") or "").strip().lower()
            if not guid or not name:
                continue
            if category == "movie":
                library_type = "movies"
            elif category == "tv":
                library_type = "tvshows"
            else:
                # The admin view carries the category; the plain /mediadb/list
                # view omits it, so fall back to probing the library contents.
                library_type = self._infer_library_type(str(guid))
                if library_type is None:
                    logger.debug(
                        f"TrimMedia: skipping library {name} with unknown type"
                    )
                    continue
            self._libraries[str(name)] = (str(guid), library_type)

    def _infer_library_type(self, library_guid: str) -> str | None:
        """Determine a library's type by probing its contents.

        Used when the API omits ``category`` (non-administrator accounts).
        """
        for item_types, library_type in (
            (["Movie"], "movies"),
            (["Episode"], "tvshows"),
        ):
            try:
                data = self._client.request(
                    "/item/list",
                    "post",
                    {
                        "ancestor_guid": library_guid,
                        "exclude_grouped_video": 1,
                        "sort_column": "create_time",
                        "sort_type": "DESC",
                        "page": 1,
                        "page_size": 1,
                        "tags": {"type": item_types},
                    },
                )
            except TrimMediaError:
                continue
            if isinstance(data, dict) and int(data.get("total") or 0) > 0:
                return library_type
        return None

    def get_libraries(self) -> dict[str, str]:
        self._ensure_libraries()
        return {name: kind for name, (_, kind) in self._libraries.items()}

    def _user_library_filter(self, user_name: str) -> set[str] | None:
        granted = self._user_libraries.get(normalize_name(user_name))
        return granted if granted else None

    def get_user_libraries(self, user: tuple[str, str]) -> dict[str, str]:
        """Return the libraries this user can see.

        The library list is server-wide; per-user access comes from the
        administrator user listing. A user without a recorded permission set
        falls back to every library so single-account setups still work.
        """
        user_name, _ = user
        self._ensure_libraries()
        allowed = self._user_library_filter(user_name)
        libraries: dict[str, str] = {}
        for name, (guid, kind) in self._libraries.items():
            if allowed is not None and guid not in allowed:
                continue
            libraries[name] = kind
        return libraries

    # ------------------------------------------------------------------ #
    # Watched history                                                       #
    # ------------------------------------------------------------------ #

    def _iter_items(
        self,
        library_guid: str,
        item_types: list[str],
        user_guid: str | None = None,
        page_size: int = 200,
    ) -> Iterator[dict[str, Any]]:
        page = 1
        while True:
            body: dict[str, Any] = {
                "ancestor_guid": library_guid,
                "exclude_grouped_video": 1,
                "sort_column": "create_time",
                "sort_type": "DESC",
                "page": page,
                "page_size": page_size,
                "tags": {"type": list(item_types)},
            }
            if user_guid:
                body["user_guid"] = user_guid
            try:
                data = self._client.request("/item/list", "post", body)
            except TrimMediaPermissionError as error:
                logger.debug(
                    f"TrimMedia: {self.server_type} access denied for library "
                    f"{library_guid}: {error.message}"
                )
                return
            if not isinstance(data, dict):
                return
            items = data.get("list") or []
            for item in items:
                yield item
            total = int(data.get("total") or 0)
            if len(items) < page_size or page * page_size >= total:
                return
            page += 1

    def _paths(self, item_guid: str) -> tuple[tuple[str, ...], list[str]]:
        """Return (file basenames, raw paths) for one item, cached."""
        key = (normalize_name(self.server_settings.name), item_guid)
        cached = self._locations.get(key)
        if cached is not None:
            return cached

        locations: tuple[str, ...] = tuple()
        raw: list[str] = []
        if self._location_lookups >= _MAX_LOCATION_LOOKUPS:
            logger.debug(
                f"TrimMedia: location lookup limit reached; "
                f"{item_guid} will be matched by provider ids only"
            )
        else:
            self._location_lookups += 1
            try:
                data = self._client.request(f"/stream/list/{item_guid}")
            except TrimMediaError as error:
                logger.debug(f"TrimMedia: stream/list failed for {item_guid}, {error}")
                data = None
            files = (data or {}).get("files") if isinstance(data, dict) else None
            raw = [
                str(entry["path"])
                for entry in (files or [])
                if isinstance(entry, dict) and entry.get("path")
            ]
            locations = tuple(filename_from_any_path(path) for path in raw)

        result = (locations, raw)
        self._locations[key] = result
        return result

    def _item_locations(self, item: dict[str, Any], generate_locations: bool) -> tuple[str, ...]:
        if not generate_locations:
            return tuple()
        locations, _ = self._paths(str(item.get("guid")))
        if not locations:
            file_name = item.get("file_name")
            if file_name:
                locations = (filename_from_any_path(str(file_name)),)
        return locations

    def _item_guids(self, item: dict[str, Any], generate_guids: bool) -> tuple[str | None, str | None]:
        """Return (imdb_id, tmdb_id) for a movie/series level item."""
        if not generate_guids:
            return None, None
        imdb_id = item.get("imdb_id") or None
        tmdb_id = _parse_trim_id(item.get("trim_id"))
        return (
            str(imdb_id) if imdb_id else None,
            tmdb_id,
        )

    def _media_item(self, item: dict[str, Any], status: WatchedStatus) -> MediaItem:
        imdb_id, tmdb_id = self._item_guids(item, self.app_settings.generate_guids)
        return MediaItem(
            identifiers=MediaIdentifiers(
                title=item.get("title") or None,
                locations=self._item_locations(item, self.app_settings.generate_locations),
                imdb_id=imdb_id,
                tmdb_id=tmdb_id,
            ),
            status=status,
        )

    def _episode_item(self, item: dict[str, Any], status: WatchedStatus) -> MediaItem:
        # fnOS exposes only series-level provider ids on episodes, so episodes
        # are matched by file name (the engine never treats titles as identity).
        return MediaItem(
            identifiers=MediaIdentifiers(
                title=item.get("title") or None,
                locations=self._item_locations(item, self.app_settings.generate_locations),
            ),
            status=status,
        )

    def _series_identifiers(self, item: dict[str, Any]) -> MediaIdentifiers:
        imdb_id, tmdb_id = self._item_guids(item, self.app_settings.generate_guids)
        locations: tuple[str, ...] = tuple()
        if self.app_settings.generate_locations:
            _, raw_paths = self._paths(str(item.get("guid")))
            folder = _series_folder_from_path(raw_paths)
            if folder:
                locations = (filename_from_any_path(folder),)
        return MediaIdentifiers(
            title=item.get("tv_title") or item.get("title") or None,
            locations=locations,
            imdb_id=imdb_id,
            tmdb_id=tmdb_id,
        )

    def _watched_status(self, item: dict[str, Any]) -> WatchedStatus | None:
        """Return the sync-relevant state, or None when nothing was watched.

        fnOS does not expose a last-played timestamp, so the fetch time is used,
        mirroring the Jellyfin/Emby adapters when ``LastPlayedDate`` is absent.
        """
        viewed_date = datetime.now(timezone.utc)
        if item.get("watched") == 1:
            return WatchedStatus(completed=True, time=0, viewed_date=viewed_date)
        position = int(item.get("ts") or 0)
        if position > _MIN_PROGRESS_SECONDS:
            return WatchedStatus(
                completed=False,
                time=position * 1000,
                viewed_date=viewed_date,
            )
        return None

    def get_user_library_watched(
        self,
        user_name: str,
        user_id: str,
        library_type: str,
        library_guid: str,
        library_title: str,
    ) -> LibraryData | None:
        logger.info(
            f"TrimMedia: Generating watched for {user_name} in library {library_title}",
        )
        watched = LibraryData(title=library_title, library_type=library_type)
        try:
            if library_type == "movies":
                for item in self._iter_items(library_guid, ["Movie"], user_id):
                    status = self._watched_status(item)
                    if status is None:
                        continue
                    watched.movies.append(self._media_item(item, status))
            elif library_type == "tvshows":
                series: dict[tuple[str, str, str], Series] = {}
                for item in self._iter_items(library_guid, ["Episode"], user_id):
                    status = self._watched_status(item)
                    if status is None:
                        continue
                    key = (
                        str(item.get("ancestor_guid") or ""),
                        str(item.get("tv_title") or ""),
                        str(item.get("trim_id") or ""),
                    )
                    group = series.get(key)
                    if group is None:
                        group = Series(identifiers=self._series_identifiers(item))
                        series[key] = group
                    group.episodes.append(self._episode_item(item, status))
                watched.series = [group for group in series.values() if group.episodes]
            else:
                return None
        except TrimMediaError as error:
            logger.error(
                f"TrimMedia: Failed to get watched for {user_name} in "
                f"{library_title}, {error}"
            )
            return None
        return watched

    def get_watched(
        self,
        users: dict[str, str],
        sync_libraries: list[str],
        users_watched: dict[str, UserData] | None = None,
        *,
        library_types: dict[str, str] | None = None,
    ) -> dict[str, UserData]:
        """Fetch watched history for the requested users and libraries."""
        if not users_watched:
            users_watched = {}
        self._location_lookups = 0
        sync_library_names = {normalize_name(name) for name in sync_libraries}
        discovered_types = {
            normalize_name(name): kind for name, kind in (library_types or {}).items()
        }

        try:
            for user_name, user_id in users.items():
                user_key = normalize_name(user_name)
                users_watched.setdefault(user_key, UserData())
                allowed = self._user_library_filter(user_name)

                for library_name, (library_guid, library_kind) in self._libraries.items():
                    if normalize_name(library_name) not in sync_library_names:
                        continue
                    if allowed is not None and library_guid not in allowed:
                        logger.debug(
                            f"TrimMedia: {user_name} has no access to "
                            f"{library_name}, skipping"
                        )
                        continue
                    if library_name in users_watched[user_key].libraries:
                        logger.info(
                            f"TrimMedia: {user_name} {library_name} watched "
                            "history has already been gathered, skipping"
                        )
                        continue

                    library_type = discovered_types.get(
                        normalize_name(library_name), library_kind
                    )
                    if library_type not in ("movies", "tvshows"):
                        continue

                    library_data = self.get_user_library_watched(
                        user_name,
                        user_id,
                        library_type,
                        library_guid,
                        library_name,
                    )
                    if library_data is None:
                        continue
                    users_watched[user_key].libraries[library_name] = library_data
        except TrimMediaError as error:
            logger.error(f"TrimMedia: Failed to get watched, {error}")
            return {}
        return users_watched

    # ------------------------------------------------------------------ #
    # Writes                                                                #
    # ------------------------------------------------------------------ #

    def _resolve_local_users(self, source_server: str, source_user: str) -> list[tuple[str, str]]:
        this_server = self.server_settings.name
        candidates = {
            normalize_name(name)
            for name in self.app_settings.sync_targets_for_user(
                source_server, source_user, this_server
            )
        }
        return [
            (name, guid)
            for name, guid in self.users.items()
            if normalize_name(name) in candidates
        ]

    def _resolve_local_libraries(
        self, source_server: str, source_library: str
    ) -> list[tuple[str, str, str]]:
        this_server = self.server_settings.name
        candidates = {
            normalize_name(name)
            for name in self.app_settings.sync_targets_for_library(
                source_server, source_library, this_server
            )
        }
        self._ensure_libraries()
        return [
            (name, guid, kind)
            for name, (guid, kind) in self._libraries.items()
            if normalize_name(name) in candidates
        ]

    def _destination_movies(self, library_guid: str) -> list[dict[str, Any]]:
        return list(self._iter_items(library_guid, ["Movie"]))

    def _destination_episodes(self, library_guid: str) -> list[dict[str, Any]]:
        return list(self._iter_items(library_guid, ["Episode"]))

    def _matches(self, identifiers: MediaIdentifiers, item: dict[str, Any]) -> bool:
        candidate = self._destination_identifiers(item)
        return check_same_identifiers(identifiers, candidate)

    def _destination_identifiers(self, item: dict[str, Any]) -> MediaIdentifiers:
        imdb_id, tmdb_id = self._item_guids(item, self.app_settings.generate_guids)
        return MediaIdentifiers(
            title=item.get("title") or None,
            locations=self._item_locations(item, self.app_settings.generate_locations),
            imdb_id=imdb_id,
            tmdb_id=tmdb_id,
        )

    def _find_movie(
        self,
        stored: MediaItem,
        movies: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for item in movies:
            if self._matches(stored.identifiers, item):
                return item
        return None

    def _series_key(self, item: dict[str, Any]) -> MediaIdentifiers:
        imdb_id, tmdb_id = self._item_guids(item, self.app_settings.generate_guids)
        return MediaIdentifiers(
            title=item.get("tv_title") or item.get("title") or None,
            imdb_id=imdb_id,
            tmdb_id=tmdb_id,
        )

    @staticmethod
    def _provider_keys(identifiers: MediaIdentifiers) -> set[tuple[str, str]]:
        """Return the provider-id keys usable for grouping."""
        keys: set[tuple[str, str]] = set()
        for provider, value in (
            ("imdb", identifiers.imdb_id),
            ("tvdb", identifiers.tvdb_id),
            ("tmdb", identifiers.tmdb_id),
        ):
            if value:
                keys.add((provider, value))
        for provider, value in identifiers.matching_aliases:
            if provider in ("imdb", "tvdb", "tmdb"):
                keys.add((provider, value))
        return keys

    def _destination_series_groups(
        self, episodes: list[dict[str, Any]]
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        """Group destination episodes by the series-level provider ids.

        fnOS reports series ids on every episode, so this avoids resolving file
        names for the whole library just to locate one series.
        """
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in episodes:
            imdb_id, tmdb_id = self._item_guids(item, self.app_settings.generate_guids)
            for provider, value in (("imdb", imdb_id), ("tmdb", tmdb_id)):
                if not value:
                    continue
                key = (provider, value)
                bucket = groups.get(key)
                if bucket is None:
                    bucket = []
                    groups[key] = bucket
                bucket.append(item)
        return groups

    def _candidate_groups(
        self,
        stored_series: MediaIdentifiers,
        groups: dict[tuple[str, str], list[dict[str, Any]]],
        unkeyed: list[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        """Return destination episode groups that could belong to this series."""
        candidates: list[list[dict[str, Any]]] = []
        seen: set[int] = set()
        matched_by_ids = False
        for key in self._provider_keys(stored_series):
            group = groups.get(key)
            if group is None or id(group) in seen:
                continue
            seen.add(id(group))
            candidates.append(group)
            matched_by_ids = True

        if matched_by_ids or not self.app_settings.generate_locations:
            return candidates

        # No provider-id match: fall back to the series folder derived from a
        # single episode path per remaining group.
        for group in groups.values():
            if id(group) in seen:
                continue
            seen.add(id(group))
            series_ids = self._series_identifiers(group[0])
            if check_same_identifiers(series_ids, stored_series):
                candidates.append(group)
        if unkeyed:
            candidates.append(unkeyed)
        return candidates

    def _match_episode(
        self, stored: MediaItem, candidates: list[list[dict[str, Any]]]
    ) -> dict[str, Any] | None:
        for group in candidates:
            for item in group:
                if self._matches(stored.identifiers, item):
                    return item
        return None

    def _write_state(
        self,
        client: TrimMediaClient,
        item: dict[str, Any],
        stored: MediaItem,
        user_name: str,
        user_guid: str,
        library_name: str,
        library_guid: str,
        dryrun: bool,
        series_identifiers: MediaIdentifiers | None = None,
    ) -> WatchedWriteOutcome:
        item_guid = str(item.get("guid"))
        target_identifiers = self._destination_identifiers(item)
        completed = stored.status.completed

        def receipt(status: WriteOutcomeStatus, reason: str | None = None) -> WatchedWriteOutcome:
            return WatchedWriteOutcome(
                status=status,
                target_user=normalize_name(user_name),
                target_library=library_name,
                media_item=(
                    resulting_media_item(stored, completed, target_identifiers)
                    if status == "applied"
                    else stored
                ),
                series_identifiers=series_identifiers,
                target_user_id=user_guid or None,
                target_library_id=library_guid,
                target_item_id=item_guid,
                reason=reason,
            )

        if dryrun:
            logger.success(
                f"[DRYRUN] TrimMedia: {item.get('title')} as "
                f"{'watched' if completed else 'partially watched'} for "
                f"{user_name} in {library_name}"
            )
            return receipt("skipped", "dry-run")

        try:
            if completed:
                client.request("/item/watched", "post", {"item_guid": item_guid})
            else:
                play_info = client.request("/play/info", "post", {"item_guid": item_guid})
                if not isinstance(play_info, dict):
                    return receipt("uncertain", "play info unavailable")
                payload = {
                    "item_guid": item_guid,
                    "media_guid": play_info.get("media_guid") or "",
                    "video_guid": play_info.get("video_guid") or "",
                    "audio_guid": play_info.get("audio_guid") or "",
                    "subtitle_guid": play_info.get("subtitle_guid") or "",
                    "play_link": "",
                    "ts": int(stored.status.time / 1000),
                    "duration": int(item.get("duration") or 0),
                }
                client.request("/play/record", "post", payload)
        except TrimMediaError as error:
            logger.error(
                f"TrimMedia: Failed to update {item.get('title')} for "
                f"{user_name} in {library_name}, {error}"
            )
            return receipt("failed", str(error))

        logger.success(
            f"TrimMedia: {item.get('title')} as "
            f"{'watched' if completed else f'partially watched for {stored.status.time // 60000} minutes'} "
            f"for {user_name} in {library_name}"
        )
        log_marked(
            self.server_type,
            self.server_name,
            user_name,
            library_name,
            str(item.get("title")),
            duration=None if completed else stored.status.time // 60000,
            mark_file=self.app_settings.mark_file,
        )
        return receipt("applied")

    def update_watched(
        self,
        watched_list: dict[str, UserData] | list[WatchedUpdate],
        source_server_name: str,
    ) -> list[WatchedWriteOutcome]:
        """Write completed/partial state onto this 飞牛影视 server."""
        dryrun = self.app_settings.dryrun
        outcomes: list[WatchedWriteOutcome] = []
        this_server = self.server_settings.name
        self._location_lookups = 0

        pending_updates = (
            watched_list
            if isinstance(watched_list, list)
            else expand_watched_updates(
                watched_list,
                source_server_name,
                this_server,
                self.app_settings,
            )
        )

        for update in pending_updates:
            user = update.source_user
            if not self.app_settings.should_sync_user(user, source_server_name, this_server):
                logger.debug(
                    f"TrimMedia: {user} (from {source_server_name}) skipped"
                )
                continue

            target_key = normalize_name(update.target_user)
            resolved_users = [
                resolved
                for resolved in self._resolve_local_users(source_server_name, user)
                if normalize_name(resolved[0]) == target_key
            ]
            if not resolved_users:
                logger.info(
                    f"TrimMedia: {user} (from {source_server_name}) not found "
                    "on this server, skipping"
                )
                continue

            resolved_libraries = [
                resolved
                for resolved in self._resolve_local_libraries(
                    source_server_name, update.source_library
                )
                if normalize_name(resolved[0]) == normalize_name(update.target_library)
            ]
            if not resolved_libraries:
                logger.info(
                    f"TrimMedia: Library {update.source_library} (from "
                    f"{source_server_name}) not found in library list"
                )
                continue

            for user_name, user_guid in resolved_users:
                credentials = self._credentials_for(user_name)
                for library_name, library_guid, library_kind in resolved_libraries:
                    if not self.app_settings.should_sync_scope(
                        user,
                        update.source_library,
                        source_server_name,
                        this_server,
                        library_type=update.library_data.library_type,
                        target_library_type=library_kind,
                    ):
                        continue

                    if credentials is None:
                        reason = (
                            f"no credentials configured for TrimMedia user "
                            f"{user_name}; writes always apply to the "
                            "authenticated account"
                        )
                        logger.warning(
                            f"TrimMedia: skipping {user_name} in {library_name}, {reason}"
                        )
                        for movie in update.library_data.movies:
                            outcomes.append(
                                WatchedWriteOutcome(
                                    status="unsupported",
                                    target_user=normalize_name(user_name),
                                    target_library=library_name,
                                    media_item=movie,
                                    target_user_id=user_guid or None,
                                    target_library_id=library_guid,
                                    reason=reason,
                                )
                            )
                        for show in update.library_data.series:
                            for episode in show.episodes:
                                outcomes.append(
                                    WatchedWriteOutcome(
                                        status="unsupported",
                                        target_user=normalize_name(user_name),
                                        target_library=library_name,
                                        media_item=episode,
                                        series_identifiers=show.identifiers,
                                        target_user_id=user_guid or None,
                                        target_library_id=library_guid,
                                        reason=reason,
                                    )
                                )
                        continue

                    client, _account = credentials
                    try:
                        outcomes.extend(
                            self._update_library(
                                client,
                                library_data=update.library_data,
                                library_guid=library_guid,
                                library_name=library_name,
                                user_name=user_name,
                                user_guid=user_guid,
                                dryrun=dryrun,
                            )
                        )
                    except TrimMediaError as error:
                        logger.error(
                            f"TrimMedia: error updating watched for {user_name} "
                            f"in {library_name}, {error}"
                        )

        return outcomes

    def _update_library(
        self,
        client: TrimMediaClient,
        *,
        library_data: LibraryData,
        library_guid: str,
        library_name: str,
        user_name: str,
        user_guid: str,
        dryrun: bool,
    ) -> list[WatchedWriteOutcome]:
        outcomes: list[WatchedWriteOutcome] = []
        if not library_data.movies and not library_data.series:
            return outcomes

        logger.info(
            f"TrimMedia: Updating watched for {user_name} in library {library_name}"
        )

        if library_data.movies:
            movies = self._destination_movies(library_guid)
            for stored in library_data.movies:
                item = self._find_movie(stored, movies)
                if item is None:
                    outcomes.append(
                        WatchedWriteOutcome(
                            status="skipped",
                            target_user=normalize_name(user_name),
                            target_library=library_name,
                            media_item=stored,
                            target_user_id=user_guid or None,
                            target_library_id=library_guid,
                            reason="media not found",
                        )
                    )
                    continue
                outcomes.append(
                    self._write_state(
                        client,
                        item,
                        stored,
                        user_name,
                        user_guid,
                        library_name,
                        library_guid,
                        dryrun,
                    )
                )

        if library_data.series:
            episodes = self._destination_episodes(library_guid)
            groups = self._destination_series_groups(episodes)
            keyed = {id(item) for group in groups.values() for item in group}
            unkeyed = [item for item in episodes if id(item) not in keyed]
            for show in library_data.series:
                candidates = self._candidate_groups(show.identifiers, groups, unkeyed)
                for stored in show.episodes:
                    item = self._match_episode(stored, candidates)
                    if item is None:
                        outcomes.append(
                            WatchedWriteOutcome(
                                status="skipped",
                                target_user=normalize_name(user_name),
                                target_library=library_name,
                                media_item=stored,
                                series_identifiers=show.identifiers,
                                target_user_id=user_guid or None,
                                target_library_id=library_guid,
                                reason="media not found",
                            )
                        )
                        continue
                    outcomes.append(
                        self._write_state(
                            client,
                            item,
                            stored,
                            user_name,
                            user_guid,
                            library_name,
                            library_guid,
                            dryrun,
                            series_identifiers=show.identifiers,
                        )
                    )
        return outcomes
