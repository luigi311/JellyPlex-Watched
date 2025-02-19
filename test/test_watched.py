import sys
import os

# getting the name of the directory
# where the this file is present.
current = os.path.dirname(os.path.realpath(__file__))

# Getting the parent directory name
# where the current directory is present.
parent = os.path.dirname(current)

# adding the parent directory to
# the sys.path.
sys.path.append(parent)

from src.watched import (
    LibraryData,
    MediaIdentifiers,
    MediaItem,
    Series,
    UserData,
    WatchedStatus,
    cleanup_watched,
)

tv_shows_watched_list_1: list[Series] = [
    Series(
        identifiers=MediaIdentifiers(
            title="Doctor Who (2005)",
            locations=("Doctor Who (2005) {tvdb-78804} {imdb-tt0436992}",),
            imdb_id="tt0436992",
            tmdb_id="57243",
            tvdb_id="78804",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="The Unquiet Dead",
                    locations=("S01E03.mkv",),
                    imdb_id="tt0563001",
                    tmdb_id="968589",
                    tvdb_id="295296",
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Aliens of London (1)",
                    locations=("S01E04.mkv",),
                    imdb_id="tt0562985",
                    tmdb_id="968590",
                    tvdb_id="295297",
                ),
                status=WatchedStatus(completed=False, time=240000),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="World War Three (2)",
                    locations=("S01E05.mkv",),
                    imdb_id="tt0563003",
                    tmdb_id="968592",
                    tvdb_id="295298",
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
        ],
    ),
    Series(
        identifiers=MediaIdentifiers(
            title="Monarch: Legacy of Monsters",
            locations=("Monarch - Legacy of Monsters {tvdb-422598} {imdb-tt17220216}",),
            imdb_id="tt17220216",
            tmdb_id="202411",
            tvdb_id="422598",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Secrets and Lies",
                    locations=("S01E03.mkv",),
                    imdb_id="tt21255044",
                    tmdb_id="4661246",
                    tvdb_id="10009418",
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Parallels and Interiors",
                    locations=("S01E04.mkv",),
                    imdb_id="tt21255050",
                    tmdb_id="4712059",
                    tvdb_id="10009419",
                ),
                status=WatchedStatus(completed=False, time=240000),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="The Way Out",
                    locations=("S01E05.mkv",),
                    imdb_id="tt23787572",
                    tmdb_id="4712061",
                    tvdb_id="10009420",
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
        ],
    ),
    Series(
        identifiers=MediaIdentifiers(
            title="My Adventures with Superman",
            locations=("My Adventures with Superman {tvdb-403172} {imdb-tt14681924}",),
            imdb_id="tt14681924",
            tmdb_id="125928",
            tvdb_id="403172",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Adventures of a Normal Man (1)",
                    locations=("S01E01.mkv",),
                    imdb_id="tt15699926",
                    tmdb_id="3070048",
                    tvdb_id="8438181",
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Adventures of a Normal Man (2)",
                    locations=("S01E02.mkv",),
                    imdb_id="tt20413322",
                    tmdb_id="4568681",
                    tvdb_id="9829910",
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="My Interview with Superman",
                    locations=("S01E03.mkv",),
                    imdb_id="tt20413328",
                    tmdb_id="4497012",
                    tvdb_id="9870382",
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
        ],
    ),
]

# ─────────────────────────────────────────────────────────────
# TV Shows Watched list 2

