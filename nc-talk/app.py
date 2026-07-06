"""NC Talk note-bot frontend.

Reuses the existing backend modules (NoteManager, parse_message, movies, finance)
unchanged, and exposes them through Nextcloud Talk using reaction chips as buttons.
The Telegram bot (bot.py) is untouched; this is a parallel frontend over the same
backend code, and it mirrors bot.py's flows and Russian wording.

Run:  config=/path/to/configdir  TALK_SECRET=... python nc-talk/app.py
"""

import os
import sys
import json
import threading

# Optional: tee all stdout/stderr to a (bind-mounted) file so logs can be read
# without `docker logs` / sudo. Set LOG_FILE to enable.
_LOG_FILE = os.environ.get("LOG_FILE")
if _LOG_FILE:
    class _Tee:
        def __init__(self, *streams):
            self.streams = streams

        def write(self, data):
            for s in self.streams:
                s.write(data)
                s.flush()

        def flush(self):
            for s in self.streams:
                s.flush()

    _fh = open(_LOG_FILE, "a")
    sys.stdout = _Tee(sys.__stdout__, _fh)
    sys.stderr = _Tee(sys.__stderr__, _fh)

# make the parent repo (backend modules) importable, plus this folder
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root: thoughts.py, parse.py, ...
sys.path.insert(0, HERE)                    # talk.py, session.py

from thoughts import NoteManager
from parse import parse_message
from movies import get_movies, get_info, MovieSaver
from finance import SheetWriter

import session as S
from session import Session, SessionStore
from talk import TalkClient, serve
from nc_files import share_image_to_room

# --- config (same var.json the Telegram bot uses) -------------------------------
CONFIG_FOLDER = os.environ["config"]
with open(os.path.join(CONFIG_FOLDER, "var.json")) as f:
    config = json.load(f)
GSHEETS_CRED = os.path.join(CONFIG_FOLDER, "gsheets.json")
NOTE_DB_PATH = config["note_db_path"]
USER_ID = os.getenv("os_user_id")
PROXY = config.get("proxy")

TALK_SECRET = os.environ["TALK_SECRET"]
NC_INTERNAL_URL = os.environ.get("NC_INTERNAL_URL")
PORT = int(os.environ.get("BOT_PORT", "9000"))
NOTE_SUBFOLDER = config.get("nc_note_subfolder", "voice/talk")
# Nextcloud account used only to attach files (posters) to the chat — the bot's HMAC
# secret can't upload files. Create an app password in Nextcloud and put it here.
NC_USER = config.get("nc_user")
NC_APP_PASSWORD = config.get("nc_app_password")


def log(*args):
    print("[nc]", *args, flush=True)


# --- backend (loaded once) ------------------------------------------------------
log("loading NoteManager ...")
nm = NoteManager(
    NOTE_DB_PATH,
    model_name=config["embedding_model"],
    save_path=config["cache_path"],
    batch_size=int(config["batch_size"]),
)

# Google/TMDb features are optional — if they fail to init, notes still work.
try:
    sheet_writer = SheetWriter(GSHEETS_CRED, proxy=PROXY)
except Exception as e:  # noqa: BLE001
    sheet_writer = None
    log(f"finance disabled: {e}")
try:
    ms = MovieSaver(
        note_db_path=NOTE_DB_PATH, cred_path=GSHEETS_CRED,
        tmdb_api_key=config["tmdb_api_key"], proxy=PROXY,
    )
except Exception as e:  # noqa: BLE001
    ms = None
    log(f"movies disabled: {e}")

talk = TalkClient(TALK_SECRET, internal_url=NC_INTERNAL_URL)
store = SessionStore()
LOCK = threading.Lock()  # serialise handling; backend isn't thread-safe

