import os
import sys

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

# Add the parent directory to sys.path so we can import from src/
current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
sys.path.append(parent)

from src.settings import (
    AppSettings,
    EmbySettings,
    JellyfinSettings,
    LibraryAlias,
    LibraryMapping,
    LibrarySyncRule,
    PlexSettings,
    SyncRule,
    UserAlias,
    UserMapping,
    _dump_for_yaml,
)


class _IsolatedAppSettings(AppSettings):
    """
    AppSettings that ignores all external configuration sources (env vars,
    .env, legacy .env, config.yaml) so tests depend only on the kwargs
    passed in.
    """

    model_config = SettingsConfigDict(
        yaml_file=None,
        yaml_file_encoding=None,
        nested_model_default_partial_update=True,
        extra="forbid",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (init_settings,)


def _settings(**overrides) -> AppSettings:
    """Build a minimal two-server AppSettings for testing."""
    base = {
        "plex": [
            {
                "name": "plex-main",
                "baseurl": "http://plex",
                "token": "x",
                "sync_to": ["jellyfin-main"],
            }
        ],
        "jellyfin": [
            {
                "name": "jellyfin-main",
                "baseurl": "http://jellyfin",
                "token": "x",
                "sync_to": ["plex-main"],
            }
        ],
    }
    base.update(overrides)
    return _IsolatedAppSettings(**base)


# ---------------------------------------------------------------------------
# Server model tests
# ---------------------------------------------------------------------------


def test_plex_settings_with_token():
    s = PlexSettings(name="plex-1", baseurl="http://plex", token="mytoken")
    assert s.token is not None
    assert s.token.get_secret_value() == "mytoken"


def test_plex_settings_with_userpass():
    s = PlexSettings(
        name="plex-1",
        baseurl="http://plex",
        username="user",
        password="pass",
        servername="MyPlex",
    )
    assert s.username == "user"
    assert s.password.get_secret_value() == "pass"


def test_plex_settings_no_auth_raises():
    with pytest.raises(ValidationError, match="needs either a 'token'"):
        PlexSettings(name="plex-1", baseurl="http://plex")


def test_plex_settings_baseurl_trailing_slash_stripped():
    s = PlexSettings(name="plex-1", baseurl="http://plex/", token="t")
    assert s.baseurl == "http://plex"


def test_jellyfin_settings_requires_token():
    s = JellyfinSettings(name="jf", baseurl="http://jellyfin", token="mytoken")
    assert s.token.get_secret_value() == "mytoken"


def test_emby_settings_requires_token():
    s = EmbySettings(name="emby", baseurl="http://emby", token="mytoken")
    assert s.token.get_secret_value() == "mytoken"


def test_server_baseurl_trailing_slash_stripped():
    s = JellyfinSettings(name="jf", baseurl="http://jellyfin/path/", token="t")
    assert s.baseurl == "http://jellyfin/path"


# ---------------------------------------------------------------------------
# AppSettings validation: duplicate server names
# ---------------------------------------------------------------------------


def test_duplicate_server_names_raises():
    with pytest.raises(ValidationError, match="Duplicate server names"):
        _IsolatedAppSettings(
            plex=[
                {"name": "server", "baseurl": "http://a", "token": "x"},
                {"name": "server", "baseurl": "http://b", "token": "y"},
            ]
        )


def test_duplicate_server_names_across_types_raises():
    with pytest.raises(ValidationError, match="Duplicate server names"):
        _IsolatedAppSettings(
            plex=[{"name": "shared", "baseurl": "http://a", "token": "x"}],
            jellyfin=[{"name": "shared", "baseurl": "http://b", "token": "y"}],
        )


# ---------------------------------------------------------------------------
# AppSettings validation: sync_to references
# ---------------------------------------------------------------------------


def test_sync_to_unknown_server_raises():
    with pytest.raises(ValidationError, match="not a configured server"):
        _IsolatedAppSettings(
            plex=[
                {
                    "name": "plex-main",
                    "baseurl": "http://plex",
                    "token": "x",
                    "sync_to": ["nonexistent"],
                }
            ]
        )


def test_sync_to_self_raises():
    with pytest.raises(ValidationError, match="cannot sync_to itself"):
        _IsolatedAppSettings(
            plex=[
                {
                    "name": "plex-main",
                    "baseurl": "http://plex",
                    "token": "x",
                    "sync_to": ["plex-main"],
                }
            ]
        )


def test_sync_to_duplicate_entry_raises():
    with pytest.raises(ValidationError, match="duplicate sync_to entry"):
        _IsolatedAppSettings(
            plex=[
                {
                    "name": "plex-main",
                    "baseurl": "http://plex",
                    "token": "x",
                    "sync_to": ["jf", "jf"],
                }
            ],
            jellyfin=[{"name": "jf", "baseurl": "http://jf", "token": "y"}],
        )


# ---------------------------------------------------------------------------
# AppSettings validation: user_mappings aliases
# ---------------------------------------------------------------------------


def test_user_alias_unknown_server_raises():
    with pytest.raises(ValidationError, match="references unknown server"):
        _IsolatedAppSettings(
            plex=[{"name": "plex-main", "baseurl": "http://plex", "token": "x"}],
            user_mappings=[
                {
                    "canonical": "user1",
                    "aliases": [
                        {"server": "nonexistent", "username": "user1"},
                    ],
                }
            ],
        )


def test_user_alias_duplicate_within_canonical_raises():
    with pytest.raises(ValidationError, match="duplicate alias"):
        _IsolatedAppSettings(
            plex=[{"name": "plex-main", "baseurl": "http://plex", "token": "x"}],
            user_mappings=[
                {
                    "canonical": "user1",
                    "aliases": [
                        {"server": "plex-main", "username": "user1"},
                        {"server": "plex-main", "username": "user1"},
                    ],
                }
            ],
        )


def test_user_alias_across_canonicals_raises():
    with pytest.raises(ValidationError, match="claimed by both"):
        _IsolatedAppSettings(
            plex=[{"name": "plex-main", "baseurl": "http://plex", "token": "x"}],
            user_mappings=[
                {
                    "canonical": "user1",
                    "aliases": [{"server": "plex-main", "username": "shared"}],
                },
                {
                    "canonical": "user2",
                    "aliases": [{"server": "plex-main", "username": "shared"}],
                },
            ],
        )


def test_duplicate_user_canonicals_raises():
    with pytest.raises(ValidationError, match="Duplicate user_mappings.canonical"):
        _IsolatedAppSettings(
            plex=[{"name": "plex-main", "baseurl": "http://plex", "token": "x"}],
            user_mappings=[
                {
                    "canonical": "user1",
                    "aliases": [{"server": "plex-main", "username": "a"}],
                },
                {
                    "canonical": "user1",
                    "aliases": [{"server": "plex-main", "username": "b"}],
                },
            ],
        )


# ---------------------------------------------------------------------------
# AppSettings validation: library_mappings aliases
# ---------------------------------------------------------------------------


def test_library_alias_unknown_server_raises():
    with pytest.raises(ValidationError, match="references unknown server"):
        _IsolatedAppSettings(
            plex=[{"name": "plex-main", "baseurl": "http://plex", "token": "x"}],
            library_mappings=[
                {
                    "canonical": "Movies",
                    "aliases": [
                        {"server": "nonexistent", "library": "Movies"},
                    ],
                }
            ],
        )


def test_library_alias_across_canonicals_raises():
    with pytest.raises(ValidationError, match="claimed by both"):
        _IsolatedAppSettings(
            plex=[{"name": "plex-main", "baseurl": "http://plex", "token": "x"}],
            library_mappings=[
                {
                    "canonical": "lib1",
                    "aliases": [{"server": "plex-main", "library": "shared"}],
                },
                {
                    "canonical": "lib2",
                    "aliases": [{"server": "plex-main", "library": "shared"}],
                },
            ],
        )


def test_duplicate_library_canonicals_raises():
    with pytest.raises(ValidationError, match="Duplicate library_mappings.canonical"):
        _IsolatedAppSettings(
            plex=[{"name": "plex-main", "baseurl": "http://plex", "token": "x"}],
            library_mappings=[
                {
                    "canonical": "Movies",
                    "aliases": [{"server": "plex-main", "library": "Movies"}],
                },
                {
                    "canonical": "Movies",
                    "aliases": [{"server": "plex-main", "library": "Other Movies"}],
                },
            ],
        )


# ---------------------------------------------------------------------------
# AppSettings validation: sync_rules
# ---------------------------------------------------------------------------


def test_sync_rules_unknown_from_server_raises():
    with pytest.raises(ValidationError, match="is unknown"):
        _IsolatedAppSettings(
            plex=[{"name": "plex-main", "baseurl": "http://plex", "token": "x"}],
            sync_rules=[
                {"users": ["user1"], "from": "nonexistent", "to": "plex-main"}
            ],
        )


def test_sync_rules_unknown_to_server_raises():
    with pytest.raises(ValidationError, match="is unknown"):
        _IsolatedAppSettings(
            plex=[{"name": "plex-main", "baseurl": "http://plex", "token": "x"}],
            sync_rules=[
                {"users": ["user1"], "from": "plex-main", "to": "nonexistent"}
            ],
        )


def test_sync_rules_from_equals_to_raises():
    with pytest.raises(ValidationError, match="from == to"):
        _IsolatedAppSettings(
            plex=[{"name": "plex-main", "baseurl": "http://plex", "token": "x"}],
            sync_rules=[
                {"users": ["user1"], "from": "plex-main", "to": "plex-main"}
            ],
        )


def test_sync_rules_user_missing_from_alias_raises():
    """A canonical user in sync_rules must have an alias on the 'from' server."""
    with pytest.raises(ValidationError, match="has no alias on server"):
        _IsolatedAppSettings(
            plex=[{"name": "plex-main", "baseurl": "http://plex", "token": "x"}],
            jellyfin=[{"name": "jf-main", "baseurl": "http://jf", "token": "y"}],
            user_mappings=[
                {
                    "canonical": "user1",
                    "aliases": [
                        # Only on jf-main, not on plex-main
                        {"server": "jf-main", "username": "user1"},
                    ],
                }
            ],
            sync_rules=[
                # user1 has no alias on plex-main (from), should fail
                {"users": ["user1"], "from": "plex-main", "to": "jf-main"}
            ],
        )


def test_sync_rules_duplicate_triple_raises():
    with pytest.raises(ValidationError, match="duplicate coverage"):
        _IsolatedAppSettings(
            plex=[{"name": "plex-main", "baseurl": "http://plex", "token": "x"}],
            jellyfin=[{"name": "jf-main", "baseurl": "http://jf", "token": "y"}],
            sync_rules=[
                {"users": ["u"], "from": "plex-main", "to": "jf-main"},
                {"users": ["u"], "from": "plex-main", "to": "jf-main"},
            ],
        )


# ---------------------------------------------------------------------------
# AppSettings validation: library_sync_rules
# ---------------------------------------------------------------------------


def test_library_sync_rules_unknown_server_raises():
    with pytest.raises(ValidationError, match="is unknown"):
        _IsolatedAppSettings(
            plex=[{"name": "plex-main", "baseurl": "http://plex", "token": "x"}],
            library_sync_rules=[
                {"libraries": ["Movies"], "from": "nonexistent", "to": "plex-main"}
            ],
        )


def test_library_sync_rules_from_equals_to_raises():
    with pytest.raises(ValidationError, match="from == to"):
        _IsolatedAppSettings(
            plex=[{"name": "plex-main", "baseurl": "http://plex", "token": "x"}],
            library_sync_rules=[
                {"libraries": ["Movies"], "from": "plex-main", "to": "plex-main"}
            ],
        )


# ---------------------------------------------------------------------------
# AppSettings.all_servers property
# ---------------------------------------------------------------------------


def test_all_servers_returns_all():
    settings = _IsolatedAppSettings(
        plex=[{"name": "p1", "baseurl": "http://plex", "token": "x"}],
        jellyfin=[{"name": "jf1", "baseurl": "http://jf", "token": "y"}],
        emby=[{"name": "emby1", "baseurl": "http://emby", "token": "z"}],
    )
    names = {s.name for s in settings.all_servers}
    assert names == {"p1", "jf1", "emby1"}


def test_all_servers_returns_tuple():
    settings = _settings()
    assert isinstance(settings.all_servers, tuple)


# ---------------------------------------------------------------------------
# AppSettings.lookup_user
# ---------------------------------------------------------------------------


def test_lookup_user_returns_canonical():
    settings = _settings(
        user_mappings=[
            {
                "canonical": "Alice",
                "aliases": [
                    {"server": "plex-main", "username": "alice_plex"},
                    {"server": "jellyfin-main", "username": "alice_jf"},
                ],
            }
        ]
    )
    assert settings.lookup_user("plex-main", "alice_plex") == "alice"


def test_lookup_user_case_insensitive():
    settings = _settings(
        user_mappings=[
            {
                "canonical": "Alice",
                "aliases": [{"server": "plex-main", "username": "Alice"}],
            }
        ]
    )
    assert settings.lookup_user("plex-main", "ALICE") == "alice"


def test_lookup_user_not_found_returns_none():
    settings = _settings()
    assert settings.lookup_user("plex-main", "nobody") is None


# ---------------------------------------------------------------------------
# AppSettings.lookup_library
# ---------------------------------------------------------------------------


def test_lookup_library_returns_canonical():
    settings = _settings(
        library_mappings=[
            {
                "canonical": "Shows",
                "aliases": [
                    {"server": "plex-main", "library": "TV Shows"},
                    {"server": "jellyfin-main", "library": "Shows"},
                ],
            }
        ]
    )
    assert settings.lookup_library("plex-main", "tv shows") == "shows"


def test_lookup_library_not_found_returns_none():
    settings = _settings()
    assert settings.lookup_library("plex-main", "Nonexistent") is None


# ---------------------------------------------------------------------------
# AppSettings.is_user_allowed
# ---------------------------------------------------------------------------


def test_is_user_allowed_no_filters():
    settings = _settings()
    assert settings.is_user_allowed("anyone") is True


def test_is_user_allowed_whitelist():
    settings = _settings(whitelist_users=["alice"])
    assert settings.is_user_allowed("alice") is True
    assert settings.is_user_allowed("bob") is False


def test_is_user_allowed_whitelist_case_insensitive():
    settings = _settings(whitelist_users=["Alice"])
    assert settings.is_user_allowed("alice") is True


def test_is_user_allowed_blacklist():
    settings = _settings(blacklist_users=["bob"])
    assert settings.is_user_allowed("alice") is True
    assert settings.is_user_allowed("bob") is False


def test_is_user_allowed_blacklist_case_insensitive():
    settings = _settings(blacklist_users=["Bob"])
    assert settings.is_user_allowed("BOB") is False


def test_is_user_allowed_whitelist_by_identity():
    """Whitelisting any name in a user's identity allows all of their names."""
    settings = _settings(
        whitelist_users=["alice_plex"],
        user_mappings=[
            {
                "canonical": "Alice",
                "aliases": [
                    {"server": "plex-main", "username": "alice_plex"},
                    {"server": "jellyfin-main", "username": "alice_jf"},
                ],
            }
        ],
    )
    # alice_jf is allowed because alice_plex is whitelisted and they share an identity
    assert settings.is_user_allowed("alice_jf") is True
    # bob is not allowed (whitelist is active)
    assert settings.is_user_allowed("bob") is False


# ---------------------------------------------------------------------------
# AppSettings.is_library_type_allowed
# ---------------------------------------------------------------------------


def test_is_library_type_allowed_no_filters():
    settings = _settings()
    assert settings.is_library_type_allowed("movie") is True


def test_is_library_type_allowed_whitelist():
    settings = _settings(whitelist_library_types=["movie"])
    assert settings.is_library_type_allowed("movie") is True
    assert settings.is_library_type_allowed("show") is False


def test_is_library_type_allowed_whitelist_list():
    settings = _settings(whitelist_library_types=["movie", "show"])
    assert settings.is_library_type_allowed("movie") is True
    assert settings.is_library_type_allowed("music") is False


def test_is_library_type_allowed_whitelist_multi_all_must_match():
    """When a library has multiple types, ALL must be in the whitelist."""
    settings = _settings(whitelist_library_types=["movie"])
    # A library with types ["movie", "music"] — "music" is not in whitelist
    assert settings.is_library_type_allowed(["movie", "music"]) is False


def test_is_library_type_allowed_blacklist():
    settings = _settings(blacklist_library_types=["music"])
    assert settings.is_library_type_allowed("movie") is True
    assert settings.is_library_type_allowed("music") is False


def test_is_library_type_allowed_empty_types():
    settings = _settings(whitelist_library_types=["movie"])
    assert settings.is_library_type_allowed([]) is True


def test_is_library_type_allowed_case_insensitive():
    settings = _settings(blacklist_library_types=["Music"])
    assert settings.is_library_type_allowed("music") is False
    assert settings.is_library_type_allowed("MUSIC") is False


# ---------------------------------------------------------------------------
# AppSettings.should_sync_server
# ---------------------------------------------------------------------------


def test_should_sync_server_true_when_in_sync_to():
    settings = _settings()
    assert settings.should_sync_server("plex-main", "jellyfin-main") is True


def test_should_sync_server_false_when_not_in_sync_to():
    settings = _IsolatedAppSettings(
        plex=[
            {
                "name": "plex-main",
                "baseurl": "http://plex",
                "token": "x",
                "sync_to": [],  # doesn't push anywhere
            }
        ],
        jellyfin=[{"name": "jellyfin-main", "baseurl": "http://jf", "token": "y"}],
    )
    assert settings.should_sync_server("plex-main", "jellyfin-main") is False


def test_should_sync_server_false_for_same_server():
    settings = _settings()
    assert settings.should_sync_server("plex-main", "plex-main") is False


def test_should_sync_server_false_for_unknown_server():
    settings = _settings()
    assert settings.should_sync_server("plex-main", "unknown") is False
    assert settings.should_sync_server("unknown", "jellyfin-main") is False


def test_should_sync_server_true_via_rule_direction():
    """A sync_rule can enable a direction that server-level sync_to wouldn't."""
    settings = _IsolatedAppSettings(
        plex=[
            {
                "name": "plex-main",
                "baseurl": "http://plex",
                "token": "x",
                "sync_to": [],  # no server-level sync
            }
        ],
        jellyfin=[{"name": "jf-main", "baseurl": "http://jf", "token": "y"}],
        sync_rules=[
            # Rule-only direction: plex -> jf for user 'alice'
            {"users": ["alice"], "from": "plex-main", "to": "jf-main"}
        ],
    )
    # The direction is enabled by the rule
    assert settings.should_sync_server("plex-main", "jf-main") is True
    # Reverse direction is NOT enabled
    assert settings.should_sync_server("jf-main", "plex-main") is False


# ---------------------------------------------------------------------------
# AppSettings.should_sync_user
# ---------------------------------------------------------------------------


def test_should_sync_user_via_server_level():
    settings = _settings()
    assert settings.should_sync_user("alice", "plex-main", "jellyfin-main") is True


def test_should_sync_user_blacklisted():
    settings = _settings(blacklist_users=["alice"])
    assert settings.should_sync_user("alice", "plex-main", "jellyfin-main") is False


def test_should_sync_user_whitelisted():
    settings = _settings(whitelist_users=["alice"])
    assert settings.should_sync_user("alice", "plex-main", "jellyfin-main") is True
    assert settings.should_sync_user("bob", "plex-main", "jellyfin-main") is False


def test_should_sync_user_via_rule():
    """A sync_rule enables a user on a direction without server-level sync_to."""
    settings = _IsolatedAppSettings(
        plex=[
            {
                "name": "plex-main",
                "baseurl": "http://plex",
                "token": "x",
                "sync_to": [],  # no server-level push
            }
        ],
        jellyfin=[{"name": "jf-main", "baseurl": "http://jf", "token": "y"}],
        sync_rules=[{"users": ["alice"], "from": "plex-main", "to": "jf-main"}],
    )
    assert settings.should_sync_user("alice", "plex-main", "jf-main") is True
    assert settings.should_sync_user("bob", "plex-main", "jf-main") is False


def test_should_sync_user_canonical_rule():
    """A rule using a canonical name applies to all of that user's aliases."""
    settings = _IsolatedAppSettings(
        plex=[
            {"name": "plex-main", "baseurl": "http://plex", "token": "x", "sync_to": []}
        ],
        jellyfin=[{"name": "jf-main", "baseurl": "http://jf", "token": "y"}],
        user_mappings=[
            {
                "canonical": "Alice",
                "aliases": [
                    {"server": "plex-main", "username": "alice_plex"},
                    {"server": "jf-main", "username": "alice_jf"},
                ],
            }
        ],
        sync_rules=[{"users": ["Alice"], "from": "plex-main", "to": "jf-main"}],
    )
    # alice_plex is the from-server alias; rule uses the canonical name Alice
    assert settings.should_sync_user("alice_plex", "plex-main", "jf-main") is True


# ---------------------------------------------------------------------------
# AppSettings.should_sync_library
# ---------------------------------------------------------------------------


def test_should_sync_library_via_server_level():
    settings = _settings()
    assert settings.should_sync_library("Movies", "plex-main", "jellyfin-main") is True


def test_should_sync_library_blacklisted():
    settings = _settings(blacklist_libraries=["Movies"])
    assert (
        settings.should_sync_library("Movies", "plex-main", "jellyfin-main") is False
    )


def test_should_sync_library_whitelisted():
    settings = _settings(whitelist_libraries=["Movies"])
    assert (
        settings.should_sync_library("Movies", "plex-main", "jellyfin-main") is True
    )
    assert (
        settings.should_sync_library("TV Shows", "plex-main", "jellyfin-main") is False
    )


def test_should_sync_library_case_insensitive():
    settings = _settings(blacklist_libraries=["MOVIES"])
    assert (
        settings.should_sync_library("movies", "plex-main", "jellyfin-main") is False
    )


def test_should_sync_library_via_rule():
    settings = _IsolatedAppSettings(
        plex=[
            {
                "name": "plex-main",
                "baseurl": "http://plex",
                "token": "x",
                "sync_to": [],
            }
        ],
        jellyfin=[{"name": "jf-main", "baseurl": "http://jf", "token": "y"}],
        library_sync_rules=[
            {"libraries": ["Movies"], "from": "plex-main", "to": "jf-main"}
        ],
    )
    assert settings.should_sync_library("Movies", "plex-main", "jf-main") is True
    assert settings.should_sync_library("TV Shows", "plex-main", "jf-main") is False


# ---------------------------------------------------------------------------
# AppSettings.sync_targets_for_user
# ---------------------------------------------------------------------------


def test_sync_targets_for_user_with_mapping():
    settings = _settings(
        user_mappings=[
            {
                "canonical": "Alice",
                "aliases": [
                    {"server": "plex-main", "username": "alice_plex"},
                    {"server": "jellyfin-main", "username": "alice_jf"},
                ],
            }
        ]
    )
    targets = settings.sync_targets_for_user("plex-main", "alice_plex", "jellyfin-main")
    assert targets == ["alice_jf"]


def test_sync_targets_for_user_implicit_fallback():
    """When not mapped, the fallback is the same username."""
    settings = _settings()
    targets = settings.sync_targets_for_user("plex-main", "bob", "jellyfin-main")
    assert targets == ["bob"]


def test_sync_targets_for_user_fanout():
    """One source user can map to multiple targets on another server."""
    settings = _settings(
        user_mappings=[
            {
                "canonical": "family",
                "aliases": [
                    {"server": "plex-main", "username": "family"},
                    {"server": "jellyfin-main", "username": "alice"},
                    {"server": "jellyfin-main", "username": "bob"},
                ],
            }
        ]
    )
    targets = settings.sync_targets_for_user("plex-main", "family", "jellyfin-main")
    assert sorted(targets) == ["alice", "bob"]


def test_sync_targets_for_user_no_alias_on_target_returns_empty():
    """Mapped user with no alias on the target server returns []."""
    settings = _settings(
        user_mappings=[
            {
                "canonical": "Alice",
                "aliases": [
                    # only on plex-main, not on jellyfin-main
                    {"server": "plex-main", "username": "alice"},
                ],
            }
        ]
    )
    targets = settings.sync_targets_for_user("plex-main", "alice", "jellyfin-main")
    assert targets == []


def test_sync_targets_for_user_case_insensitive_lookup():
    settings = _settings(
        user_mappings=[
            {
                "canonical": "Alice",
                "aliases": [
                    {"server": "plex-main", "username": "Alice"},
                    {"server": "jellyfin-main", "username": "alice_jf"},
                ],
            }
        ]
    )
    # Look up with different casing
    targets = settings.sync_targets_for_user("plex-main", "ALICE", "jellyfin-main")
    assert targets == ["alice_jf"]


# ---------------------------------------------------------------------------
# AppSettings.sync_targets_for_library
# ---------------------------------------------------------------------------


def test_sync_targets_for_library_with_mapping():
    settings = _settings(
        library_mappings=[
            {
                "canonical": "Shows",
                "aliases": [
                    {"server": "plex-main", "library": "TV Shows"},
                    {"server": "jellyfin-main", "library": "Shows"},
                ],
            }
        ]
    )
    targets = settings.sync_targets_for_library("plex-main", "TV Shows", "jellyfin-main")
    assert targets == ["Shows"]


def test_sync_targets_for_library_implicit_fallback():
    settings = _settings()
    targets = settings.sync_targets_for_library("plex-main", "Movies", "jellyfin-main")
    assert targets == ["Movies"]


def test_sync_targets_for_library_no_alias_on_target():
    settings = _settings(
        library_mappings=[
            {
                "canonical": "Movies",
                "aliases": [
                    {"server": "plex-main", "library": "Movies"},
                    # no alias on jellyfin-main
                ],
            }
        ]
    )
    targets = settings.sync_targets_for_library("plex-main", "Movies", "jellyfin-main")
    assert targets == []


# ---------------------------------------------------------------------------
# _dump_for_yaml
# ---------------------------------------------------------------------------


def test_dump_for_yaml_excludes_defaults():
    """Fields that weren't explicitly set are excluded from the YAML dump."""
    settings = _IsolatedAppSettings(
        plex=[{"name": "p1", "baseurl": "http://plex", "token": "x"}]
    )
    dumped = _dump_for_yaml(settings)
    # 'plex' was set; 'jellyfin', 'emby', 'dryrun' etc. were not
    assert "plex" in dumped
    # Default fields are excluded
    assert "jellyfin" not in dumped
    assert "dryrun" not in dumped


def test_dump_for_yaml_unwraps_secret_str():
    """SecretStr values are emitted as plaintext in the YAML dump."""
    settings = _IsolatedAppSettings(
        plex=[{"name": "p1", "baseurl": "http://plex", "token": "mytoken"}]
    )
    dumped = _dump_for_yaml(settings)
    plex_entry = dumped["plex"][0]
    assert plex_entry["token"] == "mytoken"


def test_dump_for_yaml_path_as_string():
    """Path objects are serialized as strings."""
    from pathlib import Path

    settings = _IsolatedAppSettings(
        plex=[{"name": "p1", "baseurl": "http://plex", "token": "x"}],
        log_file=Path("/var/log/jellyplex.log"),
    )
    dumped = _dump_for_yaml(settings)
    assert isinstance(dumped["log_file"], str)
    assert dumped["log_file"] == "/var/log/jellyplex.log"


# ---------------------------------------------------------------------------
# sync_rules wildcard expansion
# ---------------------------------------------------------------------------


def test_sync_rules_wildcard_expands_to_all_canonicals():
    """users=['*'] in a sync_rule applies to all canonical users."""
    settings = _IsolatedAppSettings(
        plex=[
            {
                "name": "plex-main",
                "baseurl": "http://plex",
                "token": "x",
                "sync_to": [],
            }
        ],
        jellyfin=[{"name": "jf-main", "baseurl": "http://jf", "token": "y"}],
        user_mappings=[
            {
                "canonical": "Alice",
                "aliases": [
                    {"server": "plex-main", "username": "alice"},
                    {"server": "jf-main", "username": "alice"},
                ],
            }
        ],
        sync_rules=[{"users": ["*"], "from": "plex-main", "to": "jf-main"}],
    )
    # Alice is a canonical, so the wildcard covers her
    assert settings.should_sync_user("alice", "plex-main", "jf-main") is True


# ---------------------------------------------------------------------------
# AppSettings defaults
# ---------------------------------------------------------------------------


def test_default_values():
    settings = _IsolatedAppSettings(
        plex=[{"name": "p1", "baseurl": "http://plex", "token": "x"}]
    )
    assert settings.dryrun is True
    assert settings.debug_level == "INFO"
    assert settings.run_only_once is False
    assert settings.sleep_duration == 3600
    assert settings.request_timeout == 300
    assert settings.max_threads == 32
    assert settings.generate_guids is True
    assert settings.generate_locations is True
    assert settings.blacklist_libraries == []
    assert settings.whitelist_libraries == []
    assert settings.blacklist_users == []
    assert settings.whitelist_users == []
