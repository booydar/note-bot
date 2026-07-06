"""Per-conversation state, shared by both frontends.

A flow is driven by a menu on the bot's last message (inline buttons on
Telegram, reaction chips on NC Talk) plus typed replies. `state` says which
menu/prompt is active, so a tap or a typed line can be interpreted in context.

NC Talk specifics: `last_id` tracks the most recent message id in the
conversation. Talk ids are sequential and the send API doesn't return the new
id, so we count every message we send (and sync to every id we see) to know
which id our next reply will have — that's the id we seed chips on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# states
IDLE = "idle"
CAPTURE = "capture"          # text captured, main menu shown
THOUGHTS = "thoughts"        # related-notes list, pick numbers to link
TAG = "tag"                  # suggested tags, pick numbers or type
MOVIE_TYPE = "movie_type"    # choose film/series (year optionally typed first)
MOVIE_RESULT = "movie_result"  # a search result shown
MOVIE_RATING = "movie_rating"  # waiting for a typed 1-10 rating
MOVIE_COMMENT = "movie_comment"  # waiting for a typed comment, then save
EXPENSE_CATEGORY = "expense_category"  # amount set, pick a category (type comment first if wanted)


@dataclass
class Session:
    state: str = IDLE

    # nc-talk message-id bookkeeping
    last_id: int = 0
    active_msg_id: Optional[int] = None  # the message whose chips are "live"

    # telegram bookkeeping
    chat_id: Optional[int] = None
    to_delete: list = field(default_factory=list)  # intermediate messages to clean up

    # capture / note
    text: str = ""
    tags: list = field(default_factory=list)
    links: list = field(default_factory=list)

    # thoughts / tags
    nearest: list = field(default_factory=list)
    suggested_tags: list = field(default_factory=list)

    # movies
    movies: list = field(default_factory=list)
    movie_type: str = "movie"
    year: Optional[int] = None
    rating: Optional[int] = None
    comment: str = ""

    # expense
    amount: Optional[int] = None
    category: Optional[str] = None

    def reset(self):
        """Clear flow state; keep the per-conversation bookkeeping."""
        last_id, chat_id = self.last_id, self.chat_id
        self.__init__()
        self.last_id, self.chat_id = last_id, chat_id


class SessionStore:
    def __init__(self):
        self._sessions: dict = {}

    def get(self, key) -> Session:
        if key not in self._sessions:
            self._sessions[key] = Session()
        return self._sessions[key]