# --- chips ----------------------------------------------------------------------
KEYS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
CANCEL = "❌"
# capture menu mirrors bot.py's voice_markup: В заметки / В фильмы / Мысли / +тэг
CAPTURE_CHIPS = ["📝", "🎬", "💭", "🏷️", CANCEL]
MOVIE_TYPE_CHIPS = ["🎬", "📺", CANCEL]      # Фильм / Сериал
MOVIE_RESULT_CHIPS = ["👁️", "🔖", "⏭️", CANCEL]  # Просмотрено / На будущее / Следующий
WAIT_CHIPS = [CANCEL]
SAVE_CHIPS = ["✅", CANCEL]                   # Сохранить
RESET_WORDS = {"отмена", "стоп", "сброс", "cancel", "reset", "/reset", "/cancel", "/clear"}


# --- low-level send helpers (own the message-id bookkeeping) --------------------
# Talk message ids are sequential, and the send API doesn't return the new id, so we
# predict it. Reactions create hidden "system messages" that ALSO consume ids, so we
# must count them: +1 per message we send, +len(chips) per seeding, +1 per reaction
# event we receive. The most recent user message re-syncs us (max).
def send(sess: Session, backend, token, text) -> int:
    talk.send_message(backend, token, text)
    sess.last_id += 1
    return sess.last_id


def show(sess: Session, backend, token, state, text, chips):
    """Send a reply and seed `chips` on it, making it the live menu."""
    msg_id = send(sess, backend, token, text)
    talk.seed_reactions(backend, token, msg_id, chips)
    sess.last_id += len(chips)          # reaction system-messages consume ids
    sess.state = state
    sess.active_msg_id = msg_id
    log(f"show state={state} menu_id={msg_id} chips={len(chips)} last_id={sess.last_id}")


def done(sess: Session, backend, token, text):
    """Send a final confirmation and clear the flow."""
    send(sess, backend, token, text)
    sess.reset()


# --- note saving (the only logic mirrored from bot.py, kept tiny) ---------------
def _chown_to_user(path: str) -> None:
    """Hand a path to the host user so syncthing (runs as that user) can manage it.

    The bot runs as root in Docker, so anything it creates is root-owned. The
    Telegram bot only ever wrote files into a pre-existing (user-owned) `voice/`
    dir, but here we create the subfolder ourselves — a root-owned dir blocks
    syncthing from writing/deleting inside it, so chown the dirs too, not just
    the file.
    """
    if USER_ID is None:
        return
    try:
        os.chown(path, int(USER_ID), int(USER_ID))
    except OSError:
        pass


def save_note(sess: Session) -> str:
    note_text, name = parse_message(sess.text, sess.tags, sess.links)
    name = name.strip() or "note"
    note_dir = os.path.join(NOTE_DB_PATH, NOTE_SUBFOLDER)
    os.makedirs(note_dir, exist_ok=True)
    # chown each subfolder component we may have just created (e.g. voice, then
    # voice/talk), leaving the existing, user-owned note db root untouched.
    d = NOTE_DB_PATH
    for part in NOTE_SUBFOLDER.strip("/").split("/"):
        d = os.path.join(d, part)
        _chown_to_user(d)
    path = os.path.join(note_dir, f"{name}.md")
    with open(path, "w") as f:
        f.write(note_text)
    _chown_to_user(path)
    nm.parse_notes()  # reindex so the new note is searchable
    return name


# --- screens --------------------------------------------------------------------
def show_capture(sess, backend, token):
    legend = "📝 в заметки   🎬 в фильмы   💭 мысли   🏷️ +тэг"
    show(sess, backend, token, S.CAPTURE, f"{sess.text.strip()}\n\n{legend}", CAPTURE_CHIPS)


