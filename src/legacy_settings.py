# ---------------------------------------------------------------------------
# Legacy .env parsing
# ---------------------------------------------------------------------------


import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from loguru import logger
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

LegacyEnvPath = Path | str | Sequence[Path | str] | None

LEGACY_ENV_VARS = {
    # operational
    "DRYRUN",
    "DEBUG",
    "DEBUG_LEVEL",
    "RUN_ONLY_ONCE",
    "SLEEP_DURATION",
    "LOGFILE",
    "LOG_FILE",
    "MARKFILE",
    "MARK_FILE",
    "REQUEST_TIMEOUT",
    "MAX_THREADS",
    "GENERATE_GUIDS",
    "GENERATE_LOCATIONS",
    # filtering
    "BLACKLIST_LIBRARY",
    "WHITELIST_LIBRARY",
    "BLACKLIST_LIBRARY_TYPE",
    "WHITELIST_LIBRARY_TYPE",
    "BLACKLIST_USERS",
    "WHITELIST_USERS",
    # plex servers
    "PLEX_BASEURL",
    "PLEX_TOKEN",
    "PLEX_USERNAME",
    "PLEX_PASSWORD",
    "PLEX_SERVERNAME",
    "SSL_BYPASS",
    # jellyfin servers
    "JELLYFIN_BASEURL",
    "JELLYFIN_TOKEN",
    # emby servers
    "EMBY_BASEURL",
    "EMBY_TOKEN",
    # mappings
    "USER_MAPPING",
    "LIBRARY_MAPPING",
    # sync direction flags
    "SYNC_FROM_PLEX_TO_JELLYFIN",
    "SYNC_FROM_PLEX_TO_PLEX",
    "SYNC_FROM_PLEX_TO_EMBY",
    "SYNC_FROM_JELLYFIN_TO_PLEX",
    "SYNC_FROM_JELLYFIN_TO_JELLYFIN",
    "SYNC_FROM_JELLYFIN_TO_EMBY",
    "SYNC_FROM_EMBY_TO_PLEX",
    "SYNC_FROM_EMBY_TO_JELLYFIN",
    "SYNC_FROM_EMBY_TO_EMBY",
}

# Keep alias order aligned with the preference used by the translator below.
# Resolution chooses a source for the whole group before exposing its keys to
# the translator, so a lower-priority file alias cannot beat a process alias.
_LEGACY_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("LOG_FILE", "LOGFILE"),
    ("MARK_FILE", "MARKFILE"),
    ("DEBUG_LEVEL", "DEBUG"),
)


def resolve_legacy_env(
    file_env: Mapping[str, str | None],
    process_env: Mapping[str, str | None] | None = None,
) -> dict[str, str | None]:
    """Resolve recognized legacy keys with process presence taking precedence.

    A present process key wins even when its value is empty. A valueless dotenv
    key is represented as ``None`` and follows the same rule. Aliases are
    resolved as groups: the highest-priority source containing any alias wins,
    then the translator retains its existing preference within that source.
    Legacy parsers treat empty and valueless values as unset after this
    precedence decision; they never fall back to the lower-priority file value.
    """
    process_values = os.environ if process_env is None else process_env
    resolved: dict[str, str | None] = {}

    grouped_keys: set[str] = set()
    for aliases in _LEGACY_ALIAS_GROUPS:
        grouped_keys.update(aliases)
        if any(key in process_values for key in aliases):
            source = process_values
        elif any(key in file_env for key in aliases):
            source = file_env
        else:
            continue

        for key in aliases:
            if key in source:
                resolved[key] = source[key]

    for key in sorted(LEGACY_ENV_VARS - grouped_keys):
        if key in process_values:
            resolved[key] = process_values[key]
        elif key in file_env:
            resolved[key] = file_env[key]
    return resolved


_TRUE_BOOLEAN_VALUES = frozenset({"1", "true", "yes", "on", "t", "y"})
_FALSE_BOOLEAN_VALUES = frozenset({"0", "false", "no", "off", "f", "n"})


def _env_as_bool(v: str | None, field_name: str) -> bool | None:
    """Parse legacy boolean spellings without silently accepting typos."""
    if v is None:
        return None

    normalized = v.strip().casefold()
    if not normalized:
        return None
    if normalized in _TRUE_BOOLEAN_VALUES:
        return True
    if normalized in _FALSE_BOOLEAN_VALUES:
        return False
    raise ValueError(f"invalid boolean value for {field_name}")


