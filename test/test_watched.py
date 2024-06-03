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

from src.watched import cleanup_watched, combine_watched_dicts

tv_shows_watched_list_1 = {
    frozenset(
        {
            ("locations", ("Doctor Who (2005) {tvdb-78804} {imdb-tt0436992}",)),
            ("imdb", "tt0436992"),
            ("tmdb", "57243"),
            ("tvdb", "78804"),
            ("title", "Doctor Who (2005)"),
        }
    ): [
        {
            "imdb": "tt0563001",
            "tmdb": "968589",
            "tvdb": "295296",
            "title": "The Unquiet Dead",
            "locations": ("S01E03.mkv",),
            "status": {"completed": True, "time": 0},
        },
        {
            "imdb": "tt0562985",
            "tmdb": "968590",
            "tvdb": "295297",
            "title": "Aliens of London (1)",
            "locations": ("S01E04.mkv",),
            "status": {"completed": False, "time": 240000},
        },
        {
            "imdb": "tt0563003",
            "tmdb": "968592",
            "tvdb": "295298",
            "title": "World War Three (2)",
            "locations": ("S01E05.mkv",),
            "status": {"completed": True, "time": 0},
        },
    ],
    frozenset(
        {
            ("title", "Monarch: Legacy of Monsters"),
            ("imdb", "tt17220216"),
            ("tvdb", "422598"),
            ("tmdb", "202411"),
            (
                "locations",
                ("Monarch - Legacy of Monsters {tvdb-422598} {imdb-tt17220216}",),
            ),
        }
    ): [
        {
            "imdb": "tt21255044",
            "tmdb": "4661246",
            "tvdb": "10009418",
            "title": "Secrets and Lies",
            "locations": ("S01E03.mkv",),
            "status": {"completed": True, "time": 0},
        },
        {
            "imdb": "tt21255050",
            "tmdb": "4712059",
            "tvdb": "10009419",
            "title": "Parallels and Interiors",
            "locations": ("S01E04.mkv",),
            "status": {"completed": False, "time": 240000},
        },
        {
            "imdb": "tt23787572",
            "tmdb": "4712061",
            "tvdb": "10009420",
            "title": "The Way Out",
            "locations": ("S01E05.mkv",),
            "status": {"completed": True, "time": 0},
        },
    ],
    frozenset(
        {
            ("tmdb", "125928"),
            ("imdb", "tt14681924"),
            ("tvdb", "403172"),
            (
                "locations",
                ("My Adventures with Superman {tvdb-403172} {imdb-tt14681924}",),
            ),
            ("title", "My Adventures with Superman"),
        }
    ): [
        {
            "imdb": "tt15699926",
            "tmdb": "3070048",
            "tvdb": "8438181",
            "title": "Adventures of a Normal Man (1)",
            "locations": ("S01E01.mkv",),
            "status": {"completed": True, "time": 0},
        },
        {
            "imdb": "tt20413322",
            "tmdb": "4568681",
            "tvdb": "9829910",
            "title": "Adventures of a Normal Man (2)",
            "locations": ("S01E02.mkv",),
            "status": {"completed": True, "time": 0},
        },
        {
            "imdb": "tt20413328",
            "tmdb": "4497012",
            "tvdb": "9870382",
            "title": "My Interview with Superman",
            "locations": ("S01E03.mkv",),
            "status": {"completed": True, "time": 0},
        },
    ],
}


