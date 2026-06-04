from loguru import logger
from packaging.version import Version, parse

from src.jellyfin_emby import JellyfinEmby
from src.settings import AppSettings, EmbySettings


class Emby(JellyfinEmby):
    def __init__(
        self,
        app_settings: AppSettings,
        server_settings: EmbySettings,
    ) -> None:
        authorization = (
            "Emby , "
            'Client="JellyPlex-Watched", '
            'Device="script", '
            'DeviceId="script", '
            'Version="6.0.2"'
        )
        headers = {
            "Accept": "application/json",
            "X-Emby-Token": server_settings.token.get_secret_value(),
            "X-Emby-Authorization": authorization,
        }

        super().__init__(
            app_settings=app_settings,
            server_settings=server_settings,
            server_type="Emby",
            headers=headers,
        )

    def is_partial_update_supported(self, server_version: Version) -> bool:
        if not server_version >= parse("4.4"):
            logger.info(
                f"{self.server_type}: Server version {server_version} does not support updating playback position.",
            )
            return False

        return True
