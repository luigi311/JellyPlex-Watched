from src.jellyfin_emby import JellyfinEmby
from packaging.version import parse, Version


class Emby(JellyfinEmby):
    def __init__(self, baseurl, token):
        authorization = (
            "Emby , "
            'Client="JellyPlex-Watched", '
            'Device="script", '
            'DeviceId="script", '
            'Version="6.0.2"'
        )
        headers = {
            "Accept": "application/json",
            "X-Emby-Token": token,
            "X-Emby-Authorization": authorization,
        }

        super().__init__(
            server_type="Emby", baseurl=baseurl, token=token, headers=headers
        )

    def is_partial_update_supported(self, server_version: Version) -> bool:
        return server_version > parse("4.4")