tv_shows_watched_list_2: list[Series] = [
    Series(
        identifiers=MediaIdentifiers(
            title="Doctor Who",
            locations=("Doctor Who (2005) {tvdb-78804} {imdb-tt0436992}",),
            imdb_id="tt0436992",
            tmdb_id="57243",
            tvdb_id="78804",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Rose",
                    locations=("S01E01.mkv",),
                    imdb_id="tt0562992",
                    tvdb_id="295294",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="The End of the World",
                    locations=("S01E02.mkv",),
                    imdb_id="tt0562997",
                    tvdb_id="295295",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=False, time=300670),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="World War Three (2)",
                    locations=("S01E05.mkv",),
                    imdb_id="tt0563003",
                    tvdb_id="295298",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
        ],
    ),
    Series(
        identifiers=MediaIdentifiers(
            title="Monarch: Legacy of Monsters",
            locations=("Monarch - Legacy of Monsters {tvdb-422598} {imdb-tt17220216}",),
            imdb_id="tt17220216",
            tmdb_id="202411",
            tvdb_id="422598",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Aftermath",
                    locations=("S01E01.mkv",),
                    imdb_id="tt20412166",
                    tvdb_id="9959300",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Departure",
                    locations=("S01E02.mkv",),
                    imdb_id="tt22866594",
                    tvdb_id="10009417",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=False, time=300741),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="The Way Out",
                    locations=("S01E05.mkv",),
                    imdb_id="tt23787572",
                    tvdb_id="10009420",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
        ],
    ),
    Series(
        identifiers=MediaIdentifiers(
            title="My Adventures with Superman",
            locations=("My Adventures with Superman {tvdb-403172} {imdb-tt14681924}",),
            imdb_id="tt14681924",
            tmdb_id="125928",
            tvdb_id="403172",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Adventures of a Normal Man (1)",
                    locations=("S01E01.mkv",),
                    imdb_id="tt15699926",
                    tvdb_id="8438181",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Adventures of a Normal Man (2)",
                    locations=("S01E02.mkv",),
                    imdb_id="tt20413322",
                    tvdb_id="9829910",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="My Interview with Superman",
                    locations=("S01E03.mkv",),
                    imdb_id="tt20413328",
                    tvdb_id="9870382",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
        ],
    ),
]

# ─────────────────────────────────────────────────────────────
# Expected TV Shows Watched list 1 (after cleanup)

expected_tv_show_watched_list_1: list[Series] = [
    Series(
        identifiers=MediaIdentifiers(
            title="Doctor Who (2005)",
            locations=("Doctor Who (2005) {tvdb-78804} {imdb-tt0436992}",),
            imdb_id="tt0436992",
            tmdb_id="57243",
            tvdb_id="78804",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="The Unquiet Dead",
                    locations=("S01E03.mkv",),
                    imdb_id="tt0563001",
                    tmdb_id="968589",
                    tvdb_id="295296",
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Aliens of London (1)",
                    locations=("S01E04.mkv",),
                    imdb_id="tt0562985",
                    tmdb_id="968590",
                    tvdb_id="295297",
                ),
                status=WatchedStatus(completed=False, time=240000),
            ),
        ],
    ),
    Series(
        identifiers=MediaIdentifiers(
            title="Monarch: Legacy of Monsters",
            locations=("Monarch - Legacy of Monsters {tvdb-422598} {imdb-tt17220216}",),
            imdb_id="tt17220216",
            tmdb_id="202411",
            tvdb_id="422598",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Secrets and Lies",
                    locations=("S01E03.mkv",),
                    imdb_id="tt21255044",
                    tmdb_id="4661246",
                    tvdb_id="10009418",
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Parallels and Interiors",
                    locations=("S01E04.mkv",),
                    imdb_id="tt21255050",
                    tmdb_id="4712059",
                    tvdb_id="10009419",
                ),
                status=WatchedStatus(completed=False, time=240000),
            ),
        ],
    ),
]

# ─────────────────────────────────────────────────────────────
# Expected TV Shows Watched list 2 (after cleanup)

expected_tv_show_watched_list_2: list[Series] = [
    Series(
        identifiers=MediaIdentifiers(
            title="Doctor Who",
            locations=("Doctor Who (2005) {tvdb-78804} {imdb-tt0436992}",),
            imdb_id="tt0436992",
            tmdb_id="57243",
            tvdb_id="78804",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Rose",
                    locations=("S01E01.mkv",),
                    imdb_id="tt0562992",
                    tvdb_id="295294",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="The End of the World",
                    locations=("S01E02.mkv",),
                    imdb_id="tt0562997",
                    tvdb_id="295295",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=False, time=300670),
            ),
        ],
    ),
    Series(
        identifiers=MediaIdentifiers(
            title="Monarch: Legacy of Monsters",
            locations=("Monarch - Legacy of Monsters {tvdb-422598} {imdb-tt17220216}",),
            imdb_id="tt17220216",
            tmdb_id="202411",
            tvdb_id="422598",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Aftermath",
                    locations=("S01E01.mkv",),
                    imdb_id="tt20412166",
                    tvdb_id="9959300",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Departure",
                    locations=("S01E02.mkv",),
                    imdb_id="tt22866594",
                    tvdb_id="10009417",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=False, time=300741),
            ),
        ],
    ),
]

