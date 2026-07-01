#!/bin/sh
# Unified entrypoint for all image modes.
#
# SOLVE_IT_MODE=release|monthly  — data is baked in; start server directly.
# SOLVE_IT_MODE=live             — on startup, check SOLVE_IT_REPO@SOLVE_IT_BRANCH
#                                  for a new commit and download if the SHA changed.
#                                  A background loop repeats this check every 24 h;
#                                  on a new commit it updates DATA_DIR and sends
#                                  SIGTERM to the server so Docker/Compose restarts
#                                  it with the fresh data.
#                                  Set SOLVE_IT_LIVE_UPDATES=false to disable all
#                                  update checks and use cached/bundled data only.

set -e

# ── helpers ────────────────────────────────────────────────────────────────────

# Resolve latest commit SHA from GitHub API. Prints SHA or nothing on failure.
_latest_sha() {
    wget -qO- --timeout=10 \
        "https://api.github.com/repos/${REPO}/commits/${BRANCH}" 2>/dev/null \
        | grep -m1 '"sha"' | sed 's/.*"sha": *"\([^"]*\)".*/\1/' || true
}

# Download and extract the SOLVE-IT tarball for a given SHA into DATA_DIR.
# Returns 0 on success, 1 on failure (cleans up on failure).
_download() {
    _sha="$1"
    _url="https://github.com/${REPO}/archive/${_sha}.tar.gz"
    if wget -qO "$ARCHIVE_PATH" --timeout=60 "$_url" \
       && tar xz -C "$DATA_DIR" --strip-components=1 -f "$ARCHIVE_PATH" 2>/dev/null; then
        rm -f "$ARCHIVE_PATH"
        printf '%s' "$_sha" > "$SHA_FILE"
        return 0
    fi
    rm -f "$ARCHIVE_PATH"
    return 1
}

# ── live mode setup ────────────────────────────────────────────────────────────

if [ "$SOLVE_IT_MODE" = "live" ]; then
    DATA_DIR="${SOLVE_IT_DATA_DIR:-/tmp/app-cache/solve-it}"
    BUNDLED_DIR="${MCP_APP_SOLVEIT_DATA_PATH:-/app/solve-it-main}"
    ARCHIVE_PATH="/tmp/app-tmp/solve-it.tar.gz"
    REPO="${SOLVE_IT_REPO:-SOLVE-IT-DF/solve-it}"
    BRANCH="${SOLVE_IT_BRANCH:-main}"
    SHA_FILE="${DATA_DIR}/.sha"

    mkdir -p "$DATA_DIR" /tmp/app-tmp

    # Startup check
    if [ "${SOLVE_IT_LIVE_UPDATES:-true}" = "true" ]; then
        echo "[entrypoint] live mode — checking ${REPO}@${BRANCH} ..."
        LATEST_SHA=$(_latest_sha)
        STORED_SHA=""; [ -f "$SHA_FILE" ] && STORED_SHA=$(cat "$SHA_FILE")
        SHORT=$(printf '%s' "$LATEST_SHA" | cut -c1-7)

        if [ -n "$LATEST_SHA" ] && [ "$LATEST_SHA" = "$STORED_SHA" ] \
           && [ -d "${DATA_DIR}/data" ]; then
            echo "[entrypoint] Already up to date (${SHORT})."
        elif [ -n "$LATEST_SHA" ]; then
            echo "[entrypoint] New commit ${SHORT} — downloading ..."
            _download "$LATEST_SHA" \
                && echo "[entrypoint] Data updated." \
                || echo "[entrypoint] Download failed — will use fallback." >&2
        else
            echo "[entrypoint] Cannot reach GitHub API — using cached/bundled data." >&2
        fi
    else
        echo "[entrypoint] live mode — updates disabled."
    fi

    # Resolve active data path and stamp SOLVE_IT_VERSION for provenance
    if [ -d "${DATA_DIR}/data" ]; then
        export MCP_APP_SOLVEIT_DATA_PATH="${DATA_DIR}"
        ACTIVE_SHA=""; [ -f "$SHA_FILE" ] && ACTIVE_SHA=$(cat "$SHA_FILE")
        [ -n "$ACTIVE_SHA" ] && export SOLVE_IT_VERSION="sha-$(printf '%s' "$ACTIVE_SHA" | cut -c1-7)"
        echo "[entrypoint] Using live data (${SOLVE_IT_VERSION:-unknown})."
    else
        export MCP_APP_SOLVEIT_DATA_PATH="${BUNDLED_DIR}"
        echo "[entrypoint] Falling back to bundled data (${SOLVE_IT_VERSION:-unknown})."
    fi
fi

# ── start server ───────────────────────────────────────────────────────────────
# When the daily updater is active we cannot use exec — the shell must stay
# alive to run the background loop and signal the server. In all other cases
# exec is used so stdin/stdout pass directly to Python (required for stdio
# transport and for the image test suite).

if [ "$SOLVE_IT_MODE" = "live" ] && [ "${SOLVE_IT_LIVE_UPDATES:-true}" = "true" ]; then
    python -m mcp_chassis "$@" &
    SERVER_PID=$!
    export SERVER_PID

    # ── daily update loop ──────────────────────────────────────────────────────
    # Checks every 24 h. On a new commit: downloads data, then SIGTERMs the
    # server so Docker/Compose (restart: always) restarts it with fresh data.
    (
        while true; do
            sleep 86400
            echo "[updater] Daily check — ${REPO}@${BRANCH} ..."
            LATEST=$(_latest_sha)
            STORED=""; [ -f "$SHA_FILE" ] && STORED=$(cat "$SHA_FILE")

            if [ -n "$LATEST" ] && [ "$LATEST" != "$STORED" ]; then
                SHORT=$(printf '%s' "$LATEST" | cut -c1-7)
                echo "[updater] New commit ${SHORT} — downloading ..."
                if _download "$LATEST"; then
                    echo "[updater] Restarting server to load new data ..."
                    kill -TERM "$SERVER_PID" 2>/dev/null || true
                else
                    echo "[updater] Download failed — keeping current data." >&2
                fi
            else
                echo "[updater] No changes."
            fi
        done
    ) &

    wait $SERVER_PID
else
    exec python -m mcp_chassis "$@"
fi
