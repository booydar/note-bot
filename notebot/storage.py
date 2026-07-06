"""Disk layer: note files, the embedding cache, and the capture-event log.

Three concerns, all shared by the frontends:
  - write_note: create a .md note in the vault (mkdirs + chown for syncthing,
    never silently overwrite an existing note);
  - atomic .npy save for the NoteManager cache (a crash mid-save must not
    corrupt the db) plus an inter-process lock so the telegram and nctalk
    processes don't write the cache at the same instant;
  - EventLog: an append-only SQLite record of every capture (note / expense /
    movie), with the raw input and the produced artifact. This is the ground
    layer for downstream extraction jobs — the bot stays dumb, the log stays
    complete.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import sqlite3
import time

import numpy as np

logger = logging.getLogger("notebot.storage")


def chown_to_user(path: str, user_id: int | None) -> None:
    """Hand a path to the host user so syncthing (runs as that user) can manage it.

    The bot runs as root in Docker, so anything it creates is root-owned; a
    root-owned dir blocks syncthing from writing/deleting inside it, so dirs we
    create must be chowned too, not just files.
    """
    if user_id is None:
        return
    try:
        os.chown(path, user_id, user_id)
    except OSError:
        pass


def write_note(note_db_path: str, subfolder: str, name: str, text: str,
               user_id: int | None = None) -> str:
    """Write `text` as <vault>/<subfolder>/<name>.md and return the path.

    Creates (and chowns) the subfolder chain, leaving the existing vault root
    untouched. If the name is already taken, a timestamp is appended instead of
    overwriting the existing note.
    """
    name = (name or "").strip() or "note"
    note_dir = os.path.join(note_db_path, subfolder)
    os.makedirs(note_dir, exist_ok=True)
    d = note_db_path
    for part in subfolder.strip("/").split("/"):
        d = os.path.join(d, part)
        chown_to_user(d, user_id)

    path = os.path.join(note_dir, f"{name}.md")
    if os.path.exists(path):
        suffix = time.strftime("%Y-%m-%d %H-%M-%S")
        path = os.path.join(note_dir, f"{name} - {suffix}.md")
    with open(path, "w") as f:
        f.write(text)
    chown_to_user(path, user_id)
    return path


@contextlib.contextmanager
def file_lock(path: str):
    """Advisory inter-process lock (the npy cache is shared by both frontends)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def save_npy(path: str, obj) -> None:
    """np.save via temp file + rename, so a crash never corrupts the cache."""
    tmp = path + ".tmp.npy"
    np.save(tmp, np.asarray(obj, dtype=object), allow_pickle=True)
    os.replace(tmp, path)


def load_npy(path: str):
    return np.load(path, allow_pickle=True)


class EventLog:
    """Append-only capture log. One row per thing the user saved."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    source TEXT NOT NULL,   -- telegram | nctalk | cli
                    kind TEXT NOT NULL,     -- note | expense | movie | ...
                    raw_text TEXT,          -- what the user actually sent
                    artifact TEXT,          -- file path / sheet name the save produced
                    meta TEXT               -- JSON: tags, links, amounts, ids, ...
                )"""
            )

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def record(self, source: str, kind: str, raw_text: str | None = None,
               artifact: str | None = None, **meta) -> None:
        try:
            with self._conn() as c:
                c.execute(
                    "INSERT INTO events (ts, source, kind, raw_text, artifact, meta) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        time.strftime("%Y-%m-%dT%H:%M:%S"),
                        source, kind, raw_text, artifact,
                        json.dumps(meta, ensure_ascii=False) if meta else None,
                    ),
                )
        except sqlite3.Error as e:
            logger.error("event log write failed: %s", e)  # never break a save

    def recent(self, limit: int = 20) -> list[tuple]:
        with self._conn() as c:
            return list(c.execute(
                "SELECT ts, source, kind, raw_text, artifact, meta FROM events "
                "ORDER BY id DESC LIMIT ?", (limit,)
            ))