tv_shows_watched_list_2 = {
    frozenset(
        {
            ("locations", ("Doctor Who (2005) {tvdb-78804} {imdb-tt0436992}",)),
            ("imdb", "tt0436992"),
            ("tmdb", "57243"),
            ("title", "Doctor Who"),
            ("tvdb", "78804"),
            ("tvrage", "3332"),
        }
    ): [
        {
            "tvdb": "295294",
            "imdb": "tt0562992",
            "title": "Rose",
            "locations": ("S01E01.mkv",),
            "status": {"completed": True, "time": 0},
        },
        {
            "tvdb": "295295",
            "imdb": "tt0562997",
            "title": "The End of the World",
            "locations": ("S01E02.mkv",),
            "status": {"completed": False, "time": 300670},
        },
        {
            "tvdb": "295298",
            "imdb": "tt0563003",
            "title": "World War Three (2)",
            "locations": ("S01E05.mkv",),
            "status": {"completed": True, "time": 0},
        },
    ],
    frozenset(
        {
            ("title", "Monarch: Legacy of Monsters"),
            ("imdb", "tt17220216"),
            ("tvdb", "422598"),
            ("tmdb", "202411"),
            (
                "locations",
                ("Monarch - Legacy of Monsters {tvdb-422598} {imdb-tt17220216}",),
            ),
        }
    ): [
        {
            "tvdb": "9959300",
            "imdb": "tt20412166",
            "title": "Aftermath",
            "locations": ("S01E01.mkv",),
            "status": {"completed": True, "time": 0},
        },
        {
            "tvdb": "10009417",
            "imdb": "tt22866594",
            "title": "Departure",
            "locations": ("S01E02.mkv",),
            "status": {"completed": False, "time": 300741},
        },
        {
            "tvdb": "10009420",
            "imdb": "tt23787572",
            "title": "The Way Out",
            "locations": ("S01E05.mkv",),
            "status": {"completed": True, "time": 0},
        },
    ],
    frozenset(
        {
            ("tmdb", "125928"),
            ("imdb", "tt14681924"),
            ("tvdb", "403172"),
            (
                "locations",
                ("My Adventures with Superman {tvdb-403172} {imdb-tt14681924}",),
            ),
            ("title", "My Adventures with Superman"),
        }
    ): [
        {
            "tvdb": "8438181",
            "imdb": "tt15699926",
            "title": "Adventures of a Normal Man (1)",
            "locations": ("S01E01.mkv",),
            "status": {"completed": True, "time": 0},
        },
        {
            "tvdb": "9829910",
            "imdb": "tt20413322",
            "title": "Adventures of a Normal Man (2)",
            "locations": ("S01E02.mkv",),
            "status": {"completed": True, "time": 0},
        },
        {
            "tvdb": "9870382",
            "imdb": "tt20413328",
            "title": "My Interview with Superman",
            "locations": ("S01E03.mkv",),
            "status": {"completed": True, "time": 0},
        },
    ],
}

expected_tv_show_watched_list_1 = {
    frozenset(
        {
            ("locations", ("Doctor Who (2005) {tvdb-78804} {imdb-tt0436992}",)),
            ("imdb", "tt0436992"),
            ("tmdb", "57243"),
            ("tvdb", "78804"),
            ("title", "Doctor Who (2005)"),
        }
    ): [
        {
            "imdb": "tt0563001",
            "tmdb": "968589",
            "tvdb": "295296",
            "title": "The Unquiet Dead",
            "locations": ("S01E03.mkv",),
            "status": {"completed": True, "time": 0},
        },
        {
            "imdb": "tt0562985",
            "tmdb": "968590",
            "tvdb": "295297",
            "title": "Aliens of London (1)",
            "locations": ("S01E04.mkv",),
            "status": {"completed": False, "time": 240000},
        },
    ],
    frozenset(
        {
            ("title", "Monarch: Legacy of Monsters"),
            ("imdb", "tt17220216"),
            ("tvdb", "422598"),
            ("tmdb", "202411"),
            (
                "locations",
                ("Monarch - Legacy of Monsters {tvdb-422598} {imdb-tt17220216}",),
            ),
        }
    ): [
        {
            "imdb": "tt21255044",
            "tmdb": "4661246",
            "tvdb": "10009418",
            "title": "Secrets and Lies",
            "locations": ("S01E03.mkv",),
            "status": {"completed": True, "time": 0},
        },
        {
            "imdb": "tt21255050",
            "tmdb": "4712059",
            "tvdb": "10009419",
            "title": "Parallels and Interiors",
            "locations": ("S01E04.mkv",),
            "status": {"completed": False, "time": 240000},
        },
    ],
}

expected_tv_show_watched_list_2 = {
    frozenset(
        {
            ("locations", ("Doctor Who (2005) {tvdb-78804} {imdb-tt0436992}",)),
            ("imdb", "tt0436992"),
            ("tmdb", "57243"),
            ("title", "Doctor Who"),
            ("tvdb", "78804"),
            ("tvrage", "3332"),
        }
    ): [
        {
            "tvdb": "295294",
            "imdb": "tt0562992",
            "title": "Rose",
            "locations": ("S01E01.mkv",),
            "status": {"completed": True, "time": 0},
        },
        {
            "tvdb": "295295",
            "imdb": "tt0562997",
            "title": "The End of the World",
            "locations": ("S01E02.mkv",),
            "status": {"completed": False, "time": 300670},
        },
    ],
    frozenset(
        {
            ("title", "Monarch: Legacy of Monsters"),
            ("imdb", "tt17220216"),
            ("tvdb", "422598"),
            ("tmdb", "202411"),
            (
                "locations",
                ("Monarch - Legacy of Monsters {tvdb-422598} {imdb-tt17220216}",),
            ),
        }
    ): [
        {
            "tvdb": "9959300",
            "imdb": "tt20412166",
            "title": "Aftermath",
            "locations": ("S01E01.mkv",),
            "status": {"completed": True, "time": 0},
        },
        {
            "tvdb": "10009417",
            "imdb": "tt22866594",
            "title": "Departure",
            "locations": ("S01E02.mkv",),
            "status": {"completed": False, "time": 300741},
        },
    ],
}

