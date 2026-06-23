#!/usr/bin/env bash
#
# Rebuild the bot image and restart the container WITHOUT touching the Talk
# registration (so the bot stays attached to your conversation). Use this for
# quick code iteration. Run on the home host with sudo:
#
#     sudo bash ~/Tools/notebot-nc-test/restart.sh
#
set -euo pipefail

BOT_NAME=notebot-nc-test
IMAGE=notebot-nc-test:latest
PORT=9000
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$HERE/logs"
SECRET_FILE=/root/.notebot-nc-test.secret
NET="${NC_NET:-nextcloud-aio}"

[ -f "$SECRET_FILE" ] || { echo "No secret at $SECRET_FILE — run deploy.sh first."; exit 1; }

mkdir -p "$LOG_DIR"; chmod 777 "$LOG_DIR"
: > "$LOG_DIR/bot.log"; chmod 666 "$LOG_DIR/bot.log"

docker build -t "$IMAGE" "$HERE"
docker rm -f "$BOT_NAME" >/dev/null 2>&1 || true
docker run -d --name "$BOT_NAME" --restart unless-stopped \
  --network "$NET" \
  -e SECRET="$(cat "$SECRET_FILE")" -e BOT_PORT="$PORT" -e LOG_FILE="/logs/bot.log" \
  -v "$LOG_DIR:/logs" \
  "$IMAGE" >/dev/null

echo "Restarted $BOT_NAME on '$NET'. Talk registration left untouched."
echo "Logs: $LOG_DIR/bot.log"
