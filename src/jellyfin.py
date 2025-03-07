from src.jellyfin_emby import JellyfinEmby
from packaging.version import parse, Version
from loguru import logger


class Jellyfin(JellyfinEmby):
    def __init__(self, base_url: str, token: str) -> None:
        authorization = (
            "MediaBrowser , "
            'Client="JellyPlex-Watched", '
            'Device="script", '
            'DeviceId="script", '
            'Version="6.0.2", '
            f'Token="{token}"'
        )
        headers = {
            "Accept": "application/json",
            "Authorization": authorization,
        }

        super().__init__(
            server_type="Jellyfin", base_url=base_url, token=token, headers=headers
        )

    def is_partial_update_supported(self, server_version: Version) -> bool:
        if not server_version >= parse("10.9.0"):
            logger.info(
                f"{self.server_type}: Server version {server_version} does not support updating playback position.",
            )
            return False

        return True
