#!/usr/bin/env bash
set -euo pipefail

APP_PID=""
TUNNEL_PID=""

shutdown() {
    trap - SIGTERM SIGINT

    if [[ -n "$TUNNEL_PID" ]] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
        kill -TERM "$TUNNEL_PID" 2>/dev/null || true
    fi

    if [[ -n "$APP_PID" ]] && kill -0 "$APP_PID" 2>/dev/null; then
        kill -TERM "$APP_PID" 2>/dev/null || true
    fi

    wait 2>/dev/null || true
}

trap shutdown SIGTERM SIGINT

/app/rustasr &
APP_PID=$!

TOKEN="${CLOUDFLARED_TOKEN:-${TUNNEL_TOKEN:-}}"

if [[ -n "$TOKEN" ]]; then
    echo "Запускаю Cloudflare Tunnel для локального сервиса http://localhost:8080"
    cloudflared tunnel --no-autoupdate run --token "$TOKEN" &
    TUNNEL_PID=$!
    wait -n "$APP_PID" "$TUNNEL_PID"
else
    echo "CLOUDFLARED_TOKEN/TUNNEL_TOKEN не задан, запускаю только RustASR"
    wait "$APP_PID"
fi

EXIT_CODE=$?
shutdown
exit "$EXIT_CODE"
