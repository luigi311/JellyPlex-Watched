# Functions for Jellyfin and Emby

from datetime import datetime
import requests
import traceback
from math import floor
from typing import Any, Literal
from packaging.version import parse, Version
from loguru import logger

from src.functions import (
    filename_from_any_path,
    search_mapping,
    log_marked,
    str_to_bool,
    get_env_value,
)
from src.watched import (
    LibraryData,
    MediaIdentifiers,
    MediaItem,
    WatchedStatus,
    Series,
    UserData,
    check_same_identifiers,
)


def extract_identifiers_from_item(
    server: Any,
    user_id: str,
    item: dict[str, Any],
    generate_guids: bool,
    generate_locations: bool,
) -> MediaIdentifiers:
    title = item.get("Name")
    id = item.get("Id")
    if not title:
        logger.debug(f"{server.server_type}: Name not found for {id}")

    guids = {}
    if generate_guids:
        guids = {k.lower(): v for k, v in item.get("ProviderIds", {}).items()}

    locations: tuple[str, ...] = tuple()
    full_path: str = ""
    if generate_locations:
        if item.get("Path"):
            full_path = item["Path"]
            locations = tuple([filename_from_any_path(full_path)])
        elif item.get("MediaSources"):
            full_paths = [x["Path"] for x in item["MediaSources"] if x.get("Path")]
            locations = tuple([filename_from_any_path(x) for x in full_paths])
            full_path = " ".join(full_paths)

    if generate_guids and not guids:
        logger.debug(
            f"{server.server_type}: {title or id} has no guids{f', locations: {full_path}' if full_path else ''}",
        )

    if generate_locations and not locations:
        logger.debug(
            f"{server.server_type}: {title or id} has no locations{f', guids: {guids}' if guids else ''}",
        )

    return MediaIdentifiers(
        title=title,
        locations=locations,
        imdb_id=guids.get("imdb"),
        tvdb_id=guids.get("tvdb"),
        tmdb_id=guids.get("tmdb"),
        id=id,
        server=server,
        user_id=user_id,
    )


def get_mediaitem(
    server: Any,
    user_id: str,
    item: dict[str, Any],
    generate_guids: bool,
    generate_locations: bool,
) -> MediaItem:
    user_data = item.get("UserData", {})
    last_played_date = user_data.get("LastPlayedDate")

    viewed_date = datetime.today()
    if last_played_date:
        viewed_date = datetime.fromisoformat(last_played_date.replace("Z", "+00:00"))

    last_updated_at = datetime.today()
    if item.get("DateLastSaved"):
        last_updated_at = datetime.fromisoformat(
            item.get("DateLastSaved").replace("Z", "+00:00")
        )

    return MediaItem(
        identifiers=extract_identifiers_from_item(
            server, user_id, item, generate_guids, generate_locations
        ),
        status=WatchedStatus(
            completed=user_data.get("Played"),
            time=floor(user_data.get("PlaybackPositionTicks", 0) / 10000),
            viewed_date=viewed_date,
            last_updated_at=last_updated_at,
        ),
    )


