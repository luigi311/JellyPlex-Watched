from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from conftest import settings_override
from src.emby import Emby
from src.jellyfin import Jellyfin
from src.plex import Plex
from src.users import generate_all_server_users


@pytest.mark.parametrize('reverse', [False, True])
def test_selects_both_ends_of_one_way_fanout(reverse):
    settings = settings_override(
        plex=[dict(name='plex-main', baseurl='http://plex', token='x',
                   sync_to=['jellyfin-main'] if not reverse else [])],
        jellyfin=[dict(name='jellyfin-main', baseurl='http://jellyfin', token='x',
                      sync_to=['plex-main'] if reverse else [])],
        user_mappings=[dict(canonical='family', aliases=[
            dict(server='plex-main', username='Family'),
            dict(server='jellyfin-main', username='Alice'),
            dict(server='jellyfin-main', username='Bob'),
            dict(server='jellyfin-main', username='Absent'),
        ])],
        blacklist_users=['blocked'],
    )
    plex = object.__new__(Plex)
    plex.server_settings = settings.plex[0]
    family = SimpleNamespace(username=None, title='FAMILY')
    plex.users = [family, SimpleNamespace(username='unmatched'),
                  SimpleNamespace(username='blocked')]
    jellyfin = object.__new__(Jellyfin)
    jellyfin.server_settings = settings.jellyfin[0]
    jellyfin.users = {'ALICE': 'a', 'Bob': 'b', 'blocked': 'c', 'unrelated': 'd'}
    emby = object.__new__(Emby)
    emby.server_settings = SimpleNamespace(name='disconnected')
    emby.users = {'FAMILY': 'e'}
    for server in [plex, jellyfin, emby]:
        server.get_users = Mock(side_effect=AssertionError('Users already fetched'))

    assert generate_all_server_users([plex, jellyfin, emby], settings) == {
        plex: [family], jellyfin: [('ALICE', 'a'), ('Bob', 'b')], emby: [],
    }


def test_no_other_servers_means_no_targets():
    server = object.__new__(Emby)
    server.users = {'alice': 'a'}
    assert generate_all_server_users([server], settings_override()) == {server: []}
    assert generate_all_server_users([], settings_override()) == {}
