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

from src.functions import (
    search_mapping,
)

from src.library import (
    check_skip_logic,
    check_blacklist_logic,
    check_whitelist_logic,
)

blacklist_library = ["TV Shows"]
whitelist_library = ["Movies"]
blacklist_library_type = ["episodes"]
whitelist_library_type = ["movies"]
library_mapping = {"Shows": "TV Shows", "Movie": "Movies"}

show_list = {
    frozenset(
        {
            ("locations", ("The Last of Us",)),
            ("tmdb", "100088"),
            ("imdb", "tt3581920"),
            ("tvdb", "392256"),
            ("title", "The Last of Us"),
        }
    ): [
        {
            "imdb": "tt11957006",
            "tmdb": "2181581",
            "tvdb": "8444132",
            "locations": (
                (
                    "The Last of Us - S01E01 - When You're Lost in the Darkness WEBDL-1080p.mkv",
                )
            ),
            "status": {"completed": True, "time": 0},
        }
    ]
}
movie_list = [
    {
        "title": "Coco",
        "imdb": "tt2380307",
        "tmdb": "354912",
        "locations": [("Coco (2017) Remux-2160p.mkv", "Coco (2017) Remux-1080p.mkv")],
        "status": {"completed": True, "time": 0},
    }
]

show_titles = {
    "imdb": ["tt3581920"],
    "locations": [("The Last of Us",)],
    "tmdb": ["100088"],
    "tvdb": ["392256"],
}
episode_titles = {
    "imdb": ["tt11957006"],
    "locations": [
        ("The Last of Us - S01E01 - When You're Lost in the Darkness WEBDL-1080p.mkv",)
    ],
    "tmdb": ["2181581"],
    "tvdb": ["8444132"],
    "completed": [True],
    "time": [0],
    "show": [
        {
            "imdb": "tt3581920",
            "locations": ("The Last of Us",),
            "title": "The Last of Us",
            "tmdb": "100088",
            "tvdb": "392256",
        }
    ],
}
movie_titles = {
    "imdb": ["tt2380307"],
    "locations": [
        [
            (
                "Coco (2017) Remux-2160p.mkv",
                "Coco (2017) Remux-1080p.mkv",
            )
        ]
    ],
    "title": ["coco"],
    "tmdb": ["354912"],
    "completed": [True],
    "time": [0],
}


def test_check_skip_logic():
    # Failes
    library_title = "Test"
    library_type = "movies"
    skip_reason = check_skip_logic(
        library_title,
        library_type,
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        library_mapping,
    )

    assert skip_reason == "Test is not in whitelist_library"

    library_title = "Shows"
    library_type = "episodes"
    skip_reason = check_skip_logic(
        library_title,
        library_type,
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        library_mapping,
    )

    assert (
        skip_reason
        == "episodes is in blacklist_library_type and TV Shows is in blacklist_library and "
        + "episodes is not in whitelist_library_type and Shows is not in whitelist_library"
    )

    # Passes
    library_title = "Movie"
    library_type = "movies"
    skip_reason = check_skip_logic(
        library_title,
        library_type,
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        library_mapping,
    )

    assert skip_reason is None


def test_check_blacklist_logic():
    # Fails
    library_title = "Shows"
    library_type = "episodes"
    library_other = search_mapping(library_mapping, library_title)
    skip_reason = check_blacklist_logic(
        library_title,
        library_type,
        blacklist_library,
        blacklist_library_type,
        library_other,
    )

    assert (
        skip_reason
        == "episodes is in blacklist_library_type and TV Shows is in blacklist_library"
    )

    library_title = "TV Shows"
    library_type = "episodes"
    library_other = search_mapping(library_mapping, library_title)
    skip_reason = check_blacklist_logic(
        library_title,
        library_type,
        blacklist_library,
        blacklist_library_type,
        library_other,
    )

    assert (
        skip_reason
        == "episodes is in blacklist_library_type and TV Shows is in blacklist_library"
    )

    # Passes
    library_title = "Movie"
    library_type = "movies"
    library_other = search_mapping(library_mapping, library_title)
    skip_reason = check_blacklist_logic(
        library_title,
        library_type,
        blacklist_library,
        blacklist_library_type,
        library_other,
    )

    assert skip_reason is None

    library_title = "Movies"
    library_type = "movies"
    library_other = search_mapping(library_mapping, library_title)
    skip_reason = check_blacklist_logic(
        library_title,
        library_type,
        blacklist_library,
        blacklist_library_type,
        library_other,
    )

    assert skip_reason is None


def test_check_whitelist_logic():
    # Fails
    library_title = "Shows"
    library_type = "episodes"
    library_other = search_mapping(library_mapping, library_title)
    skip_reason = check_whitelist_logic(
        library_title,
        library_type,
        whitelist_library,
        whitelist_library_type,
        library_other,
    )

    assert (
        skip_reason
        == "episodes is not in whitelist_library_type and Shows is not in whitelist_library"
    )

    library_title = "TV Shows"
    library_type = "episodes"
    library_other = search_mapping(library_mapping, library_title)
    skip_reason = check_whitelist_logic(
        library_title,
        library_type,
        whitelist_library,
        whitelist_library_type,
        library_other,
    )

    assert (
        skip_reason
        == "episodes is not in whitelist_library_type and TV Shows is not in whitelist_library"
    )

    # Passes
    library_title = "Movie"
    library_type = "movies"
    library_other = search_mapping(library_mapping, library_title)
    skip_reason = check_whitelist_logic(
        library_title,
        library_type,
        whitelist_library,
        whitelist_library_type,
        library_other,
    )

    assert skip_reason is None

    library_title = "Movies"
    library_type = "movies"
    library_other = search_mapping(library_mapping, library_title)
    skip_reason = check_whitelist_logic(
        library_title,
        library_type,
        whitelist_library,
        whitelist_library_type,
        library_other,
    )

    assert skip_reason is None
