import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add the parent directory to sys.path so we can import from src/
current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
sys.path.append(parent)

from src.legacy_settings import (
    _build_legacy_mappings,
    _build_plex_servers,
    _build_sync_to,
    _build_token_servers,
    _env_as_bool,
    _env_as_int,
    _env_as_list,
    _parse_dict_mapping,
    legacy_env_to_field_dict,
    read_legacy_env,
)


# ---------------------------------------------------------------------------
# _env_as_bool
# ---------------------------------------------------------------------------


def test_env_as_bool_true_values():
    for v in ("1", "true", "True", "TRUE", "yes", "YES", "on", "ON"):
        assert _env_as_bool(v) is True, f"Expected True for {v!r}"


def test_env_as_bool_false_values():
    for v in ("0", "false", "False", "no", "No", "off"):
        assert _env_as_bool(v) is False, f"Expected False for {v!r}"


def test_env_as_bool_none_returns_none():
    assert _env_as_bool(None) is None


def test_env_as_bool_empty_returns_none():
    assert _env_as_bool("") is None


# ---------------------------------------------------------------------------
# _env_as_int
# ---------------------------------------------------------------------------


def test_env_as_int_valid():
    assert _env_as_int("42") == 42
    assert _env_as_int("0") == 0
    assert _env_as_int("-5") == -5


def test_env_as_int_none_returns_none():
    assert _env_as_int(None) is None


def test_env_as_int_empty_returns_none():
    assert _env_as_int("") is None


def test_env_as_int_non_numeric_returns_none():
    assert _env_as_int("abc") is None
    assert _env_as_int("3.14") is None


# ---------------------------------------------------------------------------
# _env_as_list
# ---------------------------------------------------------------------------


def test_env_as_list_basic():
    assert _env_as_list("a,b,c") == ["a", "b", "c"]


def test_env_as_list_trims_whitespace():
    assert _env_as_list("a , b , c") == ["a", "b", "c"]


def test_env_as_list_none_returns_empty():
    assert _env_as_list(None) == []


def test_env_as_list_empty_returns_empty():
    assert _env_as_list("") == []


def test_env_as_list_single_value():
    assert _env_as_list("only") == ["only"]


def test_env_as_list_skips_empty_parts():
    assert _env_as_list("a,,b") == ["a", "b"]


# ---------------------------------------------------------------------------
# _parse_dict_mapping
# ---------------------------------------------------------------------------


def test_parse_dict_mapping_json():
    result = _parse_dict_mapping('{"Alice": "alice_jf", "Bob": "bob_jf"}')
    assert result == {"Alice": "alice_jf", "Bob": "bob_jf"}


def test_parse_dict_mapping_pythonic():
    result = _parse_dict_mapping("{'alice': 'alice_jf', 'bob': 'bob_jf'}")
    assert result == {"alice": "alice_jf", "bob": "bob_jf"}


def test_parse_dict_mapping_legacy_pair():
    result = _parse_dict_mapping("alice:alice_jf; bob:bob_jf")
    assert result == {"alice": "alice_jf", "bob": "bob_jf"}


def test_parse_dict_mapping_empty_returns_empty():
    assert _parse_dict_mapping("") == {}
    assert _parse_dict_mapping(None) == {}


def test_parse_dict_mapping_strips_whitespace():
    result = _parse_dict_mapping('{ "Alice" : "alice_jf" }')
    assert "Alice" in result
    assert result["Alice"] == "alice_jf"


def test_parse_dict_mapping_single_pair():
    result = _parse_dict_mapping("alice:alice_jf")
    assert result == {"alice": "alice_jf"}


# ---------------------------------------------------------------------------
# read_legacy_env
# ---------------------------------------------------------------------------


def test_read_legacy_env_nonexistent_file_returns_empty():
    result = read_legacy_env(Path("/nonexistent/path/.env"))
    assert result == {}


