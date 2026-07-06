"""Telegram frontend. Same flows/wording as the original bot.py, restructured:

  - state lives in a per-chat Session (was: attributes on the bot singleton);
  - the bot is admin-only at the door — every message and callback from another
    chat is ignored (and reported to the admin once). Previously only the two
    save actions were gated, so anyone could search your notes or write to the
    expense sheet;
  - handlers run sequentially (threaded=False) — no shared-state races;
  - transcription/gsheets/TMDb calls are wrapped, so one network error doesn't
    kill a handler silently;
  - temp files go through tempfile instead of fixed names in the CWD.
"""

from __future__ import annotations

import logging
import os
import random
import tempfile

import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from notebot import session as S
from notebot.actions import Actions
from notebot.integrations import movies
from notebot.integrations.ocr import get_text_on_image
from notebot.integrations.transcribe import transcribe_audio, Punctuator
from notebot.session import SessionStore
from notebot.storage import EventLog

logger = logging.getLogger("notebot.telegram")

THOUGHT_TEMPLATE = "[{}] {}\n{} ({}) [[{}]]\n\n"


# --- markups ---------------------------------------------------------------------
def voice_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 2
    markup.add(InlineKeyboardButton("В заметки", callback_data="save_note"),
               InlineKeyboardButton("В фильмы", callback_data="find_film"),
               InlineKeyboardButton("Мысли", callback_data="get_thoughts"),
               InlineKeyboardButton("+тэг", callback_data="hashtag"))
    return markup


def film_tv_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 2
    markup.add(InlineKeyboardButton("Фильм", callback_data="save_movie"),
               InlineKeyboardButton("Сериал", callback_data="save_tv"))
    return markup


def check_movie_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 3
    markup.add(InlineKeyboardButton("Просмотрено", callback_data="get_rating"),
               InlineKeyboardButton("На будущее", callback_data="to_watchlist"),
               InlineKeyboardButton("Следующий", callback_data="another_movie"))
    return markup


def write_movie_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 1
    markup.add(InlineKeyboardButton("Сохранить", callback_data="write_movie"))
    return markup


def category_markup(categories):
    markup = InlineKeyboardMarkup()
    markup.row_width = 2
    markup.add(*[InlineKeyboardButton(c, callback_data='category_' + c) for c in categories])
    return markup


def tag_markup(tags):
    markup = InlineKeyboardMarkup()
    markup.row_width = max(len(tags), 1)
    markup.add(*[InlineKeyboardButton('#' + t, callback_data=f"add_tag_{t}") for t in tags])
    return markup


def thoughts_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 5
    buttons = [InlineKeyboardButton(str(i + 1), callback_data=f"add_link_{i}") for i in range(5)]
    buttons += [InlineKeyboardButton("Следующие", callback_data="next_thoughts"),
                InlineKeyboardButton("Сохранить", callback_data="save_note")]
    markup.add(*buttons)
    return markup


def format_thoughts(nearest):
    return ''.join(
        THOUGHT_TEMPLATE.format(i + 1, n[n['search_field']][n['nearest_field']][:250],
                                round(float(n['distance']), 2), n['search_field'], n['name'])
        for i, n in enumerate(nearest))


