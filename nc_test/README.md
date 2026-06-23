# Nextcloud Talk — response-type test bot

A throwaway, dependency-free bot to *feel* how Talk's interaction primitives perform
before wiring up any note-bot logic. It demonstrates:

- **reaction chips as buttons** — the bot posts a message and pre-reacts to it with
  emojis; tapping a chip is ~one tap and the bot is told which emoji was tapped.
- **numbered selection** — keycap chips `1️⃣..5️⃣` plus `⏭️ next` / `✅ save`.
- **text fallback** — send any text; it echoes back with the chips.

## Files
- `talkbot.py` — the whole bot (stdlib only: HMAC verify/sign, webhook server, replies).
- `Dockerfile` — tiny `python:3.11-slim` image, no pip installs.
- `deploy.sh` — builds, runs, and registers the bot. Run on the home host with sudo.

## Deploy (on the `home` host)
```bash
sudo bash ~/Tools/notebot-nc-test/deploy.sh
```
It finds the container that can run `occ` (the PHP app container — in AIO that's
`nextcloud-aio-nextcloud`), detects its Docker network, generates a shared secret,
runs the bot on that network, and registers it via `occ talk:bot:install` with the
`reaction` feature. Override detection if needed:
```bash
OCC_CONTAINER=nextcloud-aio-nextcloud NC_NET=nextcloud-aio sudo -E bash deploy.sh
```

## Try it
1. Talk UI → a conversation → settings → **Bots** → enable **NC Test Bot**.
2. Send `menu`, `list`, or any text; tap the chips.
3. Logs are written to `~/Tools/notebot-nc-test/logs/bot.log` (readable without sudo)
   and show every real event payload — useful to confirm the exact `Like`/`Undo`
   shapes against the live server.

## Notes
- Replies use the `X-Nextcloud-Talk-Backend` (public) URL by default. If the container
  can't reach the public URL (no NAT hairpin), set `NC_INTERNAL_URL` on the container
  to an internal address and the bot keeps the public Host header for trusted-domain.
- Signing: incoming = `HMAC-SHA256(random + raw_body)`, outgoing message = over the
  message text, outgoing reaction = over the emoji.
