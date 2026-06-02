from loguru import logger

from src.emby import Emby
from src.jellyfin import Jellyfin
from src.plex import Plex
from src.settings import AppSettings, EmbySettings, JellyfinSettings, PlexSettings


def generate_server_connections(settings: AppSettings) -> list[Plex | Jellyfin | Emby]:
    servers: list[Plex | Jellyfin | Emby] = []

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
            logger.debug(f"Jellyfin Server info: {jellyfin_server.info()}")
            servers.append(jellyfin_server)
        elif isinstance(server, EmbySettings):
            emby_server = Emby(
                app_settings=settings,
                server_settings=server,
            )
            logger.debug(f"Emby Server info: {emby_server.info()}")
            servers.append(emby_server)
        else:
            msg = f"Invalid server type: {type(server)}"
            raise Exception(msg)

    return servers