def show_thoughts(sess, backend, token):
    page = sess.nearest[:5]
    if not page:
        done(sess, backend, token, "Не найдено похожих заметок")
        return
    lines = []
    for i, n in enumerate(page):
        snippet = n[n["search_field"]][n["nearest_field"]][:250]
        lines.append(f"{KEYS[i]} {snippet}\n{round(float(n['distance']), 2)} ({n['search_field']}) [[{n['name']}]]")
    text = "\n\n".join(lines) + "\n\n⏭️ ещё   🏷️ теги   📝 сохранить"
    show(sess, backend, token, S.THOUGHTS, text, KEYS[: len(page)] + ["⏭️", "🏷️", "📝", CANCEL])


def show_tags(sess, backend, token):
    sg = sess.suggested_tags[:4]
    selected = "  ".join(f"#{t}" for t in sess.tags)
    head = f"Выбрано: {selected}\n\n" if sess.tags else ""
    if not sg:
        send(sess, backend, token, "Не найдено подходящих тегов. Введи название тега")
        sess.state = S.TAG
        sess.active_msg_id = None  # nothing to tap; user types
        return
    lines = [f"{KEYS[i]} #{t}" for i, t in enumerate(sg)]
    text = head + "Введи название тега или тапни номер:\n\n" + "\n".join(lines) + "\n\n💭 мысли   📝 сохранить"
    show(sess, backend, token, S.TAG, text, KEYS[: len(sg)] + ["💭", "📝", CANCEL])


def show_movie_result(sess, backend, token):
    if not sess.movies:
        done(sess, backend, token, "Фильм не найден :(")
        return
    movie = sess.movies[0]
    try:
        info = get_info(movie, type=sess.movie_type)
    except Exception as e:  # noqa: BLE001
        done(sess, backend, token, f"Ошибка получения данных: {e}")
        return
    # Download the poster through the proxy (like the Telegram bot) and attach it as a
    # real image. A file share posts its own chat message, so count it (+1) for our id
    # bookkeeping before sending the text+chips.
    _attach_poster(sess, backend, token, info)

    desc = (
        f"{info['название']} ({info['год']})\n{info['режиссер']}\n"
        f"{movie.get('overview', '')[:400]}..."
    )
    text = desc + "\n\n👁️ просмотрено   🔖 на будущее   ⏭️ следующий"
    show(sess, backend, token, S.MOVIE_RESULT, text, MOVIE_RESULT_CHIPS)


def _attach_poster(sess, backend, token, info):
    if not (info.get("poster_path") and ms and NC_USER and NC_APP_PASSWORD):
        return
    tmp = "/tmp/nc_poster.jpg"
    name = f"{info['название']} ({info['год']}).jpg".replace("/", "-")
    try:
        ms.download_poster(info["poster_path"], out_path=tmp)  # via TMDb proxy session
        if os.path.exists(tmp):
            share_image_to_room(backend, token, tmp, name, NC_USER, NC_APP_PASSWORD)
            sess.last_id += 1  # the file share is its own chat message
            os.remove(tmp)
    except Exception as e:  # noqa: BLE001
        log(f"poster attach failed: {e}")


def show_categories(sess, backend, token):
    if not sheet_writer:
        done(sess, backend, token, "Финансы недоступны")
        return
    cats = sheet_writer.categories
    lines = [f"{KEYS[i]} {c}\n" for i, c in enumerate(cats[: len(KEYS)])]
    rest = "\n(или впиши название категории)" if len(cats) > len(KEYS) else ""
    text = f"Сумма: {sess.amount}\nУкажите категорию:\n\n" + "\n".join(lines) + rest
    show(sess, backend, token, S.EXPENSE_CATEGORY, text, KEYS[: min(len(cats), len(KEYS))] + [CANCEL])