movies_watched_list_1 = [
    {
        "imdb": "tt1254207",
        "tmdb": "10378",
        "tvdb": "12352",
        "title": "Big Buck Bunny",
        "locations": ("Big Buck Bunny.mkv",),
        "status": {"completed": True, "time": 0},
    },
    {
        "imdb": "tt16431870",
        "tmdb": "1029575",
        "tvdb": "351194",
        "title": "The Family Plan",
        "locations": ("The Family Plan (2023).mkv",),
        "status": {"completed": True, "time": 0},
    },
    {
        "imdb": "tt5537002",
        "tmdb": "466420",
        "tvdb": "135852",
        "title": "Killers of the Flower Moon",
        "locations": ("Killers of the Flower Moon (2023).mkv",),
        "status": {"completed": False, "time": 240000},
    },
]

movies_watched_list_2 = [
    {
        "imdb": "tt16431870",
        "tmdb": "1029575",
        "title": "The Family Plan",
        "locations": ("The Family Plan (2023).mkv",),
        "status": {"completed": True, "time": 0},
    },
    {
        "imdb": "tt4589218",
        "tmdb": "507089",
        "title": "Five Nights at Freddy's",
        "locations": ("Five Nights at Freddy's (2023).mkv",),
        "status": {"completed": True, "time": 0},
    },
    {
        "imdb": "tt10545296",
        "tmdb": "695721",
        "tmdbcollection": "131635",
        "title": "The Hunger Games: The Ballad of Songbirds & Snakes",
        "locations": ("The Hunger Games The Ballad of Songbirds & Snakes (2023).mkv",),
        "status": {"completed": False, "time": 301215},
    },
]


expected_movie_watched_list_1 = [
    {
        "imdb": "tt1254207",
        "tmdb": "10378",
        "tvdb": "12352",
        "title": "Big Buck Bunny",
        "locations": ("Big Buck Bunny.mkv",),
        "status": {"completed": True, "time": 0},
    },
    {
        "imdb": "tt5537002",
        "tmdb": "466420",
        "tvdb": "135852",
        "title": "Killers of the Flower Moon",
        "locations": ("Killers of the Flower Moon (2023).mkv",),
        "status": {"completed": False, "time": 240000},
    },
]

expected_movie_watched_list_2 = [
    {
        "imdb": "tt4589218",
        "tmdb": "507089",
        "title": "Five Nights at Freddy's",
        "locations": ("Five Nights at Freddy's (2023).mkv",),
        "status": {"completed": True, "time": 0},
    },
    {
        "imdb": "tt10545296",
        "tmdb": "695721",
        "tmdbcollection": "131635",
        "title": "The Hunger Games: The Ballad of Songbirds & Snakes",
        "locations": ("The Hunger Games The Ballad of Songbirds & Snakes (2023).mkv",),
        "status": {"completed": False, "time": 301215},
    },
]

# Test to see if objects get deleted all the way up to the root.
tv_shows_2_watched_list_1 = {
    frozenset(
        {
            ("tvdb", "75710"),
            ("title", "Criminal Minds"),
            ("imdb", "tt0452046"),
            ("locations", ("Criminal Minds",)),
            ("tmdb", "4057"),
        }
    ): [
        {
            "imdb": "tt0550489",
            "tmdb": "282843",
            "tvdb": "176357",
            "title": "Extreme Aggressor",
            "locations": ("Criminal Minds S01E01 Extreme Aggressor WEBDL-720p.mkv",),
            "status": {"completed": True, "time": 0},
        },
    ]
}


def test_simple_cleanup_watched():
    user_watched_list_1 = {
        "user1": {
            "TV Shows": tv_shows_watched_list_1,
            "Movies": movies_watched_list_1,
            "Other Shows": tv_shows_2_watched_list_1,
        },
    }
    user_watched_list_2 = {
        "user1": {
            "TV Shows": tv_shows_watched_list_2,
            "Movies": movies_watched_list_2,
            "Other Shows": tv_shows_2_watched_list_1,
        }
    }

    expected_watched_list_1 = {
        "user1": {
            "TV Shows": expected_tv_show_watched_list_1,
            "Movies": expected_movie_watched_list_1,
        }
    }

    expected_watched_list_2 = {
        "user1": {
            "TV Shows": expected_tv_show_watched_list_2,
            "Movies": expected_movie_watched_list_2,
        }
    }

    return_watched_list_1 = cleanup_watched(user_watched_list_1, user_watched_list_2)
    return_watched_list_2 = cleanup_watched(user_watched_list_2, user_watched_list_1)

    assert return_watched_list_1 == expected_watched_list_1
    assert return_watched_list_2 == expected_watched_list_2