# --- entry point -----------------------------------------------------------------
def run(cfg, nm):
    cfg.require("tg_api_token", "admin_chat_id", "punct_model", "tmdb_api_key")
    if cfg.proxy:
        telebot.apihelper.proxy = {'https': cfg.proxy}

    # sequential update processing: handlers share the NoteManager and sessions
    bot = telebot.TeleBot(cfg["tg_api_token"], threaded=False)
    admin_chat_id = str(cfg["admin_chat_id"])
    ocr_thr = float(cfg.get('ocr_thr', 0.35))

    punct = Punctuator(cfg["punct_model"])
    events = EventLog(cfg.events_db)
    store = SessionStore()
    reported_chats = set()

    # Google/TMDb features are optional — if they fail to init, notes still work.
    sheet_writer = ms = None
    try:
        from notebot.integrations.gsheets import GSheetsClient
        gs = GSheetsClient(cfg.gsheets_cred, proxy=cfg.proxy)
    except Exception as e:
        gs = None
        logger.warning("gsheets disabled: %s", e)
    if gs:
        try:
            from notebot.integrations.finance import SheetWriter
            sheet_writer = SheetWriter(gs)
        except Exception as e:
            logger.warning("finance disabled: %s", e)
        try:
            ms = movies.MovieSaver(note_db_path=cfg.note_db_path, gsheets=gs,
                                   tmdb_api_key=cfg["tmdb_api_key"], proxy=cfg.proxy,
                                   user_id=cfg.os_user_id)
        except Exception as e:
            logger.warning("movies disabled: %s", e)

    import easyocr
    ocr_reader = easyocr.Reader(['en', 'ru'])

    actions = Actions(cfg, nm, events, source="telegram",
                      sheet_writer=sheet_writer, movie_saver=ms, note_subfolder="voice")

    # --- helpers -----------------------------------------------------------------
    def is_admin(message_or_call):
        chat_id = (message_or_call.chat.id if hasattr(message_or_call, "chat")
                   else message_or_call.message.chat.id)
        if str(chat_id) == admin_chat_id:
            return True
        if chat_id not in reported_chats:
            reported_chats.add(chat_id)
            bot.send_message(admin_chat_id, f"{chat_id} пытается пользоваться ботом!")
        return False

    def sess_for(chat_id):
        sess = store.get(chat_id)
        sess.chat_id = chat_id
        return sess

    def remember(sess, msg):
        sess.to_delete.append(msg.message_id)
        return msg

    def clear(sess):
        for msg_id in sess.to_delete:
            try:
                bot.delete_message(sess.chat_id, msg_id)
            except Exception:
                logger.debug("cannot delete message %s", msg_id)
        sess.to_delete = []
        sess.reset()

    def show_movie(sess):
        """Display sess.movies[0] with poster + actions (was copy-pasted 3x)."""
        if not sess.movies:
            bot.send_message(sess.chat_id, "Фильм не найден :(")
            clear(sess)
            return
        movie = sess.movies[0]
        try:
            info = movies.get_info(movie, type=sess.movie_type)
        except Exception as e:
            logger.exception("tmdb info failed")
            bot.send_message(sess.chat_id, f"Ошибка получения данных: {e}")
            clear(sess)
            return
        description = (f"{info['название']} ({info['год']})\n{info['режиссер']}\n"
                       f"{movie.get('overview', '')[:400]}...")
        poster = info.get('poster_path') or movie.get('poster_path')
        msg = None
        if poster and ms:
            with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
                try:
                    ms.download_poster(poster, out_path=tmp.name)
                    with open(tmp.name, 'rb') as img:
                        msg = bot.send_photo(sess.chat_id, img, caption=description,
                                             reply_markup=check_movie_markup())
                except Exception:
                    logger.exception("poster failed")
        if msg is None:
            msg = bot.send_message(sess.chat_id, description, reply_markup=check_movie_markup())
        remember(sess, msg)
        sess.state = S.MOVIE_RESULT

    def show_thoughts(sess):
        page = sess.nearest[:5]
        text = format_thoughts(page)
        if not text:
            bot.send_message(sess.chat_id, "Не найдено похожих заметок")
            return
        remember(sess, bot.send_message(sess.chat_id, text, reply_markup=thoughts_markup()))
        sess.state = S.THOUGHTS

    def saved_note(sess, call):
        try:
            name = actions.save_note(sess)
        except Exception as e:
            logger.exception("note save failed")
            bot.send_message(sess.chat_id, f"Ошибка сохранения: {e}")
            return
        bot.answer_callback_query(call.id, f"Note saved: {name}")
        clear(sess)

    # --- handlers ------------------------------------------------------------------
    @bot.message_handler(commands=["start"])
    def start_message(message):
        if not is_admin(message):
            return
        sess_for(message.chat.id).text = ""
        bot.send_message(message.chat.id, "Привет!")

    @bot.message_handler(content_types=["voice"])
    def handle_voice(message):
        if not is_admin(message):
            return
        sess = sess_for(message.chat.id)
        try:
            file_info = bot.get_file(message.voice.file_id)
            voice_file = bot.download_file(file_info.file_path)
            with tempfile.NamedTemporaryFile(suffix=".ogg") as tmp:
                tmp.write(voice_file)
                tmp.flush()
                raw = transcribe_audio(tmp.name, "ru-RU")
            punctuated = punct.apply(raw)
        except Exception as e:
            logger.exception("transcription failed")
            bot.send_message(message.chat.id, f"Не удалось распознать голосовое: {e}")
            return
        events.record("telegram", "transcription", raw_text=raw, punctuated=punctuated)

        if sess.state in (S.MOVIE_COMMENT, S.EXPENSE_CATEGORY):
            sess.comment += punctuated + ' '
            remember(sess, bot.send_message(message.chat.id, punctuated))
        else:
            sess.text += punctuated + " "
            remember(sess, bot.send_message(message.chat.id, punctuated,
                                            reply_markup=voice_markup()))

    @bot.message_handler(content_types=['photo'])
    def handle_image(message):
        if not is_admin(message):
            return
        sess = sess_for(message.chat.id)
        file = bot.get_file(message.photo[-1].file_id)
        image = bot.download_file(file.file_path)
        with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
            tmp.write(image)
            tmp.flush()
            text = get_text_on_image(ocr_reader, tmp.name, min_line_len=2,
                                     min_confidence=ocr_thr)
        if message.caption:
            text += '\n\n' + message.caption
        sess.text += text + " "
        remember(sess, bot.send_message(message.chat.id, text, reply_markup=voice_markup()))

    @bot.message_handler(content_types=["text"])
    def handle_text(message):
        if not is_admin(message):
            return
        sess = sess_for(message.chat.id)
        text = message.text

        if text.startswith("/clear"):
            clear(sess)
        elif text.startswith("/random_number"):
            bot.send_message(message.chat.id, random.randint(0, 100))
        elif text.startswith("/yes_or_no"):
            bot.send_message(message.chat.id, random.choice(("yes", "no")))
        elif sess.state == S.MOVIE_TYPE:
            try:
                sess.year = int(text)
            except ValueError:
                remember(sess, bot.send_message(message.chat.id,
                                                "### Error processing year, try again. ###"))
        elif sess.state == S.MOVIE_RATING:
            try:
                sess.rating = int(text)
                sess.state = S.MOVIE_COMMENT
                remember(sess, bot.send_message(message.chat.id, "Добавь комментарий",
                                                reply_markup=write_movie_markup()))
            except ValueError:
                remember(sess, bot.send_message(message.chat.id,
                                                "### Error processing rating, try again. ###"))
        elif sess.state in (S.MOVIE_COMMENT, S.EXPENSE_CATEGORY):
            sess.comment += text + ' '
        elif sess.state == S.TAG:
            sess.tags.append(text)
        else:
            try:
                amount = int(text)
            except ValueError:
                sess.text += text + " "
                remember(sess, bot.send_message(message.chat.id, sess.text,
                                                reply_markup=voice_markup()))
                return
            if not sheet_writer:
                bot.send_message(message.chat.id, "Финансы недоступны")
                return
            sess.amount = amount
            sess.state = S.EXPENSE_CATEGORY
            remember(sess, bot.send_message(sess.chat_id,
                                            f"Сумма: {amount}\nУкажите категорию",
                                            reply_markup=category_markup(sheet_writer.categories)))

    @bot.callback_query_handler(func=lambda call: True)
    def callback_query(call):
        if not is_admin(call):
            bot.answer_callback_query(call.id, "Not available")
            return
        sess = sess_for(call.message.chat.id)

        if call.data == "save_note":
            saved_note(sess, call)

        elif call.data == "find_film":
            remember(sess, bot.send_message(sess.chat_id, "Укажи год, если возможно.",
                                            reply_markup=film_tv_markup()))
            sess.year = None
            sess.state = S.MOVIE_TYPE
        elif call.data in ("save_movie", "save_tv"):
            sess.movie_type = 'movie' if call.data == "save_movie" else 'tv'
            try:
                sess.movies = movies.get_movies(sess.text, year=sess.year, language='ru',
                                                type=sess.movie_type)
            except Exception as e:
                logger.exception("tmdb search failed")
                bot.send_message(sess.chat_id, f"Ошибка поиска: {e}")
                clear(sess)
                return
            show_movie(sess)
        elif call.data == "another_movie":
            try:
                bot.delete_message(sess.chat_id, sess.to_delete[-1])
            except Exception:
                pass
            sess.movies = sess.movies[1:]
            show_movie(sess)
        elif call.data == "get_rating":
            remember(sess, bot.send_message(sess.chat_id, "Введи оценку от 1 до 10",
                                            reply_markup=write_movie_markup()))
            sess.state = S.MOVIE_RATING
        elif call.data == "write_movie":
            try:
                actions.save_movie(sess)
            except Exception as e:
                logger.exception("movie save failed")
                bot.send_message(sess.chat_id, f"Ошибка сохранения: {e}")
                return
            bot.answer_callback_query(call.id, "Film saved")
            clear(sess)
        elif call.data == "to_watchlist":
            try:
                actions.save_movie(sess, watchlist=True)
            except Exception as e:
                logger.exception("watchlist save failed")
                bot.send_message(sess.chat_id, f"Ошибка сохранения: {e}")
                return
            bot.answer_callback_query(call.id, "Film added to watchlist")
            clear(sess)

        elif call.data == "hashtag":
            sess.state = S.TAG
            sess.suggested_tags = nm.suggest_tags(sess.text)
            if not sess.suggested_tags:
                bot.send_message(sess.chat_id, "Не найдено подходящих тегов. Введи название тега")
            else:
                remember(sess, bot.send_message(sess.chat_id, "Введи название тега",
                                                reply_markup=tag_markup(sess.suggested_tags)))
        elif call.data.startswith("add_tag_"):
            sess.tags.append(call.data.split('add_tag_')[1])

        elif call.data == "get_thoughts":
            sess.nearest = nm.get_nearest_all_fields(sess.text, k=25)
            show_thoughts(sess)
        elif call.data == "next_thoughts":
            sess.nearest = sess.nearest[5:]
            if not sess.nearest:
                bot.send_message(sess.chat_id, "Конец")
                clear(sess)
            else:
                try:
                    bot.delete_message(sess.chat_id, sess.to_delete[-1])
                except Exception:
                    pass
                show_thoughts(sess)
        elif call.data.startswith("add_link_"):
            i = int(call.data.split('add_link_')[1])
            page = sess.nearest[:5]
            if i < len(page):
                sess.links.append(page[i]['name'])

        elif call.data.startswith("category_"):
            category = call.data.split('category_')[1]
            try:
                actions.save_expense(sess, category)
            except Exception as e:
                logger.exception("expense save failed")
                bot.send_message(sess.chat_id, f"Ошибка сохранения: {e}")
                return
            bot.answer_callback_query(call.id, "Expense saved")
            clear(sess)
        elif call.data == "clear":
            clear(sess)

        # close the loading spinner for branches that didn't answer explicitly
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

    logger.info("telegram bot ready — %d notes indexed", len(nm.db))
    bot.infinity_polling()