# --- event entry point ----------------------------------------------------------
def on_event(ev, backend):
    with LOCK:
        sess = store.get(ev["token"])
        log(f"ev type={ev['type']} msg={ev['msg_id']} emoji={ev['emoji']} "
            f"state={sess.state} active={sess.active_msg_id} last_id={sess.last_id}")

        if ev["type"] == "Create" and ev["text"] is not None:
            if ev["msg_id"] and str(ev["msg_id"]).isdigit():
                sess.last_id = max(sess.last_id, int(ev["msg_id"]))  # re-sync
            handle_text(sess, backend, ev["token"], ev["text"].strip())
        elif ev["type"] == "Like":
            sess.last_id += 1  # the reaction is itself a system message (consumes an id)
            handle_tap(sess, backend, ev["token"], ev["emoji"], ev["msg_id"])
        elif ev["type"] == "Undo":
            sess.last_id += 1
            handle_untap(sess, ev["emoji"], ev["msg_id"])


def handle_text(sess, backend, token, text):
    if not text:
        return
    if text.lower() in RESET_WORDS:
        done(sess, backend, token, "Отменено")
        return
    st = sess.state

    if st == S.MOVIE_TYPE and text.isdigit():
        sess.year = int(text)
        send(sess, backend, token, f"Год: {text}. Выбери 🎬 фильм или 📺 сериал.")
        return
    if st == S.MOVIE_RATING:
        if not text.isdigit():
            send(sess, backend, token, "### Error processing rating, try again. ###")
            return
        sess.rating = int(text)
        show(sess, backend, token, S.MOVIE_COMMENT, "Добавь комментарий", SAVE_CHIPS)
        return
    if st == S.MOVIE_COMMENT:
        sess.comment += text + " "
        return
    if st == S.TAG:
        sess.tags.append(text)
        show_tags(sess, backend, token)  # re-show with chips so 📝 stays tappable
        return
    if st == S.EXPENSE_CATEGORY:
        if text.isdigit():
            _pick_category(sess, backend, token, int(text) - 1)
        elif sheet_writer and text in sheet_writer.categories:
            _save_expense(sess, backend, token, text)
        else:
            sess.comment += text + " "  # treat as a comment, like the Telegram bot
        return

    # otherwise: a fresh message. A bare number is an expense (as in bot.py).
    sess.reset()
    if text.isdigit():
        sess.amount = int(text)
        show_categories(sess, backend, token)
    else:
        sess.text = text
        show_capture(sess, backend, token)


def handle_tap(sess, backend, token, emoji, tapped_id):
    if sess.active_msg_id is None or int(tapped_id) != sess.active_msg_id:
        log(f"ignoring stale tap on {tapped_id} (active {sess.active_msg_id})")
        return
    if emoji == CANCEL:
        done(sess, backend, token, "Отменено")
        return

    st = sess.state
    if st == S.CAPTURE:
        _capture_tap(sess, backend, token, emoji)
    elif st == S.THOUGHTS:
        _thoughts_tap(sess, backend, token, emoji)
    elif st == S.TAG:
        _tag_tap(sess, backend, token, emoji)
    elif st == S.MOVIE_TYPE:
        _movie_type_tap(sess, backend, token, emoji)
    elif st == S.MOVIE_RESULT:
        _movie_result_tap(sess, backend, token, emoji)
    elif st == S.MOVIE_COMMENT and emoji == "✅":
        _save_movie_watched(sess, backend, token)
    elif st == S.EXPENSE_CATEGORY and emoji in KEYS:
        _pick_category(sess, backend, token, KEYS.index(emoji))


def handle_untap(sess, emoji, tapped_id):
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
def _capture_tap(sess, backend, token, emoji):
    if emoji == "📝":
        if not sess.text.strip():
            done(sess, backend, token, "Пусто — нечего сохранять")
            return
        name = save_note(sess)
        done(sess, backend, token, f"Note saved: {name}")
    elif emoji == "💭":
        sess.nearest = nm.get_nearest_all_fields(sess.text, k=25)
        show_thoughts(sess, backend, token)
    elif emoji == "🏷️":
        sess.suggested_tags = nm.suggest_tags(sess.text)
        show_tags(sess, backend, token)
    elif emoji == "🎬":
        show(sess, backend, token, S.MOVIE_TYPE,
             "Укажи год, если возможно.\n🎬 фильм   📺 сериал", MOVIE_TYPE_CHIPS)


