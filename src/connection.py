from loguru import logger

from src.emby import Emby
from src.jellyfin import Jellyfin
from src.plex import Plex
from src.settings import (
    AppSettings,
    EmbySettings,
    JellyfinSettings,
    PlexSettings,
    TrimMediaSettings,
)
from src.trimmedia import TrimMedia


def generate_server_connections(
    settings: AppSettings,
) -> list[Plex | Jellyfin | Emby | TrimMedia]:
    servers: list[Plex | Jellyfin | Emby | TrimMedia] = []

    for server in settings.all_servers:
        if isinstance(server, PlexSettings):
            plex_server = Plex(
                app_settings=settings,
                server_settings=server,
            )

            logger.debug(f"Plex Server info: {plex_server.info()}")
            servers.append(plex_server)

        elif isinstance(server, JellyfinSettings):
            jellyfin_server = Jellyfin(
                app_settings=settings,
                server_settings=server,
            )
            logger.debug(
                f"Jellyfin Server info: {jellyfin_server.server_name}: {jellyfin_server.server_version}"
            )
            servers.append(jellyfin_server)
        elif isinstance(server, EmbySettings):
            emby_server = Emby(
                app_settings=settings,
                server_settings=server,
            )
            logger.debug(
                f"Emby Server info: {emby_server.server_name}: {emby_server.server_version}"
            )
            servers.append(emby_server)
        elif isinstance(server, TrimMediaSettings):
            trimmedia_server = TrimMedia(
                app_settings=settings,
                server_settings=server,
            )
            logger.debug(
                f"TrimMedia Server info: {trimmedia_server.server_name}: {trimmedia_server.server_version}"
            )
            servers.append(trimmedia_server)
        else:
            msg = f"Invalid server type: {type(server)}"
            raise Exception(msg)

    return servers
