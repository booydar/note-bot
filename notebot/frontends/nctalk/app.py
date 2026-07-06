"""NC Talk frontend: maps reaction-chip taps and typed replies onto the shared
backend (NoteManager, Actions). Mirrors the Telegram flows and Russian wording.

Run via:  config=/path/to/configdir TALK_SECRET=... python -m notebot nctalk
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading

from notebot import session as S
from notebot.actions import Actions
from notebot.frontends.nctalk.nc_files import share_image_to_room
from notebot.frontends.nctalk.talk import TalkClient, serve
from notebot.integrations import movies
from notebot.session import Session, SessionStore
from notebot.storage import EventLog

logger = logging.getLogger("notebot.nctalk")

# --- chips ----------------------------------------------------------------------
KEYS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
CANCEL = "❌"
# capture menu mirrors telegram's voice_markup: В заметки / В фильмы / Мысли / +тэг
CAPTURE_CHIPS = ["📝", "🎬", "💭", "🏷️", CANCEL]
MOVIE_TYPE_CHIPS = ["🎬", "📺", CANCEL]      # Фильм / Сериал
MOVIE_RESULT_CHIPS = ["👁️", "🔖", "⏭️", CANCEL]  # Просмотрено / На будущее / Следующий
WAIT_CHIPS = [CANCEL]
SAVE_CHIPS = ["✅", CANCEL]                   # Сохранить
RESET_WORDS = {"отмена", "стоп", "сброс", "cancel", "reset", "/reset", "/cancel", "/clear"}


class App:
    """All handler state in one place (was module-level globals)."""

    def __init__(self, cfg, nm):
        cfg.require("tmdb_api_key")
        self.cfg = cfg
        self.nm = nm
        self.talk = TalkClient(os.environ["TALK_SECRET"],
                               internal_url=os.environ.get("NC_INTERNAL_URL"))
        self.store = SessionStore()
        self.lock = threading.Lock()  # serialise handling; backend isn't thread-safe

        # Nextcloud account used only to attach files (posters) to the chat — the
        # bot's HMAC secret can't upload files.
        self.nc_user = cfg.get("nc_user")
        self.nc_app_password = cfg.get("nc_app_password")

        # Google/TMDb features are optional — if they fail to init, notes still work.
        self.sheet_writer = self.ms = None
        try:
            from notebot.integrations.gsheets import GSheetsClient
            gs = GSheetsClient(cfg.gsheets_cred, proxy=cfg.proxy)
        except Exception as e:
            gs = None
            logger.warning("gsheets disabled: %s", e)
        if gs:
            try:
                from notebot.integrations.finance import SheetWriter
                self.sheet_writer = SheetWriter(gs)
            except Exception as e:
                logger.warning("finance disabled: %s", e)
            try:
                self.ms = movies.MovieSaver(note_db_path=cfg.note_db_path, gsheets=gs,
                                            tmdb_api_key=cfg["tmdb_api_key"], proxy=cfg.proxy,
                                            user_id=cfg.os_user_id)
            except Exception as e:
                logger.warning("movies disabled: %s", e)

        self.actions = Actions(cfg, nm, EventLog(cfg.events_db), source="nctalk",
                               sheet_writer=self.sheet_writer, movie_saver=self.ms,
                               note_subfolder=cfg.get("nc_note_subfolder", "voice/talk"))

    # --- low-level send helpers (own the message-id bookkeeping) ------------------
    # Talk message ids are sequential, and the send API doesn't return the new id, so
    # we predict it. Reactions create hidden "system messages" that ALSO consume ids,
    # so we must count them: +1 per message we send, +len(chips) per seeding, +1 per
    # reaction event we receive. The most recent user message re-syncs us (max).
    def send(self, sess: Session, backend, token, text) -> int:
        if self.talk.send_message(backend, token, text):
            sess.last_id += 1  # only count messages that actually posted
        return sess.last_id

    def show(self, sess: Session, backend, token, state, text, chips):
        """Send a reply and seed `chips` on it, making it the live menu."""
        msg_id = self.send(sess, backend, token, text)
        self.talk.seed_reactions(backend, token, msg_id, chips)
        sess.last_id += len(chips)          # reaction system-messages consume ids
        sess.state = state
        sess.active_msg_id = msg_id
        logger.debug("show state=%s menu_id=%s chips=%d last_id=%d",
                     state, msg_id, len(chips), sess.last_id)

    def done(self, sess: Session, backend, token, text):
        """Send a final confirmation and clear the flow."""
        self.send(sess, backend, token, text)
        sess.reset()

    # --- screens -------------------------------------------------------------------
    def show_capture(self, sess, backend, token):
        legend = "📝 в заметки   🎬 в фильмы   💭 мысли   🏷️ +тэг"
        self.show(sess, backend, token, S.CAPTURE, f"{sess.text.strip()}\n\n{legend}",
                  CAPTURE_CHIPS)

    def show_thoughts(self, sess, backend, token):
        page = sess.nearest[:5]
        if not page:
            self.done(sess, backend, token, "Не найдено похожих заметок")
            return
        lines = []
        for i, n in enumerate(page):
            snippet = n[n["search_field"]][n["nearest_field"]][:250]
            lines.append(f"{KEYS[i]} {snippet}\n"
                         f"{round(float(n['distance']), 2)} ({n['search_field']}) [[{n['name']}]]")
        text = "\n\n".join(lines) + "\n\n⏭️ ещё   🏷️ теги   📝 сохранить"
        self.show(sess, backend, token, S.THOUGHTS, text,
                  KEYS[: len(page)] + ["⏭️", "🏷️", "📝", CANCEL])

    def show_tags(self, sess, backend, token):
        sg = sess.suggested_tags[:4]
        selected = "  ".join(f"#{t}" for t in sess.tags)
        head = f"Выбрано: {selected}\n\n" if sess.tags else ""
        if not sg:
            self.send(sess, backend, token, "Не найдено подходящих тегов. Введи название тега")
            sess.state = S.TAG
            sess.active_msg_id = None  # nothing to tap; user types
            return
        lines = [f"{KEYS[i]} #{t}" for i, t in enumerate(sg)]
        text = head + "Введи название тега или тапни номер:\n\n" + "\n".join(lines) + \
            "\n\n💭 мысли   📝 сохранить"
        self.show(sess, backend, token, S.TAG, text, KEYS[: len(sg)] + ["💭", "📝", CANCEL])

    def show_movie_result(self, sess, backend, token):
        if not sess.movies:
            self.done(sess, backend, token, "Фильм не найден :(")
            return
        movie = sess.movies[0]
        try:
            info = movies.get_info(movie, type=sess.movie_type)
        except Exception as e:
            logger.exception("tmdb info failed")
            self.done(sess, backend, token, f"Ошибка получения данных: {e}")
            return
        self._attach_poster(sess, backend, token, info)

        desc = (f"{info['название']} ({info['год']})\n{info['режиссер']}\n"
                f"{movie.get('overview', '')[:400]}...")
        text = desc + "\n\n👁️ просмотрено   🔖 на будущее   ⏭️ следующий"
        self.show(sess, backend, token, S.MOVIE_RESULT, text, MOVIE_RESULT_CHIPS)

    def _attach_poster(self, sess, backend, token, info):
        """Download the poster via the TMDb proxy session and attach it as a real
        image. A file share posts its own chat message, so count it (+1) for our
        id bookkeeping before sending the text+chips."""
        if not (info.get("poster_path") and self.ms and self.nc_user and self.nc_app_password):
            return
        name = f"{info['название']} ({info['год']}).jpg".replace("/", "-")
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
                self.ms.download_poster(info["poster_path"], out_path=tmp.name)
                share_image_to_room(backend, token, tmp.name, name,
                                    self.nc_user, self.nc_app_password)
            sess.last_id += 1  # the file share is its own chat message
        except Exception as e:
            logger.warning("poster attach failed: %s", e)

    def show_categories(self, sess, backend, token):
        if not self.sheet_writer:
            self.done(sess, backend, token, "Финансы недоступны")
            return
        cats = self.sheet_writer.categories
        lines = [f"{KEYS[i]} {c}\n" for i, c in enumerate(cats[: len(KEYS)])]
        rest = "\n(или впиши название категории)" if len(cats) > len(KEYS) else ""
        text = f"Сумма: {sess.amount}\nУкажите категорию:\n\n" + "\n".join(lines) + rest
        self.show(sess, backend, token, S.EXPENSE_CATEGORY, text,
                  KEYS[: min(len(cats), len(KEYS))] + [CANCEL])

    # --- event entry point -----------------------------------------------------------
    def on_event(self, ev, backend):
        with self.lock:
            sess = self.store.get(ev["token"])
            logger.debug("ev type=%s msg=%s emoji=%s state=%s active=%s last_id=%s",
                         ev['type'], ev['msg_id'], ev['emoji'],
                         sess.state, sess.active_msg_id, sess.last_id)

            if ev["type"] == "Create" and ev["text"] is not None:
                if ev["msg_id"] and str(ev["msg_id"]).isdigit():
                    sess.last_id = max(sess.last_id, int(ev["msg_id"]))  # re-sync
                self.handle_text(sess, backend, ev["token"], ev["text"].strip())
            elif ev["type"] == "Like":
                sess.last_id += 1  # the reaction is itself a system message (consumes an id)
                self.handle_tap(sess, backend, ev["token"], ev["emoji"], ev["msg_id"])
            elif ev["type"] == "Undo":
                sess.last_id += 1
                self.handle_untap(sess, ev["emoji"], ev["msg_id"])

    def handle_text(self, sess, backend, token, text):
        if not text:
            return
        if text.lower() in RESET_WORDS:
            self.done(sess, backend, token, "Отменено")
            return
        st = sess.state

        if st == S.MOVIE_TYPE and text.isdigit():
            sess.year = int(text)
            self.send(sess, backend, token, f"Год: {text}. Выбери 🎬 фильм или 📺 сериал.")
            return
        if st == S.MOVIE_RATING:
            if not text.isdigit():
                self.send(sess, backend, token, "### Error processing rating, try again. ###")
                return
            sess.rating = int(text)
            self.show(sess, backend, token, S.MOVIE_COMMENT, "Добавь комментарий", SAVE_CHIPS)
            return
        if st == S.MOVIE_COMMENT:
            sess.comment += text + " "
            return
        if st == S.TAG:
            sess.tags.append(text)
            self.show_tags(sess, backend, token)  # re-show with chips so 📝 stays tappable
            return
        if st == S.EXPENSE_CATEGORY:
            if text.isdigit():
                self._pick_category(sess, backend, token, int(text) - 1)
            elif self.sheet_writer and text in self.sheet_writer.categories:
                self._save_expense(sess, backend, token, text)
            else:
                sess.comment += text + " "  # treat as a comment, like the Telegram bot
            return

        # otherwise: a fresh message. A bare number is an expense (as on Telegram).
        sess.reset()
        if text.isdigit():
            sess.amount = int(text)
            self.show_categories(sess, backend, token)
        else:
            sess.text = text
            self.show_capture(sess, backend, token)

    def handle_tap(self, sess, backend, token, emoji, tapped_id):
        if sess.active_msg_id is None or int(tapped_id) != sess.active_msg_id:
            logger.debug("ignoring stale tap on %s (active %s)", tapped_id, sess.active_msg_id)
            return
        if emoji == CANCEL:
            self.done(sess, backend, token, "Отменено")
            return

        st = sess.state
        if st == S.CAPTURE:
            self._capture_tap(sess, backend, token, emoji)
        elif st == S.THOUGHTS:
            self._thoughts_tap(sess, backend, token, emoji)
        elif st == S.TAG:
            self._tag_tap(sess, backend, token, emoji)
        elif st == S.MOVIE_TYPE:
            self._movie_type_tap(sess, backend, token, emoji)
        elif st == S.MOVIE_RESULT:
            self._movie_result_tap(sess, backend, token, emoji)
        elif st == S.MOVIE_COMMENT and emoji == "✅":
            self._save_movie_watched(sess, backend, token)
        elif st == S.EXPENSE_CATEGORY and emoji in KEYS:
            self._pick_category(sess, backend, token, KEYS.index(emoji))

    def handle_untap(self, sess, emoji, tapped_id):
        """Removing a number reaction un-selects the corresponding link/tag."""
        if sess.active_msg_id is None or int(tapped_id) != sess.active_msg_id or emoji not in KEYS:
            return
        i = KEYS.index(emoji)
        if sess.state == S.THOUGHTS:
            page = sess.nearest[:5]
            if i < len(page) and page[i]["name"] in sess.links:
                sess.links.remove(page[i]["name"])
        elif sess.state == S.TAG:
            sg = sess.suggested_tags[:4]
            if i < len(sg) and sg[i] in sess.tags:
                sess.tags.remove(sg[i])

    # --- per-state tap handlers -----------------------------------------------------
    def _save_note(self, sess, backend, token, suffix=""):
        try:
            name = self.actions.save_note(sess)
        except Exception as e:
            logger.exception("note save failed")
            self.done(sess, backend, token, f"Ошибка сохранения: {e}")
            return
        self.done(sess, backend, token, f"Note saved: {name}{suffix}")

    def _capture_tap(self, sess, backend, token, emoji):
        if emoji == "📝":
            if not sess.text.strip():
                self.done(sess, backend, token, "Пусто — нечего сохранять")
                return
            self._save_note(sess, backend, token)
        elif emoji == "💭":
            sess.nearest = self.nm.get_nearest_all_fields(sess.text, k=25)
            self.show_thoughts(sess, backend, token)
        elif emoji == "🏷️":
            sess.suggested_tags = self.nm.suggest_tags(sess.text)
            self.show_tags(sess, backend, token)
        elif emoji == "🎬":
            self.show(sess, backend, token, S.MOVIE_TYPE,
                      "Укажи год, если возможно.\n🎬 фильм   📺 сериал", MOVIE_TYPE_CHIPS)

    def _thoughts_tap(self, sess, backend, token, emoji):
        if emoji in KEYS:
            i = KEYS.index(emoji)
            page = sess.nearest[:5]
            if i < len(page) and page[i]["name"] not in sess.links:
                sess.links.append(page[i]["name"])  # the reaction itself is the feedback
        elif emoji == "⏭️":
            sess.nearest = sess.nearest[5:]
            self.show_thoughts(sess, backend, token)
        elif emoji == "🏷️":  # continue the pipeline: links -> tags (keeps both)
            if not sess.suggested_tags:
                sess.suggested_tags = self.nm.suggest_tags(sess.text)
            self.show_tags(sess, backend, token)
        elif emoji == "📝":
            self._save_note(sess, backend, token, suffix=f" (связей: {len(sess.links)})")

    def _tag_tap(self, sess, backend, token, emoji):
        if emoji in KEYS:
            i = KEYS.index(emoji)
            sg = sess.suggested_tags[:4]
            if i < len(sg) and sg[i] not in sess.tags:
                sess.tags.append(sg[i])
        elif emoji == "💭":  # continue the pipeline: tags -> related notes (keeps both)
            if not sess.nearest:
                sess.nearest = self.nm.get_nearest_all_fields(sess.text, k=25)
            self.show_thoughts(sess, backend, token)
        elif emoji == "📝":
            tags = " ".join(f"#{t}" for t in sess.tags) or "(без тегов)"
            self._save_note(sess, backend, token, suffix=f" {tags}")

    def _movie_type_tap(self, sess, backend, token, emoji):
        if not self.ms:
            self.done(sess, backend, token, "Фильмы недоступны")
            return
        sess.movie_type = "movie" if emoji == "🎬" else "tv"
        try:
            sess.movies = movies.get_movies(sess.text, year=sess.year, language="ru",
                                            type=sess.movie_type)
        except Exception as e:
            logger.exception("tmdb search failed")
            self.done(sess, backend, token, f"Ошибка поиска: {e}")
            return
        self.show_movie_result(sess, backend, token)

    def _movie_result_tap(self, sess, backend, token, emoji):
        if emoji == "👁️":
            self.show(sess, backend, token, S.MOVIE_RATING, "Введи оценку от 1 до 10", WAIT_CHIPS)
        elif emoji == "🔖":
            try:
                self.actions.save_movie(sess, watchlist=True)
            except Exception as e:
                logger.exception("watchlist save failed")
                self.done(sess, backend, token, f"Ошибка: {e}")
                return
            self.done(sess, backend, token, "Film added to watchlist")
        elif emoji == "⏭️":
            sess.movies = sess.movies[1:]
            self.show_movie_result(sess, backend, token)

    def _save_movie_watched(self, sess, backend, token):
        try:
            self.actions.save_movie(sess)
        except Exception as e:
            logger.exception("movie save failed")
            self.done(sess, backend, token, f"Ошибка сохранения: {e}")
            return
        self.done(sess, backend, token, "Film saved")

    def _pick_category(self, sess, backend, token, index):
        cats = self.sheet_writer.categories if self.sheet_writer else []
        if index < 0 or index >= len(cats):
            self.send(sess, backend, token, "Нет такой категории, попробуй снова.")
            return
        self._save_expense(sess, backend, token, cats[index])

    def _save_expense(self, sess, backend, token, category):
        try:
            self.actions.save_expense(sess, category)
        except Exception as e:
            logger.exception("expense save failed")
            self.done(sess, backend, token, f"Ошибка сохранения: {e}")
            return
        self.done(sess, backend, token, "Expense saved")


def run(cfg, nm):
    if not os.environ.get("TALK_SECRET"):
        raise SystemExit("config error: TALK_SECRET env var is required for the nctalk frontend")
    app = App(cfg, nm)
    port = int(os.environ.get("BOT_PORT", "9000"))
    logger.info("nctalk bot ready — %d notes indexed", len(nm.db))
    serve(port, app.talk, app.on_event)
