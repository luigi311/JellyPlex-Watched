from loguru import logger
from packaging.version import Version, parse

from src.jellyfin_emby import JellyfinEmby
from src.settings import AppSettings, JellyfinSettings


class Jellyfin(JellyfinEmby):
    def __init__(
        self,
        app_settings: AppSettings,
        server_settings: JellyfinSettings,
    ) -> None:
        authorization = (
            "MediaBrowser , "
            'Client="JellyPlex-Watched", '
            'Device="script", '
            'DeviceId="script", '
            'Version="6.0.2", '
            f'Token="{server_settings.token.get_secret_value()}"'
        )
        headers = {
            "Accept": "application/json",
            "Authorization": authorization,
        }

        super().__init__(
            app_settings=app_settings,
            server_settings=server_settings,
            server_type="Jellyfin",
            headers=headers,
        )

    def is_partial_update_supported(self, server_version: Version) -> bool:
        if not server_version >= parse("10.9.0"):
            logger.info(
                f"{self.server_type}: Server version {server_version} does not support updating playback position.",
            )
            return False

        return True
