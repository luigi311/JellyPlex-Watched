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