def test_read_legacy_env_reads_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DRYRUN=true\nSLEEP_DURATION=1800\n")
    result = read_legacy_env(env_file)
    assert result.get("DRYRUN") == "true"
    assert result.get("SLEEP_DURATION") == "1800"


# ---------------------------------------------------------------------------
# _build_plex_servers
# ---------------------------------------------------------------------------


def test_build_plex_servers_with_token():
    env = {
        "PLEX_BASEURL": "http://plex:32400",
        "PLEX_TOKEN": "mytoken",
    }
    servers = _build_plex_servers(env)
    assert len(servers) == 1
    assert servers[0]["name"] == "plex-main"
    assert servers[0]["baseurl"] == "http://plex:32400"
    assert servers[0]["token"] == "mytoken"


def test_build_plex_servers_with_userpass():
    env = {
        "PLEX_BASEURL": "http://plex:32400",
        "PLEX_USERNAME": "user",
        "PLEX_PASSWORD": "pass",
        "PLEX_SERVERNAME": "MyPlex",
    }
    servers = _build_plex_servers(env)
    assert len(servers) == 1
    assert servers[0]["username"] == "user"
    assert servers[0]["password"] == "pass"
    assert servers[0]["servername"] == "MyPlex"
    assert "token" not in servers[0]


def test_build_plex_servers_multiple():
    env = {
        "PLEX_BASEURL": "http://plex1:32400,http://plex2:32400",
        "PLEX_TOKEN": "token1,token2",
    }
    servers = _build_plex_servers(env)
    assert len(servers) == 2
    assert servers[0]["name"] == "plex-1"
    assert servers[1]["name"] == "plex-2"
    assert servers[0]["token"] == "token1"
    assert servers[1]["token"] == "token2"


def test_build_plex_servers_no_baseurl_returns_empty():
    env: dict = {}
    assert _build_plex_servers(env) == []


def test_build_plex_servers_ssl_bypass():
    env = {
        "PLEX_BASEURL": "http://plex:32400",
        "PLEX_TOKEN": "token",
        "SSL_BYPASS": "true",
    }
    servers = _build_plex_servers(env)
    assert servers[0]["ssl_bypass"] is True


# ---------------------------------------------------------------------------
# _build_token_servers
# ---------------------------------------------------------------------------


def test_build_token_servers_jellyfin():
    env = {
        "JELLYFIN_BASEURL": "http://jf:8096",
        "JELLYFIN_TOKEN": "jftoken",
    }
    servers = _build_token_servers(env, "JELLYFIN_BASEURL", "JELLYFIN_TOKEN", "jellyfin")
    assert len(servers) == 1
    assert servers[0]["name"] == "jellyfin-main"
    assert servers[0]["baseurl"] == "http://jf:8096"
    assert servers[0]["token"] == "jftoken"


def test_build_token_servers_multiple():
    env = {
        "JELLYFIN_BASEURL": "http://jf1:8096,http://jf2:8096",
        "JELLYFIN_TOKEN": "token1,token2",
    }
    servers = _build_token_servers(env, "JELLYFIN_BASEURL", "JELLYFIN_TOKEN", "jellyfin")
    assert len(servers) == 2
    assert servers[0]["name"] == "jellyfin-1"
    assert servers[1]["name"] == "jellyfin-2"


def test_build_token_servers_missing_token_skips(capsys):
    env = {
        "JELLYFIN_BASEURL": "http://jf1:8096,http://jf2:8096",
        "JELLYFIN_TOKEN": "token1",  # only one token for two URLs
    }
    servers = _build_token_servers(env, "JELLYFIN_BASEURL", "JELLYFIN_TOKEN", "jellyfin")
    # Second server should be skipped because it has no token
    assert len(servers) == 1
    assert servers[0]["token"] == "token1"


def test_build_token_servers_no_baseurl_returns_empty():
    env: dict = {}
    servers = _build_token_servers(env, "JELLYFIN_BASEURL", "JELLYFIN_TOKEN", "jellyfin")
    assert servers == []


