from typing import Literal
from loguru import logger

from src.functions import str_to_bool, get_env_value
from src.plex import Plex
from src.jellyfin import Jellyfin
from src.emby import Emby


def jellyfin_emby_server_connection(
    env,
    server_baseurl: str,
    server_token: str,
    server_type: Literal["jellyfin", "emby"],
) -> list[Jellyfin | Emby]:
    servers: list[Jellyfin | Emby] = []
    server: Jellyfin | Emby

    server_baseurls = server_baseurl.split(",")
    server_tokens = server_token.split(",")

    if len(server_baseurls) != len(server_tokens):
        raise Exception(
            f"{server_type.upper()}_BASEURL and {server_type.upper()}_TOKEN must have the same number of entries"
        )

    for i, base_url in enumerate(server_baseurls):
        base_url = base_url.strip()
        if base_url[-1] == "/":
            base_url = base_url[:-1]

        if server_type == "jellyfin":
            server = Jellyfin(
                env=env, base_url=base_url, token=server_tokens[i].strip()
            )
            servers.append(server)

        elif server_type == "emby":
            server = Emby(env=env, base_url=base_url, token=server_tokens[i].strip())
            servers.append(server)
        else:
            raise Exception("Unknown server type")

        logger.debug(f"{server_type} Server {i} info: {server.info()}")

    return servers


def generate_server_connections(env) -> list[Plex | Jellyfin | Emby]:
    servers: list[Plex | Jellyfin | Emby] = []

    plex_baseurl_str: str | None = get_env_value(env, "PLEX_BASEURL", None)
    plex_token_str: str | None = get_env_value(env, "PLEX_TOKEN", None)
    plex_username_str: str | None = get_env_value(env, "PLEX_USERNAME", None)
    plex_password_str: str | None = get_env_value(env, "PLEX_PASSWORD", None)
    plex_servername_str: str | None = get_env_value(env, "PLEX_SERVERNAME", None)
    ssl_bypass = str_to_bool(get_env_value(env, "SSL_BYPASS", "False"))

    if plex_baseurl_str and plex_token_str:
        plex_baseurl = plex_baseurl_str.split(",")
        plex_token = plex_token_str.split(",")

        if len(plex_baseurl) != len(plex_token):
            raise Exception(
                "PLEX_BASEURL and PLEX_TOKEN must have the same number of entries"
            )

        for i, url in enumerate(plex_baseurl):
            server = Plex(
                env,
                base_url=url.strip(),
                token=plex_token[i].strip(),
                user_name=None,
                password=None,
                server_name=None,
                ssl_bypass=ssl_bypass,
            )

            logger.debug(f"Plex Server {i} info: {server.info()}")

            servers.append(server)

    if plex_username_str and plex_password_str and plex_servername_str:
        plex_username = plex_username_str.split(",")
        plex_password = plex_password_str.split(",")
        plex_servername = plex_servername_str.split(",")

        if len(plex_username) != len(plex_password) or len(plex_username) != len(
            plex_servername
        ):
            raise Exception(
                "PLEX_USERNAME, PLEX_PASSWORD and PLEX_SERVERNAME must have the same number of entries"
            )

        for i, username in enumerate(plex_username):
            server = Plex(
                env,
                base_url=None,
                token=None,
                user_name=username.strip(),
                password=plex_password[i].strip(),
                server_name=plex_servername[i].strip(),
                ssl_bypass=ssl_bypass,
            )

            logger.debug(f"Plex Server {i} info: {server.info()}")
            servers.append(server)

    jellyfin_baseurl = get_env_value(env, "JELLYFIN_BASEURL", None)
    jellyfin_token = get_env_value(env, "JELLYFIN_TOKEN", None)
    if jellyfin_baseurl and jellyfin_token:
        servers.extend(
            jellyfin_emby_server_connection(
                env, jellyfin_baseurl, jellyfin_token, "jellyfin"
            )
        )

    emby_baseurl = get_env_value(env, "EMBY_BASEURL", None)
    emby_token = get_env_value(env, "EMBY_TOKEN", None)
    if emby_baseurl and emby_token:
        servers.extend(
            jellyfin_emby_server_connection(env, emby_baseurl, emby_token, "emby")
        )

    return servers
