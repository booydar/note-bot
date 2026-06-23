#!/usr/bin/env bash
#
# Build + run the Talk test bot on this host and register it with Nextcloud Talk.
# Run ON the home host with sudo (Docker needs root here):
#
#     sudo bash ~/Tools/notebot-nc-test/deploy.sh
#
# Overridable via env if auto-detection picks the wrong thing:
#     OCC_CONTAINER=nextcloud-aio-nextcloud NC_NET=nextcloud-aio sudo -E bash deploy.sh
#
set -euo pipefail

BOT_NAME=notebot-nc-test
IMAGE=notebot-nc-test:latest
PORT=9000
WEBHOOK_PATH=/webhook
SECRET_FILE=/root/.notebot-nc-test.secret
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$HERE/logs"

echo "==> Locating the container that can run occ"
# The container with the occ CLI is the PHP app container (in AIO that's
# nextcloud-aio-nextcloud, not the apache front-end). Probe candidates.
OCC_CONTAINER="${OCC_CONTAINER:-}"
if [ -z "$OCC_CONTAINER" ]; then
  for c in $(docker ps --format '{{.Names}}' | grep -i nextcloud); do
    if docker exec -u www-data "$c" php /var/www/html/occ status >/dev/null 2>&1; then
      OCC_CONTAINER="$c"; break
    fi
  done
fi
[ -n "$OCC_CONTAINER" ] || { echo "!! No nextcloud container could run occ. Set OCC_CONTAINER=... and retry."; docker ps --format '{{.Names}}\t{{.Image}}'; exit 1; }
OCC="docker exec -u www-data ${OCC_CONTAINER} php /var/www/html/occ"
echo "    occ container: $OCC_CONTAINER"

echo "==> Detecting Docker network (the one the occ container is on)"
# The webhook call originates from this container, so the bot must share its network.
NC_NET="${NC_NET:-$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' "$OCC_CONTAINER" | grep -v '^$' | head -1)}"
[ -n "$NC_NET" ] || { echo "!! Could not detect a network for $OCC_CONTAINER. Set NC_NET=... and retry."; exit 1; }
echo "    network: $NC_NET"

echo "==> Shared secret"
if [ -f "$SECRET_FILE" ]; then
  SECRET="$(cat "$SECRET_FILE")"
  echo "    reusing $SECRET_FILE"
else
  SECRET="$(openssl rand -hex 32)"   # 64 hex chars (Talk requires 40-128)
  echo "$SECRET" > "$SECRET_FILE"; chmod 600 "$SECRET_FILE"
  echo "    generated new secret -> $SECRET_FILE"
fi

WEBHOOK_URL="http://${BOT_NAME}:${PORT}${WEBHOOK_PATH}"

echo "==> Preparing log dir (readable without sudo): $LOG_DIR/bot.log"
mkdir -p "$LOG_DIR"; chmod 777 "$LOG_DIR"
: > "$LOG_DIR/bot.log"; chmod 666 "$LOG_DIR/bot.log"

echo "==> Building bot image"
docker build -t "$IMAGE" "$HERE"

echo "==> (Re)starting bot container on network '$NC_NET'"
docker rm -f "$BOT_NAME" >/dev/null 2>&1 || true
docker run -d --name "$BOT_NAME" --restart unless-stopped \
  --network "$NC_NET" \
  -e SECRET="$SECRET" -e BOT_PORT="$PORT" -e LOG_FILE="/logs/bot.log" \
  -v "$LOG_DIR:/logs" \
  "$IMAGE" >/dev/null
echo "    running as '$BOT_NAME', listening on :$PORT (internal)"

echo "==> Registering bot with Talk (idempotent)"
$OCC talk:bot:uninstall "$SECRET" >/dev/null 2>&1 || true
$OCC talk:bot:install "NC Test Bot" "$SECRET" "$WEBHOOK_URL" \
  --feature webhook --feature response --feature reaction \
  "Interaction-style test bot (reaction chips + numbered selection)."

echo
echo "==> Done."
echo "    Webhook URL Nextcloud will call: $WEBHOOK_URL"
echo "    Logs (no sudo needed):           $LOG_DIR/bot.log"
echo
echo "Next:"
echo "  1. Talk UI -> a conversation -> ... -> Conversation settings -> Bots ->"
echo "     enable 'NC Test Bot'."
echo "  2. Send 'menu' (or 'list', or any text) and tap the chips."
echo
echo "To remove later:"
echo "  $OCC talk:bot:uninstall \$(cat $SECRET_FILE)"
echo "  docker rm -f $BOT_NAME"