def _env_as_int(v: str | None) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _env_as_list(v: str | None) -> list[str]:
    """Split a comma-separated env value into trimmed parts."""
    if v is None or v == "":
        return []
    return [item.strip() for item in v.split(",") if item.strip()]


def _env_as_indexed_list(v: str | None) -> list[str]:
    """Split a comma-separated value while retaining empty positions."""
    if v is None or v == "":
        return []
    return [item.strip() for item in v.split(",")]


def _parse_dict_mapping(v: str | None) -> dict[str, str]:
    """
    Parse the legacy USER_MAPPING / LIBRARY_MAPPING format into a flat dict.

    Accepts:
      JSON-ish:    { "Username": "User", "Second User": "User Dos" }
      Pythonic:    {'a': 'b', 'c': 'd'}
      Legacy pair: a:b; c:d  (older docs used this)

    Returns {} if the value can't be parsed.
    """
    if not v:
        return {}
    s = v.strip()
    if s.startswith("{") and s.endswith("}"):
        for candidate in (s, s.replace("'", '"')):
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return {str(k).strip(): str(v).strip() for k, v in parsed.items()}
            except json.JSONDecodeError:
                continue
    pairs: dict[str, str] = {}
    for chunk in re.split(r"[;,]", s):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        left, _, right = chunk.partition(":")
        pairs[left.strip()] = right.strip()
    return pairs


def read_legacy_env(
    env_path: LegacyEnvPath,
    encoding: str | None = None,
) -> dict[str, str | None]:
    """
    Load a .env file into a plain dict via dotenv_values.

    Returns an empty dict if the file doesn't exist. Values may be None
    when a key is present in the file without a value (dotenv semantics);
    ``resolve_legacy_env`` preserves those entries so process/file precedence
    is decided before parsers treat them as unset.
    """
    if env_path is None:
        return {}

    env_paths = [env_path] if isinstance(env_path, (Path, str)) else env_path
    values: dict[str, str | None] = {}
    for path in env_paths:
        path_obj = Path(path)
        if path_obj.exists():
            values.update(dotenv_values(path_obj, encoding=encoding or "utf-8"))
    return values


def _build_plex_servers(env: dict[str, str | None]) -> list[dict[str, Any]]:
    """
    Build Plex server entries from comma-separated legacy vars.

    Servers are paired by index across PLEX_BASEURL / PLEX_TOKEN /
    PLEX_USERNAME / PLEX_PASSWORD / PLEX_SERVERNAME. Each baseurl produces
    one entry; auth fields are taken from the same index when present.
    """
    baseurls = _env_as_indexed_list(env.get("PLEX_BASEURL"))
    server_count = sum(bool(baseurl) for baseurl in baseurls)
    if not server_count:
        return []

    tokens = _env_as_indexed_list(env.get("PLEX_TOKEN"))
    usernames = _env_as_indexed_list(env.get("PLEX_USERNAME"))
    passwords = _env_as_indexed_list(env.get("PLEX_PASSWORD"))
    servernames = _env_as_indexed_list(env.get("PLEX_SERVERNAME"))
    ssl_bypass = _env_as_bool(env.get("SSL_BYPASS"), "SSL_BYPASS")

    servers: list[dict[str, Any]] = []
    for i, baseurl in enumerate(baseurls):
        if not baseurl:
            continue
        entry: dict[str, Any] = {
            "name": f"plex-{i + 1}" if server_count > 1 else "plex-main",
            "baseurl": baseurl,
        }
        if i < len(tokens) and tokens[i]:
            entry["token"] = tokens[i]
        else:
            if i < len(usernames) and usernames[i]:
                entry["username"] = usernames[i]
            if i < len(passwords) and passwords[i]:
                entry["password"] = passwords[i]
            if i < len(servernames) and servernames[i]:
                entry["servername"] = servernames[i]
        if ssl_bypass is not None:
            entry["ssl_bypass"] = ssl_bypass
        servers.append(entry)

    return servers


