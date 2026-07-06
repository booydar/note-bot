"""Shared save operations — the one place both frontends call to persist things.

Owns the capture-event log: every save records what was saved, from which raw
input, and what artifact it produced. Downstream jobs (extraction, nightly
batch) read the event log; the frontends stay thin.
"""

from __future__ import annotations

import logging

from notebot import storage
from notebot.notes import parsing

logger = logging.getLogger("notebot.actions")


class Actions:
    def __init__(self, cfg, nm, events, source, sheet_writer=None, movie_saver=None,
                 note_subfolder="voice"):
        self.cfg = cfg
        self.nm = nm
        self.events = events
        self.source = source            # "telegram" | "nctalk"
        self.sheet_writer = sheet_writer
        self.movie_saver = movie_saver
        self.note_subfolder = note_subfolder

    def save_note(self, sess) -> str:
        """Format + write the note, log the event, reindex in the background.
        Returns the note name."""
        note_text, name = parsing.parse_message(sess.text, sess.tags, sess.links)
        path = storage.write_note(self.cfg.note_db_path, self.note_subfolder, name,
                                  note_text, self.cfg.os_user_id)
        self.events.record(self.source, "note", raw_text=sess.text, artifact=path,
                           tags=sess.tags, links=sess.links)
        self.nm.schedule_reindex()
        return path.rsplit("/", 1)[-1][:-len(".md")]

    def save_expense(self, sess, category) -> None:
        self.sheet_writer.write_expense(sess.amount, category, sess.comment.strip())
        self.events.record(self.source, "expense", raw_text=sess.comment.strip() or None,
                           amount=sess.amount, category=category)

    def save_movie(self, sess, watchlist=False) -> None:
        movie = sess.movies[0]
        if watchlist:
            self.movie_saver.save(movie, None, sess.movie_type, sheet=1)
        else:
            self.movie_saver.save(movie, sess.rating, sess.movie_type,
                                  comment=sess.comment.strip() or None)
        self.events.record(self.source, "movie", raw_text=sess.text,
                           tmdb_id=movie.get("id"), rating=sess.rating,
                           movie_type=sess.movie_type, watchlist=watchlist,
                           comment=sess.comment.strip() or None)