def test_build_token_servers_emby():
    env = {
        "EMBY_BASEURL": "http://emby:8096",
        "EMBY_TOKEN": "embytoken",
    }
    servers = _build_token_servers(env, "EMBY_BASEURL", "EMBY_TOKEN", "emby")
    assert len(servers) == 1
    assert servers[0]["name"] == "emby-main"


# ---------------------------------------------------------------------------
# _build_sync_to
# ---------------------------------------------------------------------------


def test_build_sync_to_plex_to_jellyfin():
    env = {"SYNC_FROM_PLEX_TO_JELLYFIN": "true"}
    result = _build_sync_to(env, ["plex-main"], ["jf-main"], [])
    assert "plex-main" in result
    assert "jf-main" in result["plex-main"]


def test_build_sync_to_bidirectional():
    env = {
        "SYNC_FROM_PLEX_TO_JELLYFIN": "true",
        "SYNC_FROM_JELLYFIN_TO_PLEX": "true",
    }
    result = _build_sync_to(env, ["plex-main"], ["jf-main"], [])
    assert "jf-main" in result.get("plex-main", [])
    assert "plex-main" in result.get("jf-main", [])


def test_build_sync_to_no_flags_returns_empty():
    env: dict = {}
    result = _build_sync_to(env, ["plex-main"], ["jf-main"], [])
    assert result == {}


def test_build_sync_to_does_not_sync_to_self():
    env = {"SYNC_FROM_PLEX_TO_PLEX": "true"}
    result = _build_sync_to(env, ["plex-1", "plex-2"], [], [])
    # plex-1 should sync to plex-2, but not to itself
    assert "plex-2" in result.get("plex-1", [])
    assert "plex-1" not in result.get("plex-1", [])


def test_build_sync_to_all_three_types():
    env = {
        "SYNC_FROM_PLEX_TO_JELLYFIN": "true",
        "SYNC_FROM_JELLYFIN_TO_EMBY": "true",
    }
    result = _build_sync_to(env, ["plex-main"], ["jf-main"], ["emby-main"])
    assert "jf-main" in result.get("plex-main", [])
    assert "emby-main" in result.get("jf-main", [])
    # plex should NOT sync to emby (no flag)
    assert "emby-main" not in result.get("plex-main", [])


# ---------------------------------------------------------------------------
# _build_legacy_mappings
# ---------------------------------------------------------------------------


def test_build_legacy_mappings_adds_both_names_to_all_servers():
    pairs = {"Alice": "alice_jf"}
    server_names = ["plex-main", "jf-main"]
    result = _build_legacy_mappings(pairs, server_names, "username")

    assert len(result) == 1
    entry = result[0]
    assert entry["canonical"] == "Alice"

    # Both names should appear as aliases on every server
    aliases = entry["aliases"]
    servers_with_alice = [a["server"] for a in aliases if a["username"] == "Alice"]
    servers_with_alice_jf = [a["server"] for a in aliases if a["username"] == "alice_jf"]
    assert "plex-main" in servers_with_alice
    assert "jf-main" in servers_with_alice
    assert "plex-main" in servers_with_alice_jf
    assert "jf-main" in servers_with_alice_jf


def test_build_legacy_mappings_empty_pairs_returns_empty():
    assert _build_legacy_mappings({}, ["plex-main"], "username") == []


def test_build_legacy_mappings_empty_servers_returns_empty():
    assert _build_legacy_mappings({"a": "b"}, [], "username") == []


def test_build_legacy_mappings_library():
    pairs = {"TV Shows": "Shows"}
    server_names = ["plex-main"]
    result = _build_legacy_mappings(pairs, server_names, "library")
    assert result[0]["canonical"] == "TV Shows"
    alias_libraries = [a["library"] for a in result[0]["aliases"]]
    assert "TV Shows" in alias_libraries
    assert "Shows" in alias_libraries


# ---------------------------------------------------------------------------
# legacy_env_to_field_dict
# ---------------------------------------------------------------------------