def test_mapping_cleanup_watched():
    user_watched_list_1 = {
        "user1": {
            "TV Shows": tv_shows_watched_list_1,
            "Movies": movies_watched_list_1,
            "Other Shows": tv_shows_2_watched_list_1,
        },
    }
    user_watched_list_2 = {
        "user2": {
            "Shows": tv_shows_watched_list_2,
            "Movies": movies_watched_list_2,
            "Other Shows": tv_shows_2_watched_list_1,
        }
    }

    expected_watched_list_1 = {
        "user1": {
            "TV Shows": expected_tv_show_watched_list_1,
            "Movies": expected_movie_watched_list_1,
        }
    }

    expected_watched_list_2 = {
        "user2": {
            "Shows": expected_tv_show_watched_list_2,
            "Movies": expected_movie_watched_list_2,
        }
    }

    user_mapping = {"user1": "user2"}
    library_mapping = {"TV Shows": "Shows"}

    return_watched_list_1 = cleanup_watched(
        user_watched_list_1,
        user_watched_list_2,
        user_mapping=user_mapping,
        library_mapping=library_mapping,
    )
    return_watched_list_2 = cleanup_watched(
        user_watched_list_2,
        user_watched_list_1,
        user_mapping=user_mapping,
        library_mapping=library_mapping,
    )

    assert return_watched_list_1 == expected_watched_list_1
    assert return_watched_list_2 == expected_watched_list_2


def test_combine_watched_dicts():
    input_watched = [
        {
            "test3": {
                "Anime Movies": [
                    {
                        "title": "Ponyo",
                        "tmdb": "12429",
                        "imdb": "tt0876563",
                        "locations": ("Ponyo (2008) Bluray-1080p.mkv",),
                        "status": {"completed": True, "time": 0},
                    },
                    {
                        "title": "Spirited Away",
                        "tmdb": "129",
                        "imdb": "tt0245429",
                        "locations": ("Spirited Away (2001) Bluray-1080p.mkv",),
                        "status": {"completed": True, "time": 0},
                    },
                    {
                        "title": "Castle in the Sky",
                        "tmdb": "10515",
                        "imdb": "tt0092067",
                        "locations": ("Castle in the Sky (1986) Bluray-1080p.mkv",),
                        "status": {"completed": True, "time": 0},
                    },
                ]
            }
        },
        {"test3": {"Anime Shows": {}}},
        {"test3": {"Cartoon Shows": {}}},
        {
            "test3": {
                "Shows": {
                    frozenset(
                        {
                            ("tmdb", "64464"),
                            ("tvdb", "301824"),
                            ("tvrage", "45210"),
                            ("title", "11.22.63"),
                            ("locations", ("11.22.63",)),
                            ("imdb", "tt2879552"),
                        }
                    ): [
                        {
                            "imdb": "tt4460418",
                            "title": "The Rabbit Hole",
                            "locations": (
                                "11.22.63 S01E01 The Rabbit Hole Bluray-1080p.mkv",
                            ),
                            "status": {"completed": True, "time": 0},
                        }
                    ]
                }
            }
        },
        {"test3": {"Subbed Anime": {}}},
    ]
    expected = {
        "test3": {
            "Anime Movies": [
                {
                    "title": "Ponyo",
                    "tmdb": "12429",
                    "imdb": "tt0876563",
                    "locations": ("Ponyo (2008) Bluray-1080p.mkv",),
                    "status": {"completed": True, "time": 0},
                },
                {
                    "title": "Spirited Away",
                    "tmdb": "129",
                    "imdb": "tt0245429",
                    "locations": ("Spirited Away (2001) Bluray-1080p.mkv",),
                    "status": {"completed": True, "time": 0},
                },
                {
                    "title": "Castle in the Sky",
                    "tmdb": "10515",
                    "imdb": "tt0092067",
                    "locations": ("Castle in the Sky (1986) Bluray-1080p.mkv",),
                    "status": {"completed": True, "time": 0},
                },
            ],
            "Anime Shows": {},
            "Cartoon Shows": {},
            "Shows": {
                frozenset(
                    {
                        ("tmdb", "64464"),
                        ("tvdb", "301824"),
                        ("tvrage", "45210"),
                        ("title", "11.22.63"),
                        ("locations", ("11.22.63",)),
                        ("imdb", "tt2879552"),
                    }
                ): [
                    {
                        "imdb": "tt4460418",
                        "title": "The Rabbit Hole",
                        "locations": (
                            "11.22.63 S01E01 The Rabbit Hole Bluray-1080p.mkv",
                        ),
                        "status": {"completed": True, "time": 0},
                    }
                ]
            },
            "Subbed Anime": {},
        }
    }

    assert combine_watched_dicts(input_watched) == expected
