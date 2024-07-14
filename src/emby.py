from src.jellyfin_emby import JellyfinEmby


class Emby(JellyfinEmby):
    def __init__(self, baseurl, token):
        authorization = (
            "Emby , "
            'Client="JellyPlex-Watched", '
            'Device="script", '
            'DeviceId="script", '
            'Version="0.0.0"'
        )
        headers = {
            "Accept": "application/json",
            "X-Emby-Token": token,
            "X-Emby-Authorization": authorization,
        }

        super().__init__(
            server_type="Emby", baseurl=baseurl, token=token, headers=headers
        )
    
    def is_partial_update_supported(self, version):
        version_parts = version.split('.')
        major, minor, patch = map(int, version_parts[:3])
        return major > 4 or (major >= 4 and minor >= 4)