# ─────────────────────────────────────────────────────────────
# Movies Watched list 1

movies_watched_list_1: list[MediaItem] = [
    MediaItem(
        identifiers=MediaIdentifiers(
            title="Big Buck Bunny",
            locations=("Big Buck Bunny.mkv",),
            imdb_id="tt1254207",
            tmdb_id="10378",
            tvdb_id="12352",
        ),
        status=WatchedStatus(completed=True, time=0),
    ),
    MediaItem(
        identifiers=MediaIdentifiers(
            title="The Family Plan",
            locations=("The Family Plan (2023).mkv",),
            imdb_id="tt16431870",
            tmdb_id="1029575",
            tvdb_id="351194",
        ),
        status=WatchedStatus(completed=True, time=0),
    ),
    MediaItem(
        identifiers=MediaIdentifiers(
            title="Killers of the Flower Moon",
            locations=("Killers of the Flower Moon (2023).mkv",),
            imdb_id="tt5537002",
            tmdb_id="466420",
            tvdb_id="135852",
        ),
        status=WatchedStatus(completed=False, time=240000),
    ),
]

# ─────────────────────────────────────────────────────────────
# Movies Watched list 2

movies_watched_list_2: list[MediaItem] = [
    MediaItem(
        identifiers=MediaIdentifiers(
            title="The Family Plan",
            locations=("The Family Plan (2023).mkv",),
            imdb_id="tt16431870",
            tmdb_id="1029575",
            tvdb_id=None,
        ),
        status=WatchedStatus(completed=True, time=0),
    ),
    MediaItem(
        identifiers=MediaIdentifiers(
            title="Five Nights at Freddy's",
            locations=("Five Nights at Freddy's (2023).mkv",),
            imdb_id="tt4589218",
            tmdb_id="507089",
            tvdb_id=None,
        ),
        status=WatchedStatus(completed=True, time=0),
    ),
    MediaItem(
        identifiers=MediaIdentifiers(
            title="The Hunger Games: The Ballad of Songbirds & Snakes",
            locations=("The Hunger Games The Ballad of Songbirds & Snakes (2023).mkv",),
            imdb_id="tt10545296",
            tmdb_id="695721",
            tvdb_id=None,
        ),
        status=WatchedStatus(completed=False, time=301215),
    ),
]

# ─────────────────────────────────────────────────────────────
# Expected Movies Watched list 1

expected_movie_watched_list_1: list[MediaItem] = [
    MediaItem(
        identifiers=MediaIdentifiers(
            title="Big Buck Bunny",
            locations=("Big Buck Bunny.mkv",),
            imdb_id="tt1254207",
            tmdb_id="10378",
            tvdb_id="12352",
        ),
        status=WatchedStatus(completed=True, time=0),
    ),
    MediaItem(
        identifiers=MediaIdentifiers(
            title="Killers of the Flower Moon",
            locations=("Killers of the Flower Moon (2023).mkv",),
            imdb_id="tt5537002",
            tmdb_id="466420",
            tvdb_id="135852",
        ),
        status=WatchedStatus(completed=False, time=240000),
    ),
]

# ─────────────────────────────────────────────────────────────
# Expected Movies Watched list 2

expected_movie_watched_list_2: list[MediaItem] = [
    MediaItem(
        identifiers=MediaIdentifiers(
            title="Five Nights at Freddy's",
            locations=("Five Nights at Freddy's (2023).mkv",),
            imdb_id="tt4589218",
            tmdb_id="507089",
            tvdb_id=None,
        ),
        status=WatchedStatus(completed=True, time=0),
    ),
    MediaItem(
        identifiers=MediaIdentifiers(
            title="The Hunger Games: The Ballad of Songbirds & Snakes",
            locations=("The Hunger Games The Ballad of Songbirds & Snakes (2023).mkv",),
            imdb_id="tt10545296",
            tmdb_id="695721",
            tvdb_id=None,
        ),
        status=WatchedStatus(completed=False, time=301215),
    ),
]

# ─────────────────────────────────────────────────────────────
# TV Shows 2 Watched list 1 (for testing deletion up to the root)
# Here we use a single Series entry for "Criminal Minds"