def test_legacy_env_to_field_dict_dryrun():
    env = {"DRYRUN": "true"}
    result = legacy_env_to_field_dict(env)
    assert result.get("dryrun") is True


def test_legacy_env_to_field_dict_dryrun_false():
    env = {"DRYRUN": "false"}
    result = legacy_env_to_field_dict(env)
    assert result.get("dryrun") is False


def test_legacy_env_to_field_dict_debug_level():
    env = {"DEBUG_LEVEL": "debug"}
    result = legacy_env_to_field_dict(env)
    assert result.get("debug_level") == "DEBUG"


def test_legacy_env_to_field_dict_debug_flag():
    env = {"DEBUG": "true"}
    result = legacy_env_to_field_dict(env)
    assert result.get("debug_level") == "DEBUG"


def test_legacy_env_to_field_dict_sleep_duration():
    env = {"SLEEP_DURATION": "1800"}
    result = legacy_env_to_field_dict(env)
    assert result.get("sleep_duration") == 1800


def test_legacy_env_to_field_dict_request_timeout():
    env = {"REQUEST_TIMEOUT": "120"}
    result = legacy_env_to_field_dict(env)
    assert result.get("request_timeout") == 120


def test_legacy_env_to_field_dict_blacklist_libraries():
    env = {"BLACKLIST_LIBRARY": "Music, Audiobooks"}
    result = legacy_env_to_field_dict(env)
    assert result.get("blacklist_libraries") == ["Music", "Audiobooks"]


def test_legacy_env_to_field_dict_whitelist_library_type():
    env = {"WHITELIST_LIBRARY_TYPE": "movie, show"}
    result = legacy_env_to_field_dict(env)
    assert result.get("whitelist_library_types") == ["movie", "show"]


def test_legacy_env_to_field_dict_plex_server():
    env = {
        "PLEX_BASEURL": "http://plex:32400",
        "PLEX_TOKEN": "mytoken",
    }
    result = legacy_env_to_field_dict(env)
    assert "plex" in result
    assert len(result["plex"]) == 1
    assert result["plex"][0]["token"] == "mytoken"


def test_legacy_env_to_field_dict_jellyfin_server():
    env = {
        "JELLYFIN_BASEURL": "http://jf:8096",
        "JELLYFIN_TOKEN": "jftoken",
    }
    result = legacy_env_to_field_dict(env)
    assert "jellyfin" in result
    assert result["jellyfin"][0]["token"] == "jftoken"


def test_legacy_env_to_field_dict_no_sync_flags_means_all_sync():
    """Without SYNC_FROM_X_TO_Y flags, every server syncs to every other."""
    env = {
        "PLEX_BASEURL": "http://plex:32400",
        "PLEX_TOKEN": "ptoken",
        "JELLYFIN_BASEURL": "http://jf:8096",
        "JELLYFIN_TOKEN": "jftoken",
    }
    result = legacy_env_to_field_dict(env)
    plex_entry = result["plex"][0]
    jf_entry = result["jellyfin"][0]
    assert "jellyfin-main" in plex_entry.get("sync_to", [])
    assert "plex-main" in jf_entry.get("sync_to", [])


def test_legacy_env_to_field_dict_sync_flag_respected():
    """With SYNC_FROM_X_TO_Y flags, only flagged directions are enabled."""
    env = {
        "PLEX_BASEURL": "http://plex:32400",
        "PLEX_TOKEN": "ptoken",
        "JELLYFIN_BASEURL": "http://jf:8096",
        "JELLYFIN_TOKEN": "jftoken",
        "SYNC_FROM_PLEX_TO_JELLYFIN": "true",
        # Not setting SYNC_FROM_JELLYFIN_TO_PLEX, so that direction is off
    }
    result = legacy_env_to_field_dict(env)
    plex_entry = result["plex"][0]
    jf_entry = result["jellyfin"][0]
    # plex -> jellyfin is enabled
    assert "jellyfin-main" in plex_entry.get("sync_to", [])
    # jellyfin -> plex is NOT enabled
    assert "plex-main" not in jf_entry.get("sync_to", [])


