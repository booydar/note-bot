#!/usr/bin/env bash
#
# Deploy the NC Talk note-bot on the home host. Run with sudo:
#     sudo bash ~/Tools/notebot-nc-integration/deploy/deploy.sh
#
# It mirrors the Telegram bot's mounts/env so config + vault + cache resolve the
# same way, builds the image from the repo root, runs it on the Nextcloud network,
# and registers it with Talk.
#
set -euo pipefail

BOT_NAME=notebot-nc
IMAGE=notebot-nc:latest
PORT=9911                            # host port (host networking; avoid common ports)
SECRET_FILE=/root/.notebot-nc.secret
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"            # repo root = docker build context
LOG_DIR="$HERE/logs"

# Same as the Telegram bot's `docker run` (so var.json paths resolve identically):
HOST_HOME=/home/booydar
CONFIG_ENV="root/Tools/telegram-bots/note_bot/config_docker"
OS_USER_ID=1000

echo "==> Locating occ container + network"
OCC_CONTAINER="${OCC_CONTAINER:-}"
if [ -z "$OCC_CONTAINER" ]; then
  for c in $(docker ps --format '{{.Names}}' | grep -i nextcloud); do
    docker exec -u www-data "$c" php /var/www/html/occ status >/dev/null 2>&1 && { OCC_CONTAINER="$c"; break; }
  done
fi
[ -n "$OCC_CONTAINER" ] || { echo "!! no occ container; set OCC_CONTAINER=..."; exit 1; }
OCC="docker exec -u www-data $OCC_CONTAINER php /var/www/html/occ"
NC_NET="${NC_NET:-$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' "$OCC_CONTAINER" | grep -v '^$' | head -1)}"
# Host networking so the bot reaches the host-local SOCKS proxy (127.0.0.1:1080).
# Nextcloud (on the bridge) then reaches the bot via this network's gateway = the host.
GATEWAY="$(docker network inspect "$NC_NET" -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}')"
echo "    occ=$OCC_CONTAINER  net=$NC_NET  gateway=$GATEWAY"

echo "==> Secret"
if [ -f "$SECRET_FILE" ]; then
  SECRET="$(cat "$SECRET_FILE")"
else
  SECRET="$(openssl rand -hex 32)"; echo "$SECRET" >"$SECRET_FILE"; chmod 600 "$SECRET_FILE"
fi

echo "==> Log dir (readable without sudo): $LOG_DIR/bot.log"
mkdir -p "$LOG_DIR"; chmod 777 "$LOG_DIR"; : > "$LOG_DIR/bot.log"; chmod 666 "$LOG_DIR/bot.log"

echo "==> Building image (context: $ROOT) — first build is slow (torch etc.)"
docker build -t "$IMAGE" "$ROOT"

echo "==> (Re)starting container with host networking"
docker rm -f "$BOT_NAME" >/dev/null 2>&1 || true
docker run -d --name "$BOT_NAME" --restart unless-stopped \
  --network host \
  -v "$HOST_HOME:/app/root" \
  -v "$LOG_DIR:/logs" \
  -e config="$CONFIG_ENV" \
  -e os_user_id="$OS_USER_ID" \
  -e TALK_SECRET="$SECRET" \
  -e BOT_PORT="$PORT" \
  -e LOG_FILE="/logs/bot.log" \
  "$IMAGE" >/dev/null

echo "==> Firewall (let the docker bridge reach the bot port on the host)"
SUBNET="$(docker network inspect "$NC_NET" -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}')"
if command -v ufw >/dev/null 2>&1; then
  echo "    $(ufw status | head -1)"
  if ufw status | grep -qi active; then
    ufw allow from "$SUBNET" to any port "$PORT" proto tcp >/dev/null 2>&1 && echo "    allowed $SUBNET -> :$PORT" || true
  fi
else
  echo "    ufw not installed"
fi

echo "==> Registering with Talk (idempotent)"
WEBHOOK="http://${GATEWAY}:${PORT}/webhook"
# uninstall is by id/url (not secret); remove any prior "NC Note Bot" by id first.
OLD_IDS="$($OCC talk:bot:list --output json 2>/dev/null | python3 -c '
import sys, json
try:
    bots = json.load(sys.stdin)
except Exception:
    bots = []
for b in bots:
    if b.get("name") == "NC Note Bot":
        print(b.get("id"))
')"
for id in $OLD_IDS; do
  echo "    removing old registration id=$id"
  $OCC talk:bot:uninstall "$id" || true
done
# fallback: also drop the earlier nextcloud-aio registration by its URL, if any
$OCC talk:bot:uninstall --url "http://notebot-nc:9000/webhook" >/dev/null 2>&1 || true
$OCC talk:bot:uninstall --url "$WEBHOOK" >/dev/null 2>&1 || true
INSTALL_OUT="$($OCC talk:bot:install "NC Note Bot" "$SECRET" "$WEBHOOK" \
  --feature webhook --feature response --feature reaction \
  "Note-bot over Nextcloud Talk." 2>&1)"
echo "$INSTALL_OUT"
NEW_ID="$(printf '%s' "$INSTALL_OUT" | grep -oiE 'ID:?[[:space:]]*[0-9]+' | grep -oE '[0-9]+' | head -1)"

# Auto-attach to a room if SETUP_TOKEN is given (token = the /call/<token> URL part).
if [ -n "${SETUP_TOKEN:-}" ] && [ -n "$NEW_ID" ]; then
  $OCC talk:bot:setup "$NEW_ID" "$SETUP_TOKEN" || true
  echo "==> Attached bot id=$NEW_ID to conversation $SETUP_TOKEN"
fi

echo
echo "Done. Webhook: $WEBHOOK   (bot id=${NEW_ID:-?})"
echo "Logs (no sudo): $LOG_DIR/bot.log  — model load takes ~minute on first start."
if [ -z "${SETUP_TOKEN:-}" ]; then
  echo
  echo "Attach it to your room (re-run with SETUP_TOKEN=<token> to do this automatically):"
  echo "  $OCC talk:bot:setup ${NEW_ID:-<id>} <token>   # token = the /call/<token> part of the room URL"
fi
echo
echo "If the bot doesn't receive events, the host firewall may block the docker bridge"
echo "from reaching the host on $PORT. Allow it with e.g.:"
echo "  ufw allow from ${GATEWAY%.*}.0/16 to any port $PORT"