tv_shows_2_watched_list_1: list[Series] = [
    Series(
        identifiers=MediaIdentifiers(
            title="Criminal Minds",
            locations=("Criminal Minds",),
            imdb_id="tt0452046",
            tmdb_id="4057",
            tvdb_id="75710",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Extreme Aggressor",
                    locations=(
                        "Criminal Minds S01E01 Extreme Aggressor WEBDL-720p.mkv",
                    ),
                    imdb_id="tt0550489",
                    tmdb_id="282843",
                    tvdb_id="176357",
                ),
                status=WatchedStatus(completed=True, time=0),
            )
        ],
    )
]


def test_simple_cleanup_watched():
    user_watched_list_1: dict[str, UserData] = {
        "user1": UserData(
            libraries={
                "TV Shows": LibraryData(
                    title="TV Shows",
                    movies=[],
                    series=tv_shows_watched_list_1,
                ),
                "Movies": LibraryData(
                    title="Movies",
                    movies=movies_watched_list_1,
                    series=[],
                ),
                "Other Shows": LibraryData(
                    title="Other Shows",
                    movies=[],
                    series=tv_shows_2_watched_list_1,
                ),
            }
        )
    }

    user_watched_list_2: dict[str, UserData] = {
        "user1": UserData(
            libraries={
                "TV Shows": LibraryData(
                    title="TV Shows",
                    movies=[],
                    series=tv_shows_watched_list_2,
                ),
                "Movies": LibraryData(
                    title="Movies",
                    movies=movies_watched_list_2,
                    series=[],
                ),
                "Other Shows": LibraryData(
                    title="Other Shows",
                    movies=[],
                    series=tv_shows_2_watched_list_1,
                ),
            }
        )
    }

    expected_watched_list_1: dict[str, UserData] = {
        "user1": UserData(
            libraries={
                "TV Shows": LibraryData(
                    title="TV Shows",
                    movies=[],
                    series=expected_tv_show_watched_list_1,
                ),
                "Movies": LibraryData(
                    title="Movies",
                    movies=expected_movie_watched_list_1,
                    series=[],
                ),
            }
        )
    }

    expected_watched_list_2: dict[str, UserData] = {
        "user1": UserData(
            libraries={
                "TV Shows": LibraryData(
                    title="TV Shows",
                    movies=[],
                    series=expected_tv_show_watched_list_2,
                ),
                "Movies": LibraryData(
                    title="Movies",
                    movies=expected_movie_watched_list_2,
                    series=[],
                ),
            }
        )
    }

    return_watched_list_1 = cleanup_watched(user_watched_list_1, user_watched_list_2)
    return_watched_list_2 = cleanup_watched(user_watched_list_2, user_watched_list_1)

    assert return_watched_list_1 == expected_watched_list_1
    assert return_watched_list_2 == expected_watched_list_2


# def test_mapping_cleanup_watched():
#    user_watched_list_1 = {
#        "user1": {
#            "TV Shows": tv_shows_watched_list_1,
#            "Movies": movies_watched_list_1,
#            "Other Shows": tv_shows_2_watched_list_1,
#        },
#    }
#    user_watched_list_2 = {
#        "user2": {
#            "Shows": tv_shows_watched_list_2,
#            "Movies": movies_watched_list_2,
#            "Other Shows": tv_shows_2_watched_list_1,
#        }
#    }
#
#    expected_watched_list_1 = {
#        "user1": {
#            "TV Shows": expected_tv_show_watched_list_1,
#            "Movies": expected_movie_watched_list_1,
#        }
#    }
#
#    expected_watched_list_2 = {
#        "user2": {
#            "Shows": expected_tv_show_watched_list_2,
#            "Movies": expected_movie_watched_list_2,
#        }
#    }
#
#    user_mapping = {"user1": "user2"}
#    library_mapping = {"TV Shows": "Shows"}
#
#    return_watched_list_1 = cleanup_watched(
#        user_watched_list_1,
#        user_watched_list_2,
#        user_mapping=user_mapping,
#        library_mapping=library_mapping,
#    )
#    return_watched_list_2 = cleanup_watched(
#        user_watched_list_2,
#        user_watched_list_1,
#        user_mapping=user_mapping,
#        library_mapping=library_mapping,
#    )
#
#    assert return_watched_list_1 == expected_watched_list_1
#    assert return_watched_list_2 == expected_watched_list_2
