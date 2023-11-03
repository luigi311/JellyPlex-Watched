# JellyPlex-Watched

[![Codacy Badge](https://app.codacy.com/project/badge/Grade/26b47c5db63942f28f02f207f692dc85)](https://www.codacy.com/gh/luigi311/JellyPlex-Watched/dashboard?utm_source=github.com\&utm_medium=referral\&utm_content=luigi311/JellyPlex-Watched\&utm_campaign=Badge_Grade)

Sync watched between jellyfin and plex locally

## Description

Keep in sync all your users watched history between jellyfin and plex servers locally. This uses file names and provider ids to find the correct episode/movie between the two. This is not perfect but it works for most cases. You can use this for as many servers as you want by entering multiple options in the .env plex/jellyfin section separated by commas.

## Features

### Plex

*   \[x] Match via filenames
*   \[x] Match via provider ids
*   \[x] Map usernames
*   \[x] Use single login
*   \[x] One way/multi way sync
*   \[x] Sync watched
*   \[x] Sync in progress

### Jellyfin

*   \[x] Match via filenames
*   \[x] Match via provider ids
*   \[x] Map usernames
*   \[x] Use single login
*   \[x] One way/multi way sync
*   \[x] Sync watched
*   \[ ] Sync in progress

### Emby

*   \[ ] Match via filenames
*   \[ ] Match via provider ids
*   \[ ] Map usernames
*   \[ ] Use single login
*   \[ ] One way/multi Way sync
*   \[ ] Sync watched
*   \[ ] Sync in progress

## Configuration

```bash
# Global Settings

## Do not mark any shows/movies as played and instead just output to log if they would of been marked.
DRYRUN = "True"

## Additional logging information
DEBUG = "False"

## Debugging level, "info" is default, "debug" is more verbose
DEBUG_LEVEL = "info"

## If set to true then the script will only run once and then exit
RUN_ONLY_ONCE = "False"

## How often to run the script in seconds
SLEEP_DURATION = "3600"

## Log file where all output will be written to
LOGFILE = "log.log"

## Timeout for requests for jellyfin
REQUEST_TIMEOUT = 300

## Map usernames between servers in the event that they are different, order does not matter
## Comma separated for multiple options
USER_MAPPING = { "testuser2": "testuser3", "testuser1":"testuser4" }

## Map libraries between servers in the even that they are different, order does not matter
## Comma separated for multiple options
LIBRARY_MAPPING = { "Shows": "TV Shows", "Movie": "Movies" }

## Blacklisting/Whitelisting libraries, library types such as Movies/TV Shows, and users. Mappings apply so if the mapping for the user or library exist then both will be excluded.
## Comma separated for multiple options
BLACKLIST_LIBRARY = ""
WHITELIST_LIBRARY = ""
BLACKLIST_LIBRARY_TYPE = ""
WHITELIST_LIBRARY_TYPE = ""
BLACKLIST_USERS = ""
WHITELIST_USERS = "testuser1,testuser2"



# Plex

## Recommended to use token as it is faster to connect as it is direct to the server instead of going through the plex servers
## URL of the plex server, use hostname or IP address if the hostname is not resolving correctly
## Comma separated list for multiple servers
PLEX_BASEURL = "http://localhost:32400, https://nas:32400"

## Plex token https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/
## Comma separated list for multiple servers
PLEX_TOKEN = "SuperSecretToken, SuperSecretToken2"

## If not using plex token then use username and password of the server admin along with the servername
## Comma separated for multiple options
#PLEX_USERNAME = "PlexUser, PlexUser2"
#PLEX_PASSWORD = "SuperSecret, SuperSecret2"
#PLEX_SERVERNAME = "Plex Server1, Plex Server2"

## Skip hostname validation for ssl certificates.
## Set to True if running into ssl certificate errors
SSL_BYPASS = "False"


## control the direction of syncing. e.g. SYNC_FROM_PLEX_TO_JELLYFIN set to true will cause the updates from plex
## to be updated in jellyfin. SYNC_FROM_PLEX_TO_PLEX set to true will sync updates between multiple plex servers
SYNC_FROM_PLEX_TO_JELLYFIN = "True"
SYNC_FROM_JELLYFIN_TO_PLEX = "True"
SYNC_FROM_PLEX_TO_PLEX = "True"
SYNC_FROM_JELLYFIN_TO_JELLYFIN = "True"


# Jellyfin

## Jellyfin server URL, use hostname or IP address if the hostname is not resolving correctly
## Comma separated list for multiple servers
JELLYFIN_BASEURL = "http://localhost:8096, http://nas:8096"

## Jellyfin api token, created manually by logging in to the jellyfin server admin dashboard and creating an api key
## Comma separated list for multiple servers
JELLYFIN_TOKEN = "SuperSecretToken, SuperSecretToken2"
```

## Installation

### Baremetal

*   Setup virtualenv of your choice

*   Install dependencies

    ```bash
      pip install -r requirements.txt
    ```

*   Create a .env file similar to .env.sample, uncomment whitelist and blacklist if needed, fill in baseurls and tokens

*   Run

    ```bash
    python main.py
    ```

### Docker

*   Build docker image

    ```bash
    docker build -t jellyplex-watched .
    ```

*   or use pre-built image

    ```bash
    docker pull luigi311/jellyplex-watched:latest
    ```

#### With variables

*   Run

    ```bash
    docker run --rm -it -e PLEX_TOKEN='SuperSecretToken' luigi311/jellyplex-watched:latest
    ```

#### With .env

*   Create a .env file similar to .env.sample and set the variables to match your setup

*   Run

    ```bash
     docker run --rm -it -v "$(pwd)/.env:/app/.env" luigi311/jellyplex-watched:latest
    ```

## Contributing

I am open to receiving pull requests. If you are submitting a pull request, please make sure run it locally for a day or two to make sure it is working as expected and stable. Make all pull requests against the dev branch and nothing will be merged into the main without going through the lower branches.

## License

This is currently under the GNU General Public License v3.0.