def _build_token_servers(
    env: dict[str, str | None],
    baseurl_key: str,
    token_key: str,
    name_prefix: str,
) -> list[dict[str, Any]]:
    """Build Jellyfin/Emby server entries (token-only auth)."""
    baseurls = _env_as_indexed_list(env.get(baseurl_key))
    server_count = sum(bool(baseurl) for baseurl in baseurls)
    if not server_count:
        return []
    tokens = _env_as_indexed_list(env.get(token_key))

    servers: list[dict[str, Any]] = []
    for i, baseurl in enumerate(baseurls):
        if not baseurl:
            continue
        if i >= len(tokens):
            logger.warning(
                "{} has {} entries but {} only has {}. Server #{} skipped.",
                baseurl_key,
                len(baseurls),
                token_key,
                len(tokens),
                i + 1,
            )
            continue
        if not tokens[i]:
            logger.warning(
                "{} has an empty credential at position {}. Server #{} skipped.",
                token_key,
                i + 1,
                i + 1,
            )
            continue
        servers.append(
            {
                "name": (
                    f"{name_prefix}-{i + 1}"
                    if server_count > 1
                    else f"{name_prefix}-main"
                ),
                "baseurl": baseurl,
                "token": tokens[i],
            }
        )
    return servers


def _build_sync_to(
    env: dict[str, str | None],
    plex_names: list[str],
    jellyfin_names: list[str],
    emby_names: list[str],
) -> dict[str, list[str]]:
    """
    Translate legacy SYNC_FROM_X_TO_Y flags into per-server sync_to lists
    of plain server names.
    """
    type_names = {
        "plex": plex_names,
        "jellyfin": jellyfin_names,
        "emby": emby_names,
    }

    def is_set(src: str, dst: str) -> bool:
        flag = f"SYNC_FROM_{src.upper()}_TO_{dst.upper()}"
        return bool(_env_as_bool(env.get(flag), flag))

    result: dict[str, list[str]] = {}
    type_order = ["plex", "jellyfin", "emby"]

    for src_type in type_order:
        for dst_type in type_order:
            if not is_set(src_type, dst_type):
                continue
            for src in type_names[src_type]:
                for dst in type_names[dst_type]:
                    if src == dst:
                        continue
                    bucket = result.setdefault(src, [])
                    if dst not in bucket:
                        bucket.append(dst)

    return result


def _build_legacy_mappings(
    pairs: dict[str, str],
    server_names: list[str],
    name_field: str,
) -> list[dict[str, Any]]:
    """
    Build user/library mapping entries from a legacy `{a: b}` dict.

    The legacy format records two names per pair but doesn't say which
    name belongs to which server. The safe correct behavior is to add
    *both* names as aliases on *every* server — over-broad, but the sync
    engine will match correctly regardless of which server actually uses
    which name. The user can prune in the YAML afterward.
    """
    if not pairs or not server_names:
        return []

    legacy_var = "USER_MAPPING" if name_field == "username" else "LIBRARY_MAPPING"
    logger.warning(
        f"Legacy {legacy_var} cannot identify which server owns each alias. "
        f"Translated {len(pairs)} mapping pair(s) by assigning both names to "
        "every configured server. Review the generated YAML before disabling "
        "dryrun."
    )

    out: list[dict[str, Any]] = []
    for left, right in pairs.items():
        aliases: list[dict[str, Any]] = []
        for server in server_names:
            for alias_value in (left, right):
                aliases.append({"server": server, name_field: alias_value})
        out.append({"canonical": left, "aliases": aliases})
    return out


