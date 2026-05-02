"""
Configuration models for jellyplex-watched.

Loads configuration from a YAML file (default: config.yaml) into a fully
validated AppSettings object. Server references, user references, and sync
rule consistency are all checked at load time so misconfigurations fail
loudly instead of producing confusing runtime errors.

Sync direction model:
    Direction is expressed the same way at every level: "X pushes to Y."
    Each server has a `sync_to: list[str]` of other server names it pushes
    watch state to. Per-user `sync_rules` (and per-library
    `library_sync_rules`) follow the same shape — `from` server pushes to
    `to` server for the listed users/libraries. Bidirectional sync is
    expressed by listing the relationship in both directions, whether at
    the server level (each server in the other's sync_to) or the rule
    level (two rules with from/to swapped).

    Rules are purely additive: a matching rule enables sync for a
    (user, from, to) or (library, from, to) triple even when the
    server-level config wouldn't. Rules cannot suppress a direction the
    server-level config enables — for that, use the global
    blacklist_users / blacklist_libraries (or whitelist_*) lists, which
    are checked before any rule or server-level decision.

Identity model:
    A user/library "identity" (canonical) carries a list of aliases —
    (server, name) pairs telling the sync engine how that identity is
    known on each server. A canonical may have multiple aliases on the
    same server (e.g. a single Plex account that fans out to several
    Jellyfin users). Use AppSettings.lookup_user / lookup_library /
    sync_targets_for_user / sync_targets_for_library at runtime; the
    underlying lists are pre-indexed for O(1) access.

    Users do NOT have to be declared in user_mappings to be synced. If a
    user isn't found in user_mappings, the sync engine falls back to
    matching by identical username across servers (so 'test123' on Plex
    syncs to 'test123' on Jellyfin without any explicit config). Declare
    user_mappings only when usernames differ across servers, when one
    identity fans out to multiple users on a server, or when you need
    per-user sync_rules.

Backward compatibility:
    Legacy .env values are parsed on every load and override the YAML.
    On first run, a config.yaml is auto-generated from the .env. Legacy
    USER_MAPPING / LIBRARY_MAPPING dicts don't record which server uses
    which name, so the migration adds *both* names as aliases on *every*
    server — over-broad but correct. Users can prune the YAML afterward.

Settings priority (highest to lowest):
    1. Explicit kwargs to AppSettings(...)
    2. Standard env vars / .env entries matching new field names
    3. Legacy .env entries (translated to new fields each load)
    4. config.yaml
    5. Field defaults
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

import yaml
from dotenv import dotenv_values
from loguru import logger
from pydantic import (
    BaseModel,
    Field,
    PrivateAttr,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from src.functions import get_env_value
from src.legacy_settings import (
    LEGACY_ENV_VARS,
    LegacyEnvSettingsSource,
    legacy_env_to_field_dict,
)

# ---------------------------------------------------------------------------
# Server configurations
# ---------------------------------------------------------------------------


class _ServerBase(BaseModel):
    name: str = Field(
        ...,
        description="User-defined identifier, unique across all servers.",
    )
    baseurl: str = Field(..., description="Server base URL, e.g. http://plex.lan:32400")
    sync_to: list[str] = Field(
        default_factory=list,
        description=(
            "Names of other servers this one pushes watch state to. "
            "For bidirectional sync, list each server in the other's sync_to. "
            "Leave empty to make this a read-only source (it can be a sync "
            "target, but won't push state outward)."
        ),
    )

    @field_validator("baseurl")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


class PlexSettings(_ServerBase):
    """
    Plex authentication: either a token (preferred) OR a username/password/
    servername triple. Validators ensure exactly one path is fully populated.
    """

    token: SecretStr | None = None
    username: str | None = None
    password: SecretStr | None = None
    servername: str | None = None
    ssl_bypass: bool = False

    @model_validator(mode="after")
    def _require_some_auth(self) -> "PlexSettings":
        has_token = self.token is not None
        has_userpass = (
            self.username is not None
            and self.password is not None
            and self.servername is not None
        )

        if has_token and has_userpass:
            raise ValueError(
                f"Plex server '{self.name}' must use either 'token' or "
                "the 'username'/'password'/'servername' triple, not both."
            )

        if not has_token and not has_userpass:
            raise ValueError(
                f"Plex server '{self.name}' needs either a 'token' or "
                "the 'username'/'password'/'servername' triple."
            )
        return self


class JellyfinSettings(_ServerBase):
    token: SecretStr = Field(...)


class EmbySettings(_ServerBase):
    token: SecretStr = Field(...)


# ---------------------------------------------------------------------------
# User and library identities
# ---------------------------------------------------------------------------


class UserAlias(BaseModel):
    server: str = Field(..., description="Name of a configured server.")
    username: str = Field(..., description="Username of this person on that server.")


class UserMapping(BaseModel):
    canonical: str = Field(
        ...,
        description="Internal identifier for this user (used in logs and sync_rules).",
    )
    aliases: list[UserAlias] = Field(
        ...,
        min_length=1,
        description=(
            "How this user is identified across servers. Multiple aliases on "
            "the same server are allowed for one-to-many sync."
        ),
    )


class LibraryAlias(BaseModel):
    server: str
    library: str


class LibraryMapping(BaseModel):
    canonical: str
    aliases: list[LibraryAlias] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Sync rules (per-user / per-library overrides)
#
# Rules are purely directional: "for these users, server `from` pushes to
# server `to`". Bidirectional is expressed by writing two rules. This
# matches the server-level sync_to model exactly so users only learn one
# concept.
# ---------------------------------------------------------------------------


class SyncRule(BaseModel):
    """
    Override the default sync behavior for a specific subset of users
    on a specific (from -> to) server pair. For bidirectional sync write
    two rules.

    Use users=["*"] to apply to all users. Names listed here may either be
    user_mappings.canonical values, or literal usernames that exist on
    both `from` and `to` servers (the implicit same-username case). The
    'from_' field is aliased to 'from' in YAML/JSON because 'from' is a
    reserved Python keyword.
    """

    users: list[str] = Field(
        ...,
        min_length=1,
        description=(
            'List of canonical usernames or literal usernames, or ["*"] for all users.'
        ),
    )
    from_: str = Field(..., alias="from", description="Source server name.")
    to: str = Field(..., description="Destination server name.")

    model_config = {"populate_by_name": True}


class LibrarySyncRule(BaseModel):
    libraries: list[str] = Field(..., min_length=1)
    from_: str = Field(..., alias="from")
    to: str = Field(...)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Top-level application settings
# ---------------------------------------------------------------------------


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        yaml_file="config.yaml",
        yaml_file_encoding="utf-8",
        nested_model_default_partial_update=True,
        extra="forbid",
    )

    # --- operational knobs --------------------------------------------------
    dryrun: bool = True
    debug_level: Literal["INFO", "DEBUG", "TRACE"] = "INFO"
    run_only_once: bool = False
    sleep_duration: int = 3600
    log_file: Path = Path("log.log")
    mark_file: Path = Path("mark.log")
    request_timeout: int = 300
    max_threads: Annotated[int, Field(ge=1, le=128)] = 1
    generate_guids: bool = True
    generate_locations: bool = True

    # --- filtering ----------------------------------------------------------
    blacklist_libraries: list[str] = []
    whitelist_libraries: list[str] = []
    blacklist_library_types: list[str] = []
    whitelist_library_types: list[str] = []
    blacklist_users: list[str] = []
    whitelist_users: list[str] = []

    # --- mappings -----------------------------------------------------------
    user_mappings: list[UserMapping] = []
    library_mappings: list[LibraryMapping] = []

    # --- per-user / per-library sync overrides ------------------------------
    sync_rules: list[SyncRule] = []
    library_sync_rules: list[LibrarySyncRule] = []

    # --- servers ------------------------------------------------------------
    plex: list[PlexSettings] = []
    jellyfin: list[JellyfinSettings] = []
    emby: list[EmbySettings] = []

    # ------------------------------------------------------------------ #
    # Pre-built indexes (populated by model_post_init)                    #
    #                                                                     #
    # These exist as PrivateAttr because BaseSettings with extra="forbid" #
    # rejects attribute assignment that doesn't correspond to a declared  #
    # field — that's exactly what cached_property tries to do.            #
    # PrivateAttr is the supported escape hatch.                          #
    # ------------------------------------------------------------------ #

    _all_servers: list[_ServerBase] = PrivateAttr(default_factory=list)
    _server_names: set[str] = PrivateAttr(default_factory=set)
    _user_canonicals: set[str] = PrivateAttr(default_factory=set)
    _library_canonicals: set[str] = PrivateAttr(default_factory=set)
    _user_index: dict[tuple[str, str], str] = PrivateAttr(default_factory=dict)
    _library_index: dict[tuple[str, str], str] = PrivateAttr(default_factory=dict)
    _user_aliases_by_canonical: dict[str, list[UserAlias]] = PrivateAttr(
        default_factory=dict
    )
    _library_aliases_by_canonical: dict[str, list[LibraryAlias]] = PrivateAttr(
        default_factory=dict
    )
    _server_sync_to_index: dict[str, set[str]] = PrivateAttr(default_factory=dict)
    _user_rule_index: set[tuple[str, str, str]] = PrivateAttr(default_factory=set)
    _library_rule_index: set[tuple[str, str, str]] = PrivateAttr(default_factory=set)
    _rule_directions: set[tuple[str, str]] = PrivateAttr(default_factory=set)
    _whitelist_users_lc: set[str] = PrivateAttr(default_factory=set)
    _blacklist_users_lc: set[str] = PrivateAttr(default_factory=set)
    _whitelist_libraries_lc: set[str] = PrivateAttr(default_factory=set)
    _blacklist_libraries_lc: set[str] = PrivateAttr(default_factory=set)
    _whitelist_library_types_lc: set[str] = PrivateAttr(default_factory=set)
    _blacklist_library_types_lc: set[str] = PrivateAttr(default_factory=set)
    _user_identity_names: dict[str, set[str]] = PrivateAttr(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """
        Build all derived indexes from the validated config.

        Runs after every validator, so it sees a fully-checked model.
        """
        self._all_servers = [*self.plex, *self.jellyfin, *self.emby]
        self._server_names = {s.name for s in self._all_servers}
        self._user_canonicals = {u.canonical for u in self.user_mappings}
        self._library_canonicals = {lib.canonical for lib in self.library_mappings}

        # User/library names are matched case-insensitively: servers report
        # usernames and library names with inconsistent casing, while the
        # config is written with whatever casing the user prefers. Server
        # names are NOT lowercased — they're internal identifiers only ever
        # compared within the config.
        #
        # Index keys store the lowercased name; the canonical *value* is
        # lowercased too, so it round-trips against the lowercased rule
        # indexes and lowercased lookup arguments below.
        self._user_index = {
            (alias.server, alias.username.lower()): u.canonical.lower()
            for u in self.user_mappings
            for alias in u.aliases
        }
        self._library_index = {
            (alias.server, alias.library.lower()): lib.canonical.lower()
            for lib in self.library_mappings
            for alias in lib.aliases
        }

        # Keyed by lowercased canonical to match the lowercased values stored
        # in _user_index / _library_index. The alias objects themselves are
        # kept intact (original casing) so sync_targets_for_* returns the
        # real target names the servers expect.
        self._user_aliases_by_canonical = {
            u.canonical.lower(): u.aliases for u in self.user_mappings
        }
        self._library_aliases_by_canonical = {
            lib.canonical.lower(): lib.aliases for lib in self.library_mappings
        }

        self._server_sync_to_index = {s.name: set(s.sync_to) for s in self._all_servers}

        # Pre-expand wildcards so the runtime check is a single set lookup.
        # Note: wildcards only expand to declared canonicals; implicit
        # same-username users are matched by literal name in should_sync_user.
        # User names (canonicals from "*" expansion, or literal usernames)
        # are lowercased; from_/to are server names and stay as-is.
        user_rules: set[tuple[str, str, str]] = set()
        for rule in self.sync_rules:
            users = (
                {c.lower() for c in self._user_canonicals}
                if rule.users == ["*"]
                else {u.lower() for u in rule.users}
            )
            for user in users:
                user_rules.add((user, rule.from_, rule.to))
        self._user_rule_index = user_rules

        library_rules: set[tuple[str, str, str]] = set()
        for rule in self.library_sync_rules:
            libs = (
                {c.lower() for c in self._library_canonicals}
                if rule.libraries == ["*"]
                else {lib.lower() for lib in rule.libraries}
            )
            for lib in libs:
                library_rules.add((lib, rule.from_, rule.to))
        self._library_rule_index = library_rules

        # Project rule indexes onto (from, to) so should_sync_server can
        # tell in O(1) whether any user or library rule enables a given
        # direction independently of server-level sync_to.
        self._rule_directions = {
            (from_, to) for (_, from_, to) in self._user_rule_index
        } | {(from_, to) for (_, from_, to) in self._library_rule_index}

        # Lowercased filter sets for case-insensitive blacklist/whitelist
        # checks (the public lists keep their original casing for display).
        self._whitelist_users_lc = {u.lower() for u in self.whitelist_users}
        self._blacklist_users_lc = {u.lower() for u in self.blacklist_users}
        self._whitelist_libraries_lc = {lib.lower() for lib in self.whitelist_libraries}
        self._blacklist_libraries_lc = {lib.lower() for lib in self.blacklist_libraries}
        self._whitelist_library_types_lc = {
            t.lower() for t in self.whitelist_library_types
        }
        self._blacklist_library_types_lc = {
            t.lower() for t in self.blacklist_library_types
        }

        # Map every lowercased user alias/canonical name to the full set of
        # lowercased names that share its canonical identity. This lets the
        # whitelist/blacklist match on identity rather than on the single
        # literal name the user happened to list: if any name belonging to a
        # user's identity is whitelisted, the user (under any of their
        # server-specific names) is allowed.
        self._user_identity_names: dict[str, set[str]] = {}
        for u in self.user_mappings:
            identity_names = {u.canonical.lower()} | {
                a.username.lower() for a in u.aliases
            }
            for name in identity_names:
                # A name should resolve to one identity (validators forbid a
                # (server, username) belonging to two canonicals); union to be
                # safe if the same bare name appears under multiple canonicals.
                self._user_identity_names.setdefault(name, set()).update(identity_names)

    # ------------------------------------------------------------------ #
    # Cross-field validation                                              #
    #                                                                     #
    # Validators run before model_post_init, so they can't use the index #
    # attributes. They compute their own local views instead.            #
    # ------------------------------------------------------------------ #

    def _collect_servers(self) -> list[_ServerBase]:
        return [*self.plex, *self.jellyfin, *self.emby]

    def _collect_server_names(self) -> set[str]:
        return {s.name for s in self._collect_servers()}

    @model_validator(mode="after")
    def _validate_unique_names(self) -> "AppSettings":
        names = [s.name for s in self._collect_servers()]
        dupes = {n for n, c in Counter(names).items() if c > 1}
        if dupes:
            raise ValueError(
                f"Duplicate server names across plex/jellyfin/emby: {sorted(dupes)}. "
                "Each server entry needs a unique 'name'."
            )

        canonicals = [u.canonical for u in self.user_mappings]
        dupes = {c for c, n in Counter(canonicals).items() if n > 1}
        if dupes:
            raise ValueError(
                f"Duplicate user_mappings.canonical values: {sorted(dupes)}"
            )

        lib_canonicals = [lib.canonical for lib in self.library_mappings]
        dupes = {c for c, n in Counter(lib_canonicals).items() if n > 1}
        if dupes:
            raise ValueError(
                f"Duplicate library_mappings.canonical values: {sorted(dupes)}"
            )

        return self

    @model_validator(mode="after")
    def _validate_server_level_sync_to(self) -> "AppSettings":
        names = self._collect_server_names()
        for server in self._collect_servers():
            seen: set[str] = set()
            for target in server.sync_to:
                if target not in names:
                    raise ValueError(
                        f"Server '{server.name}' has sync_to entry '{target}' "
                        f"which is not a configured server. Known: {sorted(names)}"
                    )
                if target == server.name:
                    raise ValueError(f"Server '{server.name}' cannot sync_to itself.")
                if target in seen:
                    raise ValueError(
                        f"Server '{server.name}' has duplicate sync_to entry "
                        f"for '{target}'."
                    )
                seen.add(target)
        return self

    @model_validator(mode="after")
    def _validate_user_aliases(self) -> "AppSettings":
        names = self._collect_server_names()
        # Allow multiple aliases per server within one canonical (fan-out
        # case). Forbid duplicate exact (server, username) within one
        # canonical (a typo, not a feature). Forbid the same (server,
        # username) appearing across *different* canonicals (genuinely
        # ambiguous identity).
        seen_global: dict[tuple[str, str], str] = {}
        for user in self.user_mappings:
            seen_local: set[tuple[str, str]] = set()
            for alias in user.aliases:
                if alias.server not in names:
                    raise ValueError(
                        f"user_mappings[{user.canonical}].aliases references "
                        f"unknown server '{alias.server}'."
                    )
                key = (alias.server, alias.username)
                if key in seen_local:
                    raise ValueError(
                        f"user_mappings[{user.canonical}] has duplicate alias "
                        f"({alias.server}, {alias.username})."
                    )
                seen_local.add(key)
                if key in seen_global and seen_global[key] != user.canonical:
                    raise ValueError(
                        f"User alias ({alias.server}, {alias.username}) is "
                        f"claimed by both '{seen_global[key]}' and "
                        f"'{user.canonical}'. A given (server, username) can "
                        "belong to at most one canonical user."
                    )
                seen_global[key] = user.canonical
        return self

    @model_validator(mode="after")
    def _validate_library_aliases(self) -> "AppSettings":
        names = self._collect_server_names()
        seen_global: dict[tuple[str, str], str] = {}
        for lib in self.library_mappings:
            seen_local: set[tuple[str, str]] = set()
            for alias in lib.aliases:
                if alias.server not in names:
                    raise ValueError(
                        f"library_mappings[{lib.canonical}].aliases references "
                        f"unknown server '{alias.server}'."
                    )
                key = (alias.server, alias.library)
                if key in seen_local:
                    raise ValueError(
                        f"library_mappings[{lib.canonical}] has duplicate alias "
                        f"({alias.server}, {alias.library})."
                    )
                seen_local.add(key)
                if key in seen_global and seen_global[key] != lib.canonical:
                    raise ValueError(
                        f"Library alias ({alias.server}, {alias.library}) is "
                        f"claimed by both '{seen_global[key]}' and "
                        f"'{lib.canonical}'. A given (server, library) can "
                        "belong to at most one canonical library."
                    )
                seen_global[key] = lib.canonical
        return self

    @model_validator(mode="after")
    def _validate_sync_rules(self) -> "AppSettings":
        names = self._collect_server_names()
        canonicals = {u.canonical for u in self.user_mappings}

        # canonical -> set of servers it has aliases on
        alias_servers: dict[str, set[str]] = {}
        for u in self.user_mappings:
            alias_servers.setdefault(u.canonical, set()).update(
                a.server for a in u.aliases
            )

        seen_triples: set[tuple[str, str, str]] = set()

        for i, rule in enumerate(self.sync_rules):
            if rule.from_ not in names:
                raise ValueError(f"sync_rules[{i}].from='{rule.from_}' is unknown.")
            if rule.to not in names:
                raise ValueError(f"sync_rules[{i}].to='{rule.to}' is unknown.")
            if rule.from_ == rule.to:
                raise ValueError(f"sync_rules[{i}] has from == to ('{rule.from_}').")

            target_users = list(canonicals) if rule.users == ["*"] else rule.users

            for user in target_users:
                # Names that aren't canonicals are accepted as literal
                # usernames (implicit same-username case). We can't
                # validate at config-load time that the user actually
                # exists on both servers — the sync engine will skip them
                # at runtime if they don't.
                if user in canonicals:
                    user_servers = alias_servers.get(user, set())
                    if rule.from_ not in user_servers:
                        raise ValueError(
                            f"sync_rules[{i}]: user '{user}' has no alias on "
                            f"server '{rule.from_}'."
                        )
                    if rule.to not in user_servers:
                        raise ValueError(
                            f"sync_rules[{i}]: user '{user}' has no alias on "
                            f"server '{rule.to}'."
                        )

                triple = (user, rule.from_, rule.to)
                if triple in seen_triples:
                    raise ValueError(
                        f"sync_rules has duplicate coverage for user='{user}', "
                        f"from='{rule.from_}', to='{rule.to}'. "
                        "Each (user, from, to) triple may appear in at most one rule."
                    )
                seen_triples.add(triple)

        return self

    @model_validator(mode="after")
    def _validate_library_sync_rules(self) -> "AppSettings":
        names = self._collect_server_names()
        lib_canonicals = {lib.canonical for lib in self.library_mappings}

        alias_servers: dict[str, set[str]] = {}
        for lib in self.library_mappings:
            alias_servers.setdefault(lib.canonical, set()).update(
                a.server for a in lib.aliases
            )

        seen_triples: set[tuple[str, str, str]] = set()

        for i, rule in enumerate(self.library_sync_rules):
            if rule.from_ not in names:
                raise ValueError(
                    f"library_sync_rules[{i}].from='{rule.from_}' is unknown."
                )
            if rule.to not in names:
                raise ValueError(f"library_sync_rules[{i}].to='{rule.to}' is unknown.")
            if rule.from_ == rule.to:
                raise ValueError(
                    f"library_sync_rules[{i}] has from == to ('{rule.from_}')."
                )

            target_libs = (
                list(lib_canonicals) if rule.libraries == ["*"] else rule.libraries
            )

            for lib in target_libs:
                # Same logic as sync_rules: unknown names are accepted as
                # literal library names (implicit same-name case).
                if lib in lib_canonicals:
                    lib_servers = alias_servers.get(lib, set())
                    if rule.from_ not in lib_servers:
                        raise ValueError(
                            f"library_sync_rules[{i}]: library '{lib}' has no alias "
                            f"on server '{rule.from_}'."
                        )
                    if rule.to not in lib_servers:
                        raise ValueError(
                            f"library_sync_rules[{i}]: library '{lib}' has no alias "
                            f"on server '{rule.to}'."
                        )

                triple = (lib, rule.from_, rule.to)
                if triple in seen_triples:
                    raise ValueError(
                        f"library_sync_rules has duplicate coverage for "
                        f"library='{lib}', from='{rule.from_}', to='{rule.to}'."
                    )
                seen_triples.add(triple)

        return self

    # ------------------------------------------------------------------ #
    # Public accessors                                                    #
    # ------------------------------------------------------------------ #

    @property
    def all_servers(self) -> tuple[_ServerBase, ...]:
        """
        Every configured server (plex + jellyfin + emby), in declaration
        order. Returned as a tuple so callers can't mutate the underlying
        index.
        """
        return tuple(self._all_servers)

    # ------------------------------------------------------------------ #
    # Lookup API for the sync engine                                      #
    # ------------------------------------------------------------------ #

    def lookup_user(self, server: str, username: str) -> str | None:
        """Find the canonical user for a (server, username) pair, or None."""
        return self._user_index.get((server, username.lower()))

    def lookup_library(self, server: str, library: str) -> str | None:
        """Find the canonical library for a (server, library) pair, or None."""
        return self._library_index.get((server, library.lower()))

    def is_user_allowed(self, username: str) -> bool:
        """
        Check the global user blacklist/whitelist.

        Whitelist takes precedence: if non-empty, the user must appear in it.
        Otherwise the user must not appear in the blacklist. Matching is
        case-insensitive AND identity-aware: if the user is declared in
        user_mappings, the check considers *every* name belonging to their
        canonical identity (canonical + all aliases on all servers). So
        whitelisting any one of a user's names (e.g. the Plex name) allows
        that user even when a server reports them under a different mapped
        name (e.g. the Jellyfin name).
        """
        username = username.lower()
        # All names that share this user's identity (falls back to just the
        # given name when the user isn't in user_mappings).
        identity = self._user_identity_names.get(username, {username})

        if self._whitelist_users_lc:
            return bool(identity & self._whitelist_users_lc)
        return not (identity & self._blacklist_users_lc)

    def is_library_type_allowed(self, library_type: str | list[str]) -> bool:
        """
        Check the global library-type blacklist/whitelist (e.g. 'movie',
        'show').

        Accepts either a single type string or an iterable of types (some
        servers report a library as having multiple item types). Matching
        is case-insensitive.

        Whitelist takes precedence: if non-empty, *every* given type must
        appear in it. Otherwise the library is rejected only if *any* given
        type appears in the blacklist. A library with no types is always
        allowed.
        """
        if isinstance(library_type, str):
            types = {library_type.lower()}
        else:
            types = {t.lower() for t in library_type}

        if not types:
            return True

        if self._whitelist_library_types_lc:
            return types <= self._whitelist_library_types_lc
        return types.isdisjoint(self._blacklist_library_types_lc)

    def should_sync_server(self, from_server: str, to_server: str) -> bool:
        """
        Decide whether `from_server` has any reason to sync to `to_server`.

        Returns True if either:
          - `from_server.sync_to` includes `to_server` (server-level
            config enables the direction for all users/libraries by
            default), or
          - at least one sync_rules or library_sync_rules entry enables
            this direction for some user or library (the direction is
            rule-only — server-level wouldn't enable it, but specific
            users or libraries opt in).

        This is a coarse "is anything happening here" check, intended for
        the sync engine to skip whole server pairs cheaply. It does NOT
        guarantee any specific user or library will actually sync —
        callers still need should_sync_user / should_sync_library for
        per-item decisions, since the global blacklist/whitelist and
        per-item rule coverage are checked there.

        Returns False if either server name is unknown or if the two
        names are equal.
        """
        if from_server not in self._server_names or to_server not in self._server_names:
            return False
        if from_server == to_server:
            return False
        if to_server in self._server_sync_to_index.get(from_server, set()):
            return True
        return (from_server, to_server) in self._rule_directions

    def should_sync_user(
        self,
        username: str,
        from_server: str,
        to_server: str,
    ) -> bool:
        """
        Decide whether `username` (as known on `from_server`) should have
        their watch state pushed to `to_server`.

        Logic:
          1. If the user is filtered out by the blacklist/whitelist, return False.
          2. If a sync_rules entry covers this (user, from, to) — checking
             both the canonical name (if mapped) and the literal username —
             return True. Rules are additive: they can enable a direction
             the server-level config doesn't have, but cannot suppress one
             it does.
          3. Otherwise, fall back to the server-level decision: does
             `from_server.sync_to` include `to_server`?

        The user does NOT need to be declared in user_mappings. A user
        named 'test123' on both servers will sync if from_server pushes
        to to_server, with no further configuration.
        """
        if not self.is_user_allowed(username):
            return False

        username_lc = username.lower()
        canonical = self._user_index.get((from_server, username_lc))

        # Per-user rule check. Match against the canonical name if one
        # exists, and also against the literal username for the implicit
        # same-username case (where a rule names a user that isn't in
        # user_mappings).
        if canonical is not None and (
            (canonical, from_server, to_server) in self._user_rule_index
        ):
            return True
        if (username_lc, from_server, to_server) in self._user_rule_index:
            return True

        # Server-level fallback.
        return to_server in self._server_sync_to_index.get(from_server, set())

    def should_sync_library(
        self,
        library: str,
        from_server: str,
        to_server: str,
    ) -> bool:
        """
        Decide whether items from `library` on `from_server` should be
        pushed to `to_server`. Same logic shape as should_sync_user:
        blacklist/whitelist first, then per-library rules (canonical or
        literal), then server-level sync_to.
        """
        library_lc = library.lower()
        if (
            self._whitelist_libraries_lc
            and library_lc not in self._whitelist_libraries_lc
        ):
            return False
        if library_lc in self._blacklist_libraries_lc:
            return False

        canonical = self._library_index.get((from_server, library_lc))

        if canonical is not None and (
            (canonical, from_server, to_server) in self._library_rule_index
        ):
            return True
        if (library_lc, from_server, to_server) in self._library_rule_index:
            return True

        return to_server in self._server_sync_to_index.get(from_server, set())

    def sync_targets_for_user(
        self,
        source_server: str,
        source_username: str,
        target_server: str,
    ) -> list[str]:
        """
        Return all usernames on `target_server` that correspond to the user
        watching as `source_username` on `source_server`.

        If the user is declared in user_mappings, returns every alias on
        the target server (may be multiple — one source identity fanning
        out to multiple target users, e.g. shared family Plex →
        individual Jellyfin users).

        If the user is NOT in user_mappings, returns [source_username] as
        the implicit same-username fallback. The sync engine should still
        verify the target user actually exists before pushing.

        Returns [] only when the user is mapped but has no alias on the
        target server.
        """
        canonical = self._user_index.get((source_server, source_username.lower()))
        if canonical is None:
            # Implicit same-username fallback.
            return [source_username]
        return [
            a.username
            for a in self._user_aliases_by_canonical.get(canonical, [])
            if a.server == target_server
        ]

    def sync_targets_for_library(
        self,
        source_server: str,
        source_library: str,
        target_server: str,
    ) -> list[str]:
        """
        Return all library names on `target_server` that correspond to the
        item being from `source_library` on `source_server`.

        Mirrors sync_targets_for_user: undeclared libraries fall back to
        the same name on the target server.
        """
        canonical = self._library_index.get((source_server, source_library.lower()))
        if canonical is None:
            return [source_library]
        return [
            a.library
            for a in self._library_aliases_by_canonical.get(canonical, [])
            if a.server == target_server
        ]

    # ------------------------------------------------------------------ #
    # Settings source order                                               #
    # ------------------------------------------------------------------ #

    _legacy_env_path: ClassVar[Path] = Path(".env")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            LegacyEnvSettingsSource(settings_cls, cls._legacy_env_path),
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


# ---------------------------------------------------------------------------
# YAML migration (one-shot, just generates a starter config.yaml)
# ---------------------------------------------------------------------------


def _dump_for_yaml(model: Any) -> Any:
    """
    Serialize an AppSettings to a plain dict for YAML output.

    Only explicitly-set fields are emitted (defaults aren't serialized,
    so the generated YAML stays sparse and readable), and they're
    emitted in class-declaration order rather than the order pydantic
    happened to populate them — so the generated config matches the
    grouping in AppSettings (operational knobs, filtering, mappings,
    sync rules, servers). SecretStr is unwrapped to plaintext.
    """
    if isinstance(model, BaseModel):
        set_fields = model.model_fields_set
        out: dict[str, Any] = {}
        for name in type(model).model_fields:
            if name in set_fields:
                out[name] = _dump_for_yaml(getattr(model, name))
        return out
    if isinstance(model, SecretStr):
        return model.get_secret_value()
    if isinstance(model, list):
        return [_dump_for_yaml(item) for item in model]
    if isinstance(model, Path):
        return str(model)
    return model


_MIGRATION_HEADER = """\
# Auto-generated by jellyplex-watched from your legacy .env file.
#
# Your .env continues to work — its values are parsed on every run and
# override matching entries in this file. Once you've reviewed and are
# happy with this config, delete the .env to fully migrate to the new
# format. New features (per-user sync_rules, named server references,
# more granular controls) are only available via this YAML file.
#
# NOTE on user_mappings / library_mappings:
#   The legacy USER_MAPPING / LIBRARY_MAPPING format didn't record which
#   server uses which name. To stay safe, every alternate name has been
#   added on every server. You can prune entries that don't actually apply
#   to a given server — e.g. if "Shows" is only the Plex name and "TV
#   Shows" is only the Jellyfin name, remove the irrelevant aliases.
#
#   You can also delete user_mappings entries entirely for users whose
#   username is identical on every server — the sync engine will match
#   them automatically.
#
# Tokens are stored in plaintext here. Set restrictive permissions:
#     chmod 600 config.yaml
"""


def _migrate_env_to_yaml(env_path: Path, yaml_path: Path) -> bool:
    """
    Read legacy .env, write a fresh config.yaml. Returns True on success.

    Failures are logged but not raised — the caller continues with env-
    based config so the user's setup keeps working.
    """
    try:
        # Load the .env into a dict and resolve every legacy var through
        # get_env_value so process env overrides the file, exactly like
        # the LegacyEnvSettingsSource does at runtime.
        env = dict(dotenv_values(env_path))
        resolved: dict[str, str | None] = {}
        for key in LEGACY_ENV_VARS:
            value = get_env_value(env, key)
            if value is not None:
                resolved[key] = value

        if not resolved:
            return False
        if not (set(resolved.keys()) & LEGACY_ENV_VARS):
            return False

        field_dict = legacy_env_to_field_dict(resolved)

        # Validate purely from field_dict. We must NOT go through the normal
        # AppSettings(...) construction here, because that re-runs the full
        # settings source chain — including the base class's
        # LegacyEnvSettingsSource, which is hardcoded to read ".env". That
        # would merge the real .env into the migration output even though we
        # were asked to migrate a different env_file. Suppress every external
        # source so only field_dict (derived from THIS env_file) is used.
        class _MigrationModel(AppSettings):
            # model_config is MERGED across inheritance in pydantic-settings,
            # so the base AppSettings's yaml_file/yaml_file_encoding survive
            # unless explicitly cleared. We have no YAML source here (see
            # settings_customise_sources below), so set them to None to avoid
            # the "config key ignored" UserWarning.
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
                # init_settings carries the kwargs we pass below; everything
                # else (env vars, .env, legacy .env, YAML) is intentionally
                # excluded so the migration reflects only this env_file.
                return (init_settings,)

        settings = _MigrationModel(**field_dict)
        data = _dump_for_yaml(settings)

        with yaml_path.open("w", encoding="utf-8") as f:
            f.write(_MIGRATION_HEADER)
            f.write("\n")
            yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)

        try:
            os.chmod(yaml_path, 0o600)
        except OSError as e:
            logger.warning(f"Could not set permissions on {yaml_path}: {e}")

        return True
    except Exception as e:
        logger.warning(
            f"Auto-migration from {env_path} to {yaml_path} failed: {e}. "
            "Your existing .env config still works; you can migrate manually later.",
        )
        return False


# ---------------------------------------------------------------------------
# Convenience entrypoint
# ---------------------------------------------------------------------------


def load_settings(
    env_file: str | Path | None = None,
    yaml_file: str | Path | None = None,
    auto_migrate: bool = True,
) -> AppSettings:
    """
    Load settings.

    `env_file` is the path to the legacy .env file. Callers should resolve it
    (e.g. honoring an ENV_FILE environment variable) and pass it in; when None,
    it falls back to ENV_FILE / ".env" for backward compatibility. `yaml_file`
    works the same way against YAML_FILE / "config.yaml".

    On every load, the legacy .env (if present) is parsed and its values
    override matching YAML entries — so users on a hybrid setup can keep
    tweaking their .env and see changes immediately. Environment variables
    still take precedence over both.

    On first run after upgrade — if the YAML is missing but a legacy .env
    exists — a config.yaml is also generated as a starter for the new
    format. The .env is never modified.
    """
    if yaml_file is None:
        yaml_file = get_env_value(None, "YAML_FILE", "config.yaml")
    if env_file is None:
        env_file = get_env_value(None, "ENV_FILE", ".env")

    yaml_p = Path(yaml_file)
    env_p = Path(env_file)

    if auto_migrate and not yaml_p.exists() and env_p.exists():
        if _migrate_env_to_yaml(env_p, yaml_p):
            logger.warning(
                f"Generated {yaml_p} from your existing {env_p}. Your .env still works "
                "and overrides matching YAML values; delete it once you're "
                "ready to fully switch to the new config format.",
            )

    class _Configured(AppSettings):
        model_config = SettingsConfigDict(
            yaml_file=str(yaml_p),
            yaml_file_encoding="utf-8",
            nested_model_default_partial_update=True,
            extra="forbid",
        )
        _legacy_env_path: ClassVar[Path] = env_p

    return _Configured()
