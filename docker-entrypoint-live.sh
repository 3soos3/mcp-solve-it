#!/bin/sh
# Entrypoint for the :live image.
# Downloads the latest SOLVE-IT data from SOLVE_IT_DATA_URL at startup.
# Falls back to the previously cached data on any failure.
# Sets MCP_APP_SOLVEIT_DATA_PATH so the chassis init hook finds the data.

set -e

DATA_DIR="${SOLVE_IT_DATA_DIR:-/tmp/app-cache/solve-it}"
ARCHIVE_PATH="/tmp/app-tmp/solve-it-latest.zip"
DATA_URL="${SOLVE_IT_DATA_URL:-https://data.solveit-df.org/solve-it-latest.zip}"

mkdir -p "$DATA_DIR" /tmp/app-tmp

echo "[entrypoint] Checking ${DATA_URL} ..."

if wget --spider --quiet --timeout=10 --tries=1 "$DATA_URL" 2>/dev/null; then
    echo "[entrypoint] Reachable — downloading latest data ..."
    if wget --no-verbose --timeout=60 -O "$ARCHIVE_PATH" "$DATA_URL"; then
        echo "[entrypoint] Extracting to ${DATA_DIR} ..."
        if unzip -q -o "$ARCHIVE_PATH" -d "$DATA_DIR"; then
            rm -f "$ARCHIVE_PATH"
            echo "[entrypoint] Data ready at ${DATA_DIR}"
        else
            rm -f "$ARCHIVE_PATH"
            echo "[entrypoint] Extract failed — using cached data." >&2
        fi
    else
        rm -f "$ARCHIVE_PATH"
        echo "[entrypoint] Download failed — using cached data." >&2
    fi
else
    echo "[entrypoint] Unreachable — using cached data." >&2
fi

# Point the chassis init hook at the data directory.
# Overrides [app] solveit_data_path in config/default.toml.
export MCP_APP_SOLVEIT_DATA_PATH="${DATA_DIR}"

exec python -m mcp_chassis "$@"
