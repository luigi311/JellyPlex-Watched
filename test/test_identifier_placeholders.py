from src.watched import MediaIdentifiers, check_same_identifiers, media_identifier_keys


def test_placeholder_provider_ids_are_not_identity_evidence():
    first = MediaIdentifiers(title="Episode 1", locations=("Show - S01E01.mkv",), tvdb_id="0", imdb_id="tt1")
    second = MediaIdentifiers(title="Episode 2", locations=("Show - S01E02.mkv",), tvdb_id="0", imdb_id="tt2")

    assert ("tvdb", "0") not in media_identifier_keys(first)
    assert not check_same_identifiers(first, second)


def test_minus_one_placeholder_is_ignored():
    item = MediaIdentifiers(title="Movie", tmdb_id="-1", imdb_id="tt3")

    assert media_identifier_keys(item) == frozenset({("imdb", "tt3")})


def test_real_provider_ids_still_match():
    first = MediaIdentifiers(title="Episode", tvdb_id="8588193")
    second = MediaIdentifiers(title="Episode (renamed)", tvdb_id="8588193")

    assert check_same_identifiers(first, second)