def _thoughts_tap(sess, backend, token, emoji):
    if emoji in KEYS:
        i = KEYS.index(emoji)
        page = sess.nearest[:5]
        if i < len(page) and page[i]["name"] not in sess.links:
            sess.links.append(page[i]["name"])  # the reaction itself is the feedback
    elif emoji == "⏭️":
        sess.nearest = sess.nearest[5:]
        show_thoughts(sess, backend, token)
    elif emoji == "🏷️":  # continue the pipeline: links -> tags (keeps both)
        if not sess.suggested_tags:
            sess.suggested_tags = nm.suggest_tags(sess.text)
        show_tags(sess, backend, token)
    elif emoji == "📝":
        name = save_note(sess)
        done(sess, backend, token, f"Note saved: {name} (связей: {len(sess.links)})")


def _tag_tap(sess, backend, token, emoji):
    if emoji in KEYS:
        i = KEYS.index(emoji)
        sg = sess.suggested_tags[:4]
        if i < len(sg) and sg[i] not in sess.tags:
            sess.tags.append(sg[i])
    elif emoji == "💭":  # continue the pipeline: tags -> related notes (keeps both)
        if not sess.nearest:
            sess.nearest = nm.get_nearest_all_fields(sess.text, k=25)
        show_thoughts(sess, backend, token)
    elif emoji == "📝":
        tags = " ".join(f"#{t}" for t in sess.tags) or "(без тегов)"
        name = save_note(sess)
        done(sess, backend, token, f"Note saved: {name} {tags}")


def _movie_type_tap(sess, backend, token, emoji):
    if not ms:
        done(sess, backend, token, "Фильмы недоступны")
        return
    sess.movie_type = "movie" if emoji == "🎬" else "tv"
    try:
        sess.movies = get_movies(sess.text, year=sess.year, language="ru", type=sess.movie_type)
    except Exception as e:  # noqa: BLE001
        done(sess, backend, token, f"Ошибка поиска: {e}")
        return
    show_movie_result(sess, backend, token)


def _movie_result_tap(sess, backend, token, emoji):
    if emoji == "👁️":
        show(sess, backend, token, S.MOVIE_RATING, "Введи оценку от 1 до 10", WAIT_CHIPS)
    elif emoji == "🔖":
        try:
            ms.save(sess.movies[0], None, sess.movie_type, sheet=1)
        except Exception as e:  # noqa: BLE001
            done(sess, backend, token, f"Ошибка: {e}")
            return
        done(sess, backend, token, "Film added to watchlist")
    elif emoji == "⏭️":
        sess.movies = sess.movies[1:]
        show_movie_result(sess, backend, token)


def _save_movie_watched(sess, backend, token):
    comment = sess.comment.strip() or None
    try:
        ms.save(sess.movies[0], sess.rating, sess.movie_type, comment=comment)
    except Exception as e:  # noqa: BLE001
        done(sess, backend, token, f"Ошибка сохранения: {e}")
        return
    done(sess, backend, token, "Film saved")


def _pick_category(sess, backend, token, index):
    cats = sheet_writer.categories if sheet_writer else []
    if index < 0 or index >= len(cats):
        send(sess, backend, token, "Нет такой категории, попробуй снова.")
        return
    _save_expense(sess, backend, token, cats[index])


def _save_expense(sess, backend, token, category):
    try:
        sheet_writer.write_to_gsheet(sess.amount, category, sess.comment.strip())
    except Exception as e:  # noqa: BLE001
        done(sess, backend, token, f"Ошибка сохранения: {e}")
        return
    done(sess, backend, token, "Expense saved")


if __name__ == "__main__":
    log(f"ready — {len(nm.db)} notes indexed")
    serve(PORT, talk, on_event)
