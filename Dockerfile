FROM python:3-slim

ENV DRYRUN 'True'
ENV DEBUG 'True'
ENV DEBUG_LEVEL 'INFO'
ENV SLEEP_DURATION '3600'
ENV LOGFILE 'log.log'

ENV USER_MAPPING '{ "User Test": "User Test2" }'
ENV LIBRARY_MAPPING '{ "Shows Test": "TV Shows Test" }'

ENV PLEX_BASEURL 'http://localhost:32400'
ENV PLEX_TOKEN ''
ENV PLEX_USERNAME ''
ENV PLEX_PASSWORD ''
ENV PLEX_SERVERNAME ''

ENV JELLYFIN_BASEURL 'http://localhost:8096'
ENV JELLYFIN_TOKEN ''

ENV BLACKLIST_LIBRARY ''
ENV WHITELIST_LIBRARY ''
ENV BLACKLIST_LIBRARY_TYPE  '' 
ENV WHITELIST_LIBRARY_TYPE  ''
ENV BLACKLIST_USERS  ''
ENV WHITELIST_USERS  ''

WORKDIR /app

COPY ./requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-u", "main.py"]
