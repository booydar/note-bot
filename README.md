# note-bot

Personal capture bot: voice/text/photos → Zettelkasten notes (+ expenses to a
Google sheet, movies to a sheet + a note), with semantic search over the vault.
Two frontends over one backend:

- **Telegram** — voice notes (transcription + punctuation), OCR on photos,
  inline-button flows;
- **Nextcloud Talk** — the same flows driven by reaction chips (Talk bots have
  no buttons), text only for now.

Every save is also appended to a SQLite **event log** (`events.sqlite` in the
cache dir): timestamp, source, kind, raw input, produced artifact. That log is
the ground truth for downstream extraction/analysis jobs.

## Layout

```
notebot/
  config.py session.py storage.py actions.py   # config, per-chat state, disk + event log, shared saves
  notes/        # parsing.py (pure text munging), embed.py, manager.py (FAISS index)
  integrations/ # gsheets, finance, movies (TMDb), ocr, transcribe, llm (ollama)
  frontends/
    telegram.py
    nctalk/     # talk.py (transport: HMAC webhook + chips), nc_files.py, app.py
  cli.py
tests/          # pure-logic tests, run with pytest (no torch needed)
deploy/         # deploy.sh / restart.sh for the NC bot on the home host
```

## Run

Config lives in one folder (env var `config`): `var.json` (see
`config.example.json`) + `gsheets.json` (service-account credentials).

```bash
config=/path/to/configdir python -m notebot telegram
config=/path/to/configdir TALK_SECRET=... python -m notebot nctalk
python -m notebot reindex          # reparse + re-embed the vault (cron-able)
python -m notebot search "запрос"  # query the index from the shell
python -m notebot events           # tail the capture-event log
```

Docker: `docker build -t notebot .` — one image, pick the frontend with the
command (`python -m notebot telegram|nctalk`). The NC bot is deployed with
`sudo bash deploy/deploy.sh` (builds, runs on the host network, registers the
bot with Talk via occ; `deploy/restart.sh` rebuilds without touching the
registration).

## NC Talk specifics

Talk bots can only send text and reactions, so menus are **reaction chips on
the bot's own reply**. Message ids are sequential and the send API doesn't
return the new id, so `session.last_id` counts every message/reaction we cause
and re-syncs on every user message — see `frontends/nctalk/app.py`. Posters are
attached via WebDAV + a share (needs `nc_user`/`nc_app_password`), because the
bot's HMAC secret can't upload files.

## Notes on shared state

Both frontends may run at once (separate processes/containers). The embedding
cache (`note_db.npy`) is written atomically under a file lock, and each process
reindexes in a background thread after a save. The vault itself is plain `.md`
files — existing names are never overwritten (a timestamp is appended).