def test_legacy_env_to_field_dict_user_mapping():
    env = {
        "PLEX_BASEURL": "http://plex:32400",
        "PLEX_TOKEN": "ptoken",
        "JELLYFIN_BASEURL": "http://jf:8096",
        "JELLYFIN_TOKEN": "jftoken",
        "USER_MAPPING": '{"alice": "alice_jf"}',
    }
    result = legacy_env_to_field_dict(env)
    assert "user_mappings" in result
    mapping = result["user_mappings"][0]
    assert mapping["canonical"] == "alice"
    # Both alice and alice_jf should appear as aliases on both servers
    alias_names = {a["username"] for a in mapping["aliases"]}
    assert "alice" in alias_names
    assert "alice_jf" in alias_names


def test_legacy_env_to_field_dict_library_mapping():
    env = {
        "PLEX_BASEURL": "http://plex:32400",
        "PLEX_TOKEN": "ptoken",
        "JELLYFIN_BASEURL": "http://jf:8096",
        "JELLYFIN_TOKEN": "jftoken",
        "LIBRARY_MAPPING": '{"TV Shows": "Shows"}',
    }
    result = legacy_env_to_field_dict(env)
    assert "library_mappings" in result
    mapping = result["library_mappings"][0]
    assert mapping["canonical"] == "TV Shows"
    alias_libraries = {a["library"] for a in mapping["aliases"]}
    assert "TV Shows" in alias_libraries
    assert "Shows" in alias_libraries


def test_legacy_env_to_field_dict_log_file():
    env = {"LOG_FILE": "/var/log/jellyplex.log"}
    result = legacy_env_to_field_dict(env)
    assert result.get("log_file") == "/var/log/jellyplex.log"


def test_legacy_env_to_field_dict_logfile_alias():
    env = {"LOGFILE": "/tmp/jellyplex.log"}
    result = legacy_env_to_field_dict(env)
    assert result.get("log_file") == "/tmp/jellyplex.log"


def test_legacy_env_to_field_dict_mark_file():
    env = {"MARK_FILE": "/tmp/mark.log"}
    result = legacy_env_to_field_dict(env)
    assert result.get("mark_file") == "/tmp/mark.log"


def test_legacy_env_to_field_dict_markfile_alias():
    env = {"MARKFILE": "/tmp/mark.log"}
    result = legacy_env_to_field_dict(env)
    assert result.get("mark_file") == "/tmp/mark.log"


def test_legacy_env_to_field_dict_generate_guids():
    env = {"GENERATE_GUIDS": "false"}
    result = legacy_env_to_field_dict(env)
    assert result.get("generate_guids") is False


def test_legacy_env_to_field_dict_generate_locations():
    env = {"GENERATE_LOCATIONS": "false"}
    result = legacy_env_to_field_dict(env)
    assert result.get("generate_locations") is False


def test_legacy_env_to_field_dict_empty_env_returns_empty():
    result = legacy_env_to_field_dict({})
    # No servers, no settings
    assert "plex" not in result
    assert "jellyfin" not in result


def test_legacy_env_to_field_dict_max_threads():
    env = {"MAX_THREADS": "16"}
    result = legacy_env_to_field_dict(env)
    assert result.get("max_threads") == 16


def test_legacy_env_to_field_dict_run_only_once():
    env = {"RUN_ONLY_ONCE": "true"}
    result = legacy_env_to_field_dict(env)
    assert result.get("run_only_once") is True


def test_legacy_env_to_field_dict_blacklist_users():
    env = {"BLACKLIST_USERS": "user1,user2"}
    result = legacy_env_to_field_dict(env)
    assert result.get("blacklist_users") == ["user1", "user2"]


def test_legacy_env_to_field_dict_whitelist_users():
    env = {"WHITELIST_USERS": "alice"}
    result = legacy_env_to_field_dict(env)
    assert result.get("whitelist_users") == ["alice"]