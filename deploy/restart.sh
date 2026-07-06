#!/usr/bin/env bash
#
# Rebuild + restart the NC note-bot WITHOUT touching the Talk registration
# (keeps it attached to your conversation). Run with sudo on the home host:
#     sudo bash ~/Tools/notebot-nc-integration/deploy/restart.sh
#
set -euo pipefail

BOT_NAME=notebot-nc
IMAGE=notebot-nc:latest
PORT=9911
SECRET_FILE=/root/.notebot-nc.secret
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
LOG_DIR="$HERE/logs"

HOST_HOME=/home/booydar
CONFIG_ENV="root/Tools/telegram-bots/note_bot/config_docker"
OS_USER_ID=1000

[ -f "$SECRET_FILE" ] || { echo "No secret at $SECRET_FILE — run deploy.sh first."; exit 1; }
mkdir -p "$LOG_DIR"; chmod 777 "$LOG_DIR"; : > "$LOG_DIR/bot.log"; chmod 666 "$LOG_DIR/bot.log"

docker build -t "$IMAGE" "$ROOT"
docker rm -f "$BOT_NAME" >/dev/null 2>&1 || true
docker run -d --name "$BOT_NAME" --restart unless-stopped \
  --network host \
  -v "$HOST_HOME:/app/root" \
  -v "$LOG_DIR:/logs" \
  -e config="$CONFIG_ENV" \
  -e os_user_id="$OS_USER_ID" \
  -e TALK_SECRET="$(cat "$SECRET_FILE")" \
  -e BOT_PORT="$PORT" \
  -e LOG_FILE="/logs/bot.log" \
  "$IMAGE" >/dev/null

echo "Restarted $BOT_NAME (host network). Logs: $LOG_DIR/bot.log"
