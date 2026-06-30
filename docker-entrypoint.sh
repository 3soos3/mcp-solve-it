#!/bin/sh
# Unified entrypoint for all image modes.
#
# SOLVE_IT_MODE=release|monthly  — data is baked in; start server directly.
# SOLVE_IT_MODE=live             — check SOLVE_IT_DATA_URL for updates on each
#                                  startup; extract only when zip hash changes;
#                                  fall back to bundled data on failure.

set -e

if [ "$SOLVE_IT_MODE" = "live" ]; then
    DATA_DIR="${SOLVE_IT_DATA_DIR:-/tmp/app-cache/solve-it}"
    BUNDLED_DIR="${MCP_APP_SOLVEIT_DATA_PATH:-/app/solve-it-main}"
    ARCHIVE_PATH="/tmp/app-tmp/solve-it-latest.zip"
    DATA_URL="${SOLVE_IT_DATA_URL:-https://data.solveit-df.org/solve-it-latest.zip}"
    HASH_FILE="${DATA_DIR}/.content_hash"

    mkdir -p "$DATA_DIR" /tmp/app-tmp

    echo "[entrypoint] live mode — checking ${DATA_URL} ..."

    if wget --no-verbose --timeout=60 -O "$ARCHIVE_PATH" "$DATA_URL" 2>/dev/null; then
        NEW_HASH=$(md5sum "$ARCHIVE_PATH" | awk '{print $1}')
        OLD_HASH=""
        [ -f "$HASH_FILE" ] && OLD_HASH=$(cat "$HASH_FILE")

        if [ "$NEW_HASH" != "$OLD_HASH" ] || [ ! -d "${DATA_DIR}/data" ]; then
            echo "[entrypoint] New version detected — extracting ..."
            if unzip -q -o "$ARCHIVE_PATH" -d "$DATA_DIR"; then
                printf '%s' "$NEW_HASH" > "$HASH_FILE"
                echo "[entrypoint] Live data updated at ${DATA_DIR}."
            else
                echo "[entrypoint] Extract failed." >&2
            fi
        else
            echo "[entrypoint] Already up to date."
        fi
        rm -f "$ARCHIVE_PATH"
    else
        rm -f "$ARCHIVE_PATH"
        echo "[entrypoint] Download failed — will use fallback." >&2
    fi

    # If the downloaded data dir lacks solve_it_library, symlink from bundled.
    if [ -d "${DATA_DIR}/data" ] && [ ! -d "${DATA_DIR}/solve_it_library" ] \
       && [ -d "${BUNDLED_DIR}/solve_it_library" ]; then
        ln -sf "${BUNDLED_DIR}/solve_it_library" "${DATA_DIR}/solve_it_library"
    fi

    # Use downloaded/cached data if available; fall back to bundled.
    if [ -d "${DATA_DIR}/data" ]; then
        export MCP_APP_SOLVEIT_DATA_PATH="${DATA_DIR}"
        echo "[entrypoint] Using live data at ${DATA_DIR}."
    else
        export MCP_APP_SOLVEIT_DATA_PATH="${BUNDLED_DIR}"
        echo "[entrypoint] Falling back to bundled data at ${BUNDLED_DIR}."
    fi
fi

exec python -m mcp_chassis "$@"
