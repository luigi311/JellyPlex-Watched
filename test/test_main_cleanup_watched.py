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

from src.main import cleanup_watched

tv_shows_watched_list_1 = {
    frozenset({("tvdb", "75710"), ("title", "Criminal Minds"), ("imdb", "tt0452046"), ("locations", ("Criminal Minds",)), ("tmdb", "4057")}): {
        "Season 1": [
            {'imdb': 'tt0550489', 'tmdb': '282843', 'tvdb': '176357', 'locations': ('Criminal Minds S01E01 Extreme Aggressor WEBDL-720p.mkv',)},
            {'imdb': 'tt0550487', 'tmdb': '282861', 'tvdb': '300385', 'locations': ('Criminal Minds S01E02 Compulsion WEBDL-720p.mkv',)}
        ]
    }
}

movies_watched_list_1 = [
    {"imdb":"tt2380307", "tmdb":"354912", 'title': 'Coco', 'locations': ('Coco (2017) Remux-1080p.mkv',)},
    {"tmdbcollection":"448150", "imdb":"tt1431045", "tmdb":"293660", 'title': 'Deadpool', 'locations': ('Deadpool (2016) Remux-1080p.mkv',)},
]

tv_shows_watched_list_2 = {
    frozenset({("tvdb", "75710"), ("title", "Criminal Minds"), ("imdb", "tt0452046"), ("locations", ("Criminal Minds",)), ("tmdb", "4057")}): {
        "Season 1": [
            {'imdb': 'tt0550487', 'tmdb': '282861', 'tvdb': '300385', 'locations': ('Criminal Minds S01E02 Compulsion WEBDL-720p.mkv',)},
            {'imdb': 'tt0550498', 'tmdb': '282865', 'tvdb': '300474', 'locations': ("Criminal Minds S01E03 Won't Get Fooled Again WEBDL-720p.mkv",)}
        ]
    }
}

movies_watched_list_2 = [
    {"imdb":"tt2380307", "tmdb":"354912", 'title': 'Coco', 'locations': ('Coco (2017) Remux-1080p.mkv',)},
    {'imdb': 'tt0384793', 'tmdb': '9788', 'tvdb': '9103', 'title': 'Accepted', 'locations': ('Accepted (2006) Remux-1080p.mkv',)}
]

# Test to see if objects get deleted all the way up to the root.
tv_shows_2_watched_list_1 = {
    frozenset({("tvdb", "75710"), ("title", "Criminal Minds"), ("imdb", "tt0452046"), ("locations", ("Criminal Minds",)), ("tmdb", "4057")}): {
        "Season 1": [
            {'imdb': 'tt0550489', 'tmdb': '282843', 'tvdb': '176357', 'locations': ('Criminal Minds S01E01 Extreme Aggressor WEBDL-720p.mkv',)},
        ]
    }
}

expected_tv_show_watched_list_1 = {
    frozenset({("tvdb", "75710"), ("title", "Criminal Minds"), ("imdb", "tt0452046"), ("locations", ("Criminal Minds",)), ("tmdb", "4057")}): {
        "Season 1": [
            {'imdb': 'tt0550489', 'tmdb': '282843', 'tvdb': '176357', 'locations': ('Criminal Minds S01E01 Extreme Aggressor WEBDL-720p.mkv',)}
        ]
    }
}

expected_movie_watched_list_1 = [
    {"tmdbcollection":"448150", "imdb":"tt1431045", "tmdb":"293660", 'title': 'Deadpool', 'locations': ('Deadpool (2016) Remux-1080p.mkv',)}
]

expected_tv_show_watched_list_2 = {
    frozenset({("tvdb", "75710"), ("title", "Criminal Minds"), ("imdb", "tt0452046"), ("locations", ("Criminal Minds",)), ("tmdb", "4057")}): {
        "Season 1": [
            {'imdb': 'tt0550498', 'tmdb': '282865', 'tvdb': '300474', 'locations': ("Criminal Minds S01E03 Won't Get Fooled Again WEBDL-720p.mkv",)}
        ]
    }
}

expected_movie_watched_list_2 = [
    {'imdb': 'tt0384793', 'tmdb': '9788', 'tvdb': '9103', 'title': 'Accepted', 'locations': ('Accepted (2006) Remux-1080p.mkv',)}
]


def test_simple_cleanup_watched():
    user_watched_list_1 = {
        "user1": {
            "TV Shows": tv_shows_watched_list_1,
            "Movies": movies_watched_list_1,
            "Other Shows": tv_shows_2_watched_list_1
        },
    }
    user_watched_list_2 = {
        "user1": {
            "TV Shows": tv_shows_watched_list_2,
            "Movies": movies_watched_list_2,
            "Other Shows": tv_shows_2_watched_list_1
        }
    }

    expected_watched_list_1 = {
        "user1": {
            "TV Shows": expected_tv_show_watched_list_1
            , "Movies": expected_movie_watched_list_1
        }
    }

    expected_watched_list_2 = {
        "user1": {
            "TV Shows": expected_tv_show_watched_list_2
            , "Movies": expected_movie_watched_list_2
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
            "Other Shows": tv_shows_2_watched_list_1
        },
    }
    user_watched_list_2 = {
        "user2": {
            "Shows": tv_shows_watched_list_2,
            "Movies": movies_watched_list_2,
            "Other Shows": tv_shows_2_watched_list_1
        }
    }

    expected_watched_list_1 = {
        "user1": {
            "TV Shows": expected_tv_show_watched_list_1
            , "Movies": expected_movie_watched_list_1
        }
    }

    expected_watched_list_2 = {
        "user2": {
            "Shows": expected_tv_show_watched_list_2
            , "Movies": expected_movie_watched_list_2
        }
    }

    user_mapping = { "user1": "user2" }
    library_mapping = { "TV Shows": "Shows" }

    return_watched_list_1 = cleanup_watched(user_watched_list_1, user_watched_list_2, user_mapping=user_mapping, library_mapping=library_mapping)
    return_watched_list_2 = cleanup_watched(user_watched_list_2, user_watched_list_1, user_mapping=user_mapping, library_mapping=library_mapping)
    
    assert return_watched_list_1 == expected_watched_list_1
    assert return_watched_list_2 == expected_watched_list_2