def legacy_env_to_field_dict(env: dict[str, str | None]) -> dict[str, Any]:
    """
    Translate flat legacy env vars into a dict matching AppSettings fields.
    """
    out: dict[str, Any] = {}

    for src_key, dst_key in [
        ("DRYRUN", "dryrun"),
        ("RUN_ONLY_ONCE", "run_only_once"),
        ("GENERATE_GUIDS", "generate_guids"),
        ("GENERATE_LOCATIONS", "generate_locations"),
    ]:
        parsed = _env_as_bool(env.get(src_key), src_key)
        if parsed is not None:
            out[dst_key] = parsed

    for src_key, dst_key, parser in [
        ("SLEEP_DURATION", "sleep_duration", _env_as_int),
        ("REQUEST_TIMEOUT", "request_timeout", _env_as_int),
        ("MAX_THREADS", "max_threads", _env_as_int),
    ]:
        parsed = parser(env.get(src_key))
        if parsed is not None:
            out[dst_key] = parsed

    debug_level = env.get("DEBUG_LEVEL")
    if debug_level:
        out["debug_level"] = debug_level.upper()
    elif _env_as_bool(env.get("DEBUG"), "DEBUG"):
        out["debug_level"] = "DEBUG"

    log_file = env.get("LOG_FILE") or env.get("LOGFILE")
    if log_file:
        out["log_file"] = log_file
    mark_file = env.get("MARK_FILE") or env.get("MARKFILE")
    if mark_file:
        out["mark_file"] = mark_file

    for src_key, dst_key in [
        ("BLACKLIST_LIBRARY", "blacklist_libraries"),
        ("WHITELIST_LIBRARY", "whitelist_libraries"),
        ("BLACKLIST_LIBRARY_TYPE", "blacklist_library_types"),
        ("WHITELIST_LIBRARY_TYPE", "whitelist_library_types"),
        ("BLACKLIST_USERS", "blacklist_users"),
        ("WHITELIST_USERS", "whitelist_users"),
    ]:
        items = _env_as_list(env.get(src_key))
        if items:
            out[dst_key] = items

    plex_servers = _build_plex_servers(env)
    jellyfin_servers = _build_token_servers(
        env, "JELLYFIN_BASEURL", "JELLYFIN_TOKEN", "jellyfin"
    )
    emby_servers = _build_token_servers(env, "EMBY_BASEURL", "EMBY_TOKEN", "emby")

    plex_names = [s["name"] for s in plex_servers]
    jf_names = [s["name"] for s in jellyfin_servers]
    emby_names = [s["name"] for s in emby_servers]
    all_names = plex_names + jf_names + emby_names

    sync_flags_present = any(
        env.get(k) for k in LEGACY_ENV_VARS if k.startswith("SYNC_FROM_")
    )
    if sync_flags_present:
        sync_to_by_server = _build_sync_to(env, plex_names, jf_names, emby_names)
    else:
        sync_to_by_server = {
            src: [dst for dst in all_names if dst != src] for src in all_names
        }

    for server in plex_servers + jellyfin_servers + emby_servers:
        targets = sync_to_by_server.get(server["name"])
        if targets:
            server["sync_to"] = targets

    if plex_servers:
        out["plex"] = plex_servers
    elif (plex_tokens := _env_as_list(env.get("PLEX_TOKEN"))):
        # A token without a base URL is an override for an already-defined
        # YAML Plex server. The settings model resolves whether there is
        # exactly one eligible target after all higher-priority sources merge.
        out["_legacy_plex_token_override"] = plex_tokens
    if jellyfin_servers:
        out["jellyfin"] = jellyfin_servers
    if emby_servers:
        out["emby"] = emby_servers

    user_pairs = _parse_dict_mapping(env.get("USER_MAPPING"))
    user_mappings = _build_legacy_mappings(user_pairs, all_names, "username")
    if user_mappings:
        out["user_mappings"] = user_mappings

    lib_pairs = _parse_dict_mapping(env.get("LIBRARY_MAPPING"))
    library_mappings = _build_legacy_mappings(lib_pairs, all_names, "library")
    if library_mappings:
        out["library_mappings"] = library_mappings

    return out


class LegacyEnvSettingsSource(PydanticBaseSettingsSource):
    """
    Pydantic settings source that reads a legacy .env file (with old-format
    variable names) and translates them into new-format field values on
    every load. Process-level environment values for the same legacy names
    take precedence over the file, including when the process value is empty.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        env_path: LegacyEnvPath,
        env_file_encoding: str | None = None,
    ) -> None:
        super().__init__(settings_cls)
        self._env_path = env_path
        self._env_file_encoding = env_file_encoding
        self._field_data = self._load()

    def _load(self) -> dict[str, Any]:
        env: dict[str, str | None] = read_legacy_env(
            self._env_path,
            encoding=self._env_file_encoding,
        )
        resolved = resolve_legacy_env(env)
        if not resolved:
            return {}
        return legacy_env_to_field_dict(resolved)

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        if field_name in self._field_data:
            return self._field_data[field_name], field_name, False
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._field_data
