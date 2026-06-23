# NC Talk note-bot

A Nextcloud Talk frontend over the **same backend** as the Telegram bot. `bot.py`
is untouched; this reuses `thoughts.py`, `parse.py`, `movies.py`, `finance.py`.

Talk has no buttons, so the UI is **reaction chips on the bot's own reply** (placed
via the sequential-id trick) plus typed replies for free text/numbers.

## Files
- `talk.py` — transport: webhook verify, send message/reaction, parallel chip seeding.
- `session.py` — per-conversation state + message-id bookkeeping.
- `app.py` — loads the backend once; maps chips/typed input → backend calls.
- `Dockerfile` — built from the repo root (`-f nc-talk/Dockerfile .`).
- `deploy.sh` / `restart.sh` — run on the home host with sudo.

## Flows (all chip-driven)
```
type/send text → 📝 заметка  💭 мысли  🏷️ тег  🎬 фильм  💰 трата  ❌
  📝  save note to <vault>/talk/
  💭  nearest notes → tap 1-5 to link, ⏭️ more, 📝 save
  🏷️  suggested tags → tap 1-4 (or type a tag), 📝 save
  🎬  (type year?) → 🎬 film / 📺 series → 👁️ watched(→rating→comment→✅) / 🔖 watchlist / ⏭️ next
  💰  parse expense → ✅ save / ❌
```

## Deploy
```bash
sudo bash ~/Tools/notebot-nc-integration/nc-talk/deploy.sh   # build + run + register
# then enable it in your room:
#   occ talk:bot:list ; occ talk:bot:setup <id> <token>
```
Mounts `/home/booydar:/app/root` and uses `config=root/Tools/telegram-bots/note_bot/config_docker`
— identical to the Telegram bot, so vault/cache paths in `var.json` match. Logs:
`nc-talk/logs/bot.log`.

## Known caveats (first cut)
- Runs its **own** NoteManager → a second copy of the model in RAM, and shares the
  note vault + cache with the Telegram bot. Don't save from both at the same instant
  (concurrent `note_db.npy` writes). Unifying into one backend process is the next step.
- `id + 1` reply targeting assumes a 1-on-1 room with no concurrent posters.
- Notes are tagged `#voice` by `parse_message` (shared with Telegram); change later if
  NC notes want a different default tag.
- Text only for now (no voice/image).
