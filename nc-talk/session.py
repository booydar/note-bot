"""Per-conversation state for the NC Talk frontend.

Talk gives no buttons, so a flow is driven by (a) reaction chips on the bot's last
message and (b) typed replies. `state` says which menu/prompt is active, so a tapped
emoji or a typed line can be interpreted in context.

`last_id` tracks the most recent message id in the conversation. Because Talk ids are
sequential and the send API doesn't return the new id, we count every message we send
(and sync to every id we see) so we always know which id our next reply will have —
that's the id we seed chips on (the "id + 1" trick, generalised to survive any
intermediate messages).
"""

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
    last_id: int = 0
    active_msg_id: Optional[int] = None  # the message whose chips are "live"

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

    def reset(self, keep_last_id: bool = True):
        last_id = self.last_id
        self.__init__()
        if keep_last_id:
            self.last_id = last_id


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def get(self, token: str) -> Session:
        if token not in self._sessions:
            self._sessions[token] = Session()
        return self._sessions[token]