class JellyfinEmby:
    def __init__(
        self,
        env,
        server_type: Literal["Jellyfin", "Emby"],
        base_url: str,
        token: str,
        headers: dict[str, str],
    ) -> None:
        self.env = env
        self.server_type = server_type
        self.base_url = base_url
        self.token = token
        self.headers = headers
        self.timeout = int(get_env_value(self.env, "REQUEST_TIMEOUT", 300))

        if not self.base_url or not self.token:
            raise Exception(f"{self.server_type} credentials not set")

        self.session = requests.Session()
        self.users = self.get_users()
        self.server_name = self.info(name_only=True)
        self.server_version = self.info(version_only=True)
        self.update_partial = self.is_partial_update_supported(self.server_version)
        self.generate_guids = str_to_bool(get_env_value(self.env, "GENERATE_GUIDS", "True"))
        self.generate_locations = str_to_bool(get_env_value(self.env, "GENERATE_LOCATIONS", "True"))

    def query(self, query: str, query_type: Literal["get", "post", "delete"], json: dict | None = None) -> Any:
        try:
            if query_type == "get":
                response = self.session.get(self.base_url + query, headers=self.headers, timeout=self.timeout)
            elif query_type == "post":
                response = self.session.post(self.base_url + query, headers=self.headers, json=json, timeout=self.timeout)
            elif query_type == "delete":
                response = self.session.delete(self.base_url + query, headers=self.headers, timeout=self.timeout)
            else:
                raise ValueError(f"Unsupported query type: {query_type}")

            response.raise_for_status()

            if response.status_code == 204:
                return None
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"{self.server_type}: Query {query_type} {query} failed: {e}")
            raise

    def info(self, name_only: bool = False, version_only: bool = False) -> Any:
        response = self.query("/System/Info/Public", "get")
        if not response:
            return None
        if name_only:
            return response.get("ServerName")
        if version_only:
            return parse(response.get("Version", ""))
        return f"{self.server_type} {response.get('ServerName')}: {response.get('Version')}"

    def get_users(self) -> dict[str, str]:
        response = self.query("/Users", "get")
        return {user["Name"]: user["Id"] for user in response} if response else {}

    def get_libraries(self) -> dict[str, str]:
        libraries = {}
        for user_id in self.users.values():
            views = self.query(f"/Users/{user_id}/Views", "get")
            if not views:
                continue
            for lib in views.get("Items", []):
                lib_type = lib.get("CollectionType")
                if lib_type in ["movies", "tvshows"]:
                    libraries[lib["Name"]] = lib_type
        return libraries

    def get_user_library_watched(self, user_name: str, user_id: str, library_type: str, library_id: str, library_title: str) -> LibraryData:
        logger.info(f"{self.server_type}: Generating watched for {user_name} in library {library_title}")
        watched = LibraryData(title=library_title)

        fields = "ItemCounts,ProviderIds,MediaSources,DateLastSaved,UserDataLastPlayedDate"

        if library_type == "movies":
            items = []
            for f in ["IsPlayed", "IsResumable"]:
                res = self.query(f"/Users/{user_id}/Items?ParentId={library_id}&Filters={f}&IncludeItemTypes=Movie&Recursive=True&Fields={fields}", "get")
                if res and res.get("Items"):
                    items.extend(res["Items"])

            for item in items:
                if item.get("UserData") and (item["UserData"].get("Played") or item["UserData"].get("PlaybackPositionTicks", 0) > 600000000):
                    watched.movies.append(get_mediaitem(self, user_id, item, self.generate_guids, self.generate_locations))

        elif library_type == "tvshows":
            shows = self.query(f"/Users/{user_id}/Items?ParentId={library_id}&IncludeItemTypes=Series&Recursive=True&Fields=ProviderIds,Path,RecursiveItemCount,DateLastSaved", "get")
            if not shows: return watched

            for show in shows.get("Items", []):
                episodes = self.query(f"/Shows/{show['Id']}/Episodes?userId={user_id}&Fields={fields}", "get")
                if not episodes: continue

                episode_mediaitems = []
                for episode in episodes.get("Items", []):
                    if episode.get("UserData") and (episode["UserData"].get("Played") or episode["UserData"].get("PlaybackPositionTicks", 0) > 600000000):
                        episode_mediaitems.append(get_mediaitem(self, user_id, episode, self.generate_guids, self.generate_locations))

                if episode_mediaitems:
                    watched.series.append(Series(
                        identifiers=extract_identifiers_from_item(self, user_id, show, self.generate_guids, self.generate_locations),
                        episodes=episode_mediaitems
                    ))

        return watched

    def get_watched(self, users: dict[str, str], sync_libraries: list[str], users_watched: dict[str, UserData] = None) -> dict[str, UserData]:
        if not users_watched: users_watched = {}
        for user_name, user_id in users.items():
            user_name_lower = user_name.lower()
            if user_name_lower not in users_watched:
                users_watched[user_name_lower] = UserData()

            views = self.query(f"/Users/{user_id}/Views", "get")
            if not views: continue

            for lib in views.get("Items", []):
                if lib.get("Name") in sync_libraries:
                    if lib.get("Name") in users_watched[user_name_lower].libraries:
                        continue
                    library_data = self.get_user_library_watched(user_name, user_id, lib["CollectionType"], lib["Id"], lib["Name"])
                    users_watched[user_name_lower].libraries[lib["Name"]] = library_data
        return users_watched

    def mark_watched(self, user_id: str, item_id: str, viewed_date: str):
        payload = {"Played": True, "LastPlayedDate": viewed_date}
        self.query(f"/Users/{user_id}/PlayedItems/{item_id}", "post", json=payload)

    def mark_unwatched(self, user_id: str, item_id: str):
        self.query(f"/Users/{user_id}/PlayedItems/{item_id}", "delete")

    def update_watched(self, *args, **kwargs):
        # This function is now deprecated.
        pass

    def is_partial_update_supported(self, server_version: Version) -> bool:
        if not server_version >= parse("10.9.0"):
            logger.info(
                f"{self.server_type}: Server version {server_version} does not support updating playback position.",
            )
            return False

        return True
