from src.jellyfin_emby import JellyfinEmby
from packaging import version

class Jellyfin(JellyfinEmby):
    def __init__(self, baseurl, token):
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
            server_type="Jellyfin", baseurl=baseurl, token=token, headers=headers
        )
        
    def is_partial_update_supported(self, server_version):
        return server_version >= version.parse("10.9.0")
