# JellyPlex-Watched

[![Codacy Badge](https://app.codacy.com/project/badge/Grade/26b47c5db63942f28f02f207f692dc85)](https://www.codacy.com/gh/luigi311/JellyPlex-Watched/dashboard?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=luigi311/JellyPlex-Watched&amp;utm_campaign=Badge_Grade)

Sync watched between jellyfin and plex

## Description

Keep in sync all your users watched history between jellyfin and plex servers locally. This uses the imdb ids and any other matching id to find the correct episode/movie between the two. This is not perfect but it works for most cases. You can use this for as many servers as you want by enterying multiple options in the .env plex/jellyfin section seperated by commas.

## Configuration



## Installation

### Baremetal

-   Setup virtualenv of your choice

-   Install dependencies

    ```bash
      pip install -r requirements.txt
    ```

-   Create a .env file similar to .env.sample, uncomment whitelist and blacklist if needed, fill in baseurls and tokens

-   Run

    ```bash
    python main.py
    ```

### Docker

-   Build docker image

    ```bash
    docker build -t jellyplex-watched .
    ```

-   or use pre-built image

    ```bash
    docker pull luigi311/jellyplex-watched:latest
    ```

#### With variables

-   Run

    ```bash
    docker run --rm -it -e PLEX_TOKEN='SuperSecretToken' luigi311/jellyplex-watched:latest
    ```

#### With .env

-   Create a .env file similar to .env.sample and set the variables to match your setup

-   Run

    ```bash
     docker run --rm -it -v "$(pwd)/.env:/app/.env" luigi311/jellyplex-watched:latest
    ```

## Contributing

I am open to recieving pull requests. If you are submitting a pull request, please make sure run it locally for a day or two to make sure it is working as expected and stable. Make all pull requests against the dev branch and nothing will be merged into the main without going through the lower branches.

## License

This is currently under the GNU General Public License v3.0.
