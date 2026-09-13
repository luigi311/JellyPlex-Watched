# JellyPlex-Watched

[![Codacy Badge](https://app.codacy.com/project/badge/Grade/26b47c5db63942f28f02f207f692dc85)](https://www.codacy.com/gh/luigi311/JellyPlex-Watched/dashboard?utm_source=github.com&utm_medium=referral&utm_content=luigi311/JellyPlex-Watched&utm_campaign=Badge_Grade)

Sync watched between jellyfin, plex and emby locally

## Description

Keep in sync all your users watched history between jellyfin, plex and emby servers locally. This uses file names and provider ids to find the correct episode/movie between the two. This is not perfect but it works for most cases. You can use this for as many servers as you want by entering multiple options in the config.

## Features

### Plex

- \[x] Match via filenames
- \[x] Match via provider ids
- \[x] Map usernames
- \[x] Use single login
- \[x] One way/multi way sync
- \[x] Sync watched
- \[x] Sync in progress
- \[ ] Sync view dates

### Jellyfin

- \[x] Match via filenames
- \[x] Match via provider ids
- \[x] Map usernames
- \[x] Use single login
- \[x] One way/multi way sync
- \[x] Sync watched
- \[x] Sync in progress
- \[x] Sync view dates


### Emby

- \[x] Match via filenames
- \[x] Match via provider ids
- \[x] Map usernames
- \[x] Use single login
- \[x] One way/multi way sync
- \[x] Sync watched
- \[x] Sync in progress
- \[x] Sync view dates


## Configuration

Full list of configuration options can be found in the [.env.sample](.env.sample)

Credentials may be stored in YAML or supplied through supported environment
variables; environment values override matching YAML values. YAML credentials
are plaintext, so keep `config.yaml` restricted to the application user and
never commit it. Docker secret files are not loaded automatically; inject
secret values through the supported environment variables or create a protected
YAML file.

New-style environment overrides use the `JPW_` prefix and Pydantic's normal
JSON syntax for list values, such as `JPW_WHITELIST_USERS='["alice", "bob"]'`.
Existing unprefixed legacy variables, including comma-separated lists, remain
supported during the migration.

Configuration sources are applied in this order, from highest to lowest:
explicit constructor values, `JPW_` process variables, `JPW_` values in the
selected dotenv file, legacy process variables, legacy values in the selected
dotenv file, the selected YAML file, and field defaults. `ENV_FILE` and
`YAML_FILE` continue to select the dotenv and YAML paths.

For new-style values, an absent, empty, or valueless entry inherits from the
next source. Use JSON `[]` when an empty list should replace a YAML list;
malformed JSON is rejected. Legacy empty and valueless entries remain unset
after process/file precedence is resolved and do not fall back to the file.

## Installation

### Baremetal

- [Install uv](https://docs.astral.sh/uv/getting-started/installation/)

- Create a .env file similar to .env.sample; fill in baseurls and tokens, **remember to uncomment anything you wish to use** (e.g., user mapping, library mapping, black/whitelist, etc.). If you want to store your .env file anywhere else or under a different name you can use ENV_FILE variable to specify the location.

- Run

  ```bash
  uv run main.py
  ```

  ```bash
  ENV_FILE="Test.env" uv run main.py
  ```

### Docker

- Build docker image

  ```bash
  docker build -t jellyplex-watched .
  ```

- or use pre-built image

  ```bash
  docker pull luigi311/jellyplex-watched:latest
  ```

#### With variables

- Run

  ```bash
  docker run --rm -it -e PLEX_TOKEN='SuperSecretToken' luigi311/jellyplex-watched:latest
  ```

To replace credentials for servers already defined in YAML, use a named JSON
map such as `JPW_SERVER_TOKENS='{"plex-main":"replacement-token"}'`. The
server name must match exactly; the replacement keeps its URL, sync directions,
and mappings. A Plex replacement selects token authentication and clears the
username/password/server name fields. A legacy `PLEX_TOKEN` without
`PLEX_BASEURL` is supported when exactly one YAML Plex server exists.

#### With .env

- Create a .env file similar to .env.sample and set the variables to match your setup

- Run

  ```bash
   docker run --rm -it -v "$(pwd)/.env:/app/.env" luigi311/jellyplex-watched:latest
  ```

## Troubleshooting/Issues

- Jellyfin

  - Attempt to decode JSON with unexpected mimetype, make sure you enable remote access or add your docker subnet to lan networks in jellyfin settings

- Configuration
  - Do not use quotes around variables in docker compose
  - If you are not running all 3 supported servers, that is, Plex, Jellyfin, and Emby simultaneously, make sure to comment out the server url and token of the server you aren't using.

## Contributing

I am open to receiving pull requests. If you are submitting a pull request, please make sure run it locally for a day or two to make sure it is working as expected and stable.

## License

This is currently under the GNU General Public License v3.0.
