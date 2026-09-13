#!/usr/bin/env sh

set -e

# Check if user is root
if [ "$(id -u)" = '0' ]; then
    echo "User is root, checking if we need to create a user and group based on environment variables"
    # Create group and user based on environment variables
    if [ ! "$(getent group "$PGID")" ]; then
        # If groupadd exists, use it
        if command -v groupadd > /dev/null; then
            groupadd -g "$PGID" jellyplex_watched
        elif command -v addgroup > /dev/null; then
            addgroup -g "$PGID" jellyplex_watched
        fi
    fi

    # If user id does not exist, create the user
    if [ ! "$(getent passwd "$PUID")" ]; then
        if command -v useradd > /dev/null; then
            useradd --no-create-home -u "$PUID" -g "$PGID" jellyplex_watched
        elif command -v adduser > /dev/null; then
            # Get the group name based on the PGID since adduser does not have a flag to specify the group id
            # and if the group id already exists the group name will be sommething unexpected
            GROUPNAME=$(getent group "$PGID" | cut -d: -f1)

            # Use alpine busybox adduser syntax
            adduser -D -H -u "$PUID" -G "$GROUPNAME" jellyplex_watched
        fi
    fi
else
    # If user is not root, set the PUID and PGID to the current user
    PUID=$(id -u)
    PGID=$(id -g)
fi

# Copy sample config yaml to the config dir for the user to have a template
CONF_DIR="/app/config"
if [ -n "$CONF_DIR" ]; then
    mkdir -p "$CONF_DIR"
fi
cp /app/sample.config.yaml "${CONF_DIR}/sample.config.yaml"

# Resolve YAML and environment settings before dropping privileges. The helper
# prints only the effective log and mark file paths, so the shell never needs
# to parse application configuration or handle secrets.
RUNTIME_FILES=$(python -m src.runtime_paths)
while IFS= read -r RUNTIME_FILE; do
    if [ -z "$RUNTIME_FILE" ]; then
        continue
    fi

    RUNTIME_DIR=$(dirname "$RUNTIME_FILE")
    if [ ! -d "$RUNTIME_DIR" ]; then
        mkdir -p "$RUNTIME_DIR"
        if [ "$(id -u)" = '0' ]; then
            chown "$PUID:$PGID" "$RUNTIME_DIR"
        fi
    fi

    if [ ! -e "$RUNTIME_FILE" ]; then
        : > "$RUNTIME_FILE"
        if [ "$(id -u)" = '0' ]; then
            chown "$PUID:$PGID" "$RUNTIME_FILE"
        fi
    elif [ -f "$RUNTIME_FILE" ] && [ "$(id -u)" = '0' ]; then
        chown "$PUID:$PGID" "$RUNTIME_FILE"
    fi
done <<EOF
$RUNTIME_FILES
EOF

echo "Starting JellyPlex-Watched with UID: $PUID and GID: $PGID"

# If root run as the created user
if [ "$(id -u)" = '0' ]; then
    chown -R "$PUID:$PGID" /app/.venv
    # A documented read-only file bind mount rejects recursive chown. Keep
    # the config directory writable for migration, while allowing ownership
    # of mounted files to remain unchanged when the mount forbids it.
    if ! chown -R "$PUID:$PGID" "$CONF_DIR" 2>/dev/null; then
        chown "$PUID:$PGID" "$CONF_DIR"
    fi

    # Run the application as the created user
    exec gosu "$PUID:$PGID" "$@"
else
    # Run the application as the current user
    exec "$@"
fi
