from unittest.mock import Mock, patch

import pytest
from conftest import settings_override
from packaging.version import Version
from plexapi.myplex import MyPlexAccount, MyPlexUser
from plexapi.server import PlexServer

from src.emby import Emby
from src.jellyfin import Jellyfin
from src.jellyfin_emby import JellyfinEmby
from src.plex import Plex
from src.watched import UserData


@pytest.mark.parametrize("adapter", [Jellyfin, Emby])
@pytest.mark.parametrize(
    ("response", "field"),
    [
        ({}, "server name"),
        (None, "server name"),
        ({"Version": "10.10.0"}, "server name"),
        ({"ServerName": 123, "Version": "10.10.0"}, "server name"),
        ({"ServerName": "Test"}, "server version"),
        ({"ServerName": "Test", "Version": None}, "server version"),
    ],
)
def test_adapter_rejects_missing_or_invalid_server_metadata(adapter, response, field):
    settings = settings_override(
        emby=[{"name": "emby-main", "baseurl": "http://emby", "token": "synthetic"}]
    )
    config = settings.jellyfin[0] if adapter is Jellyfin else settings.emby[0]
    with (
        patch.object(JellyfinEmby, "get_users", return_value={}),
        patch.object(JellyfinEmby, "query", return_value=response),
        pytest.raises(ValueError, match=field),
    ):
        adapter(settings, config)


@pytest.mark.parametrize(
    ("adapter", "version", "partial"),
    [
        (Jellyfin, "10.8.0", False),
        (Jellyfin, "10.9.0", True),
        (Emby, "4.3.0", False),
        (Emby, "4.4.0", True),
    ],
)
def test_adapter_initializes_typed_metadata_and_partial_support(adapter, version, partial):
    settings = settings_override(
        emby=[{"name": "emby-main", "baseurl": "http://emby", "token": "synthetic"}]
    )
    config = settings.jellyfin[0] if adapter is Jellyfin else settings.emby[0]
    with (
        patch.object(JellyfinEmby, "get_users", return_value={}),
        patch.object(
            JellyfinEmby, "query", return_value={"ServerName": "Test", "Version": version}
        ),
    ):
        server = adapter(settings, config)

    assert server.server_name == "Test"
    assert server.server_version == Version(version)
    assert server.update_partial is partial


def test_plex_skips_non_admin_accounts_without_aborting_other_users():
    server = object.__new__(Plex)
    server.app_settings = settings_override()
    server.admin_user = Mock(spec=MyPlexAccount, username="admin", title="Admin")
    server.plex = Mock(spec=PlexServer, machineIdentifier="server")
    server.plex.library = Mock()
    server.plex.library.sections.return_value = []
    server.base_url = "http://plex"
    server.login = Mock(return_value=server.plex)
    foreign = Mock(spec=MyPlexAccount, username="foreign", title="Foreign")
    shared = Mock(spec=MyPlexUser, username="shared", title="Shared")
    shared.get_token.return_value = "synthetic-token"
    existing = {"healthy": UserData()}

    result = server.get_watched([foreign, server.admin_user, shared], [], existing)

    assert result is existing
    shared.get_token.assert_called_once_with("server")
    server.login.assert_called_once_with("http://plex", "synthetic-token", None, None, None)
