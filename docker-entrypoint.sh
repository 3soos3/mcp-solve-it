#!/bin/sh
# Unified entrypoint for all image modes.
#
# SOLVE_IT_MODE=release|monthly  — data is baked in; start server directly.
# SOLVE_IT_MODE=live             — download data from SOLVE_IT_DATA_URL at
#                                  startup; fall back to cached copy on failure.

set -e

if [ "$SOLVE_IT_MODE" = "live" ]; then
    DATA_DIR="${SOLVE_IT_DATA_DIR:-/tmp/app-cache/solve-it}"
    ARCHIVE_PATH="/tmp/app-tmp/solve-it-latest.zip"
    DATA_URL="${SOLVE_IT_DATA_URL:-https://data.solveit-df.org/solve-it-latest.zip}"

    mkdir -p "$DATA_DIR" /tmp/app-tmp

    echo "[entrypoint] Checking ${DATA_URL} ..."

    if wget --spider --quiet --timeout=10 --tries=1 "$DATA_URL" 2>/dev/null; then
        echo "[entrypoint] Reachable — downloading latest data ..."
        if wget --no-verbose --timeout=60 -O "$ARCHIVE_PATH" "$DATA_URL"; then
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

    # Tell the chassis init hook where to find the data.
    # Overrides [app] solveit_data_path in config/default.toml.
    export MCP_APP_SOLVEIT_DATA_PATH="${DATA_DIR}"
fi

exec python -m mcp_chassis "$@"
