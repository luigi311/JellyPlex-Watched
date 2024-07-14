from src.jellyfin_emby import JellyfinEmby


class Jellyfin(JellyfinEmby):
    def __init__(self, baseurl, token):
        authorization = (
            "MediaBrowser , "
            'Client="JellyPlex-Watched", '
            'Device="script", '
            'DeviceId="script", '
            'Version="5.2.0", '
            f'Token="{token}"'
        )
        headers = {
            "Accept": "application/json",
            "Authorization": authorization,
        }

        super().__init__(
            server_type="Jellyfin", baseurl=baseurl, token=token, headers=headers
        )
        
    def is_partial_update_supported(self, version):
        version_parts = version.split('.')
        major, minor, patch = map(int, version_parts[:3])
        return major > 10 or (major >= 10 and minor >= 9)
