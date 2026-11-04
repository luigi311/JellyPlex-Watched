from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from src.jellyfin_emby import get_mediaitem as get_jellyfin_emby_mediaitem
from src.plex import get_mediaitem as get_plex_mediaitem


@pytest.mark.parametrize("server_type", ["Jellyfin", "Emby"])
def test_jellyfin_emby_missing_viewed_date_uses_aware_utc(server_type):
    before = datetime.now(UTC)
    media = get_jellyfin_emby_mediaitem(
        server_type, {"Name": "Movie", "UserData": {"Played": True}}, False, False
    )

    assert media.status.viewed_date.tzinfo is UTC
    assert before <= media.status.viewed_date <= datetime.now(UTC)


def test_plex_missing_viewed_date_uses_aware_utc():
    before = datetime.now(UTC)
    media = get_plex_mediaitem(
        Mock(title="Movie", lastViewedAt=None, viewOffset=0), True, False, False
    )

    assert media.status.viewed_date.tzinfo is UTC
    assert before <= media.status.viewed_date <= datetime.now(UTC)


@pytest.mark.parametrize("server_type", ["Jellyfin", "Emby"])
def test_jellyfin_emby_parses_utc_marker_without_replacing_it(server_type):
    media = get_jellyfin_emby_mediaitem(
        server_type,
        {
            "Name": "Movie",
            "UserData": {"Played": True, "LastPlayedDate": "2026-11-04T10:20:30Z"},
        },
        False,
        False,
    )

    assert media.status.viewed_date == datetime(2026, 11, 4, 10, 20, 30, tzinfo=UTC)
