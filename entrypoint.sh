#!/usr/bin/env sh

set -e

# Create group and user based on environment variables
if [ ! "$(getent group "$PGID")" ]; then
    # If groupadd exists, use it
    if command -v groupadd > /dev/null; then
        groupadd -g "$PGID" jellyplex_group
    else
        addgroup -g "$PGID" jellyplex_group
    fi
fi

if [ ! "$(getent passwd "$PUID")" ]; then
    # If useradd exists, use it
    if command -v useradd > /dev/null; then
        useradd --no-create-home -u "$PUID" -g "$PGID" jellyplex_user
    else
        adduser -D -H -u "$PUID" -G jellyplex_group jellyplex_user
    fi
fi

# Adjust ownership of the application directory
chown -R "$PUID:$PGID" /app

# Run the application as the created user
exec gosu "$PUID:$PGID" "$@"
