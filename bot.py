import os
import re
import datetime
import json
import random
import pandas as pd
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
from transcribe import ogg2wav, transcribe_audio, Punctuator
from parse import parse_message

from finance import SheetWriter
from movies import get_movies, MovieSaver

class NoteBot(telebot.TeleBot):
    def __init__(self, cred_path="config/telegram.json"):
        with open(cred_path, "r") as f:
            d = json.load(f)
            api_token = d["token"]
            self.db_path = d["db_path"]
            self.admin_chat_id = d["chat_id"]
        super().__init__(api_token)
        self.lang = "ru-RU"
        self.tags = []
        self.wait_value = False
        self.text = ""
        self.rating = None

    def transcribe_message(self, message):
        self.tags = []
        file_info = self.get_file(message.voice.file_id)
        voice_file = self.download_file(file_info.file_path)
        with open("tmp.ogg", "wb") as new_file:
            new_file.write(voice_file)

        wav_path = ogg2wav("tmp.ogg")
        raw = transcribe_audio(wav_path, self.lang)
        os.system("rm tmp.*")
        punctuated = punct.apply(raw)
        return raw, punctuated
    
    def save_text(self):
        dt = str(datetime.datetime.now())
        dt_pfx = re.sub(r"[:]", "-", dt.split(".")[0])
        sv_path = os.path.join(self.db_path, f"{dt_pfx}.md")
        
        note = parse_message(self.text, self.tags)
        with open(sv_path, "w") as f:
            f.write(note)
        self.clear()
    
    def get_config(self):
        return self.model.config

    def handle_expense(self, text):
        values = sheet_writer.parse_expense(text)
        self.expense = values
        confirm_message = "Сумма: {}\nКатегория: {}\nКомментарий: {}".format(*values)
        self.send_message(self.chat_id, confirm_message, reply_markup=expense_markup())

    def clear(self):
        self.text = ''
        self.movie = self.rating = self.year = None
        self.wait_value = None
        self.tags = []


bot = NoteBot()
sheet_writer = SheetWriter()
punct = Punctuator()
ms = MovieSaver()

def expense_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 1
    markup.add(InlineKeyboardButton("Сохранить", callback_data="save_expense"))
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

def voice_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 3
    markup.add(InlineKeyboardButton("В заметки", callback_data="save_note"),
               InlineKeyboardButton("В расходы", callback_data="parse_expense"),
               InlineKeyboardButton("В фильмы", callback_data="find_film"),
               InlineKeyboardButton("+тэг", callback_data="hashtag"))
    return markup


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data == "save_note":
        if str(bot.chat_id) == str(bot.admin_chat_id):
            bot.save_text()
            bot.answer_callback_query(call.id, "Note saved")
        else:
            bot.send_message(bot.chat_id, "Сохранение недоступно.")
            bot.send_message(bot.admin_chat_id, f"{bot.chat_id} пытается сохранить тебе заметку!")
    elif call.data == "parse_expense":
        bot.handle_expense(bot.text)
    elif call.data == "save_expense":
        sheet_writer.write_to_gsheet(*bot.expense)
        bot.clear()
        bot.answer_callback_query(call.id, "Expense saved")
    elif call.data == "find_film":
        bot.send_message(bot.chat_id, "Укажи год, если возможно.", reply_markup=film_tv_markup())
        bot.year = None
        bot.wait_value = 'year'
    elif call.data == "save_movie":
        bot.type = 'movie'
        bot.movies = get_movies(bot.text, year=bot.year, language='ru', type='movie')
        movie = bot.movies[0]
        name = movie.get('title', movie.get('name'))
        year = pd.to_datetime(movie.get('release_date', movie.get('first_air_date'))).year
        description = f"{name} ({year})\n{movie['overview'][:250]}..."
        bot.send_message(bot.chat_id, description, reply_markup=check_movie_markup())
    elif call.data == "save_tv":
        bot.type = 'tv'
        bot.movies = get_movies(bot.text, year=bot.year, language='ru', type='tv')
        movie = bot.movies[0]
        name = movie.get('title', movie.get('name'))
        year = pd.to_datetime(movie.get('release_date', movie.get('first_air_date'))).year
        description = f"{name} ({year})\n{movie['overview'][:250]}..."
        bot.send_message(bot.chat_id, description, reply_markup=check_movie_markup())
    elif call.data == "another_movie":
        bot.movies = bot.movies[1:]
        if len(bot.movies) > 0:
            movie = bot.movies[0]
            name = movie.get('title', movie.get('name'))
            year = pd.to_datetime(movie.get('release_date', movie.get('first_air_date'))).year
            description = f"{name} ({year})\n{movie['overview'][:250]}..."
            bot.send_message(bot.chat_id, description, reply_markup=check_movie_markup())
        else:
            bot.send_message(bot.chat_id, "Фильм не найден :(")
            bot.clear()
            bot.answer_callback_query(call.id, "Film search ended")
    elif call.data == "get_rating":
        bot.send_message(bot.chat_id, "Введи оценку от 1 до 10", reply_markup=write_movie_markup())
        bot.wait_value = 'rating'
    elif call.data == "write_movie":
        ms.save(bot.movies[0], bot.rating, bot.type)
        bot.clear()
        bot.answer_callback_query(call.id, "Film saved")
    elif call.data == "to_watchlist":
        ms.save(bot.movies[0], bot.rating, bot.type, 1)
        bot.clear()
    elif call.data == "hashtag":
        bot.answer_callback_query(call.id)
        bot.wait_value = "tag"
        bot.send_message(bot.chat_id, "Введи название тега")


@bot.message_handler(commands=["start"])
def start_message(message):
    bot.text = ""
    bot.chat_id = message.chat.id
    bot.send_message(message.chat.id, "Привет!")


@bot.message_handler(content_types=["voice"])
def handle_voice(message):
    bot.chat_id = message.chat.id
    raw, punctuated = bot.transcribe_message(message)
    if "трат" in raw[:15]:
        bot.handle_expense(raw)
    else:
        bot.text_raw = bot.text
        bot.text_raw += raw + " "
        bot.text += punctuated + " "
        bot.send_message(message.chat.id, punctuated, reply_markup=voice_markup())


@bot.message_handler(content_types=["text"])
def handle_text(message):
    bot.chat_id = message.chat.id
    if message.text.startswith("/clear"):
        bot.clear()
    elif message.text.startswith("/random_number"):
        bot.send_message(message.chat.id, random.randint(0, 100))
    elif message.text.startswith("/yes_or_no"):
        bot.send_message(message.chat.id, random.choice(("yes", "no")))
    elif bot.wait_value == "year":
        try:
            bot.year = int(message.text)
        except ValueError:
            pass
    elif bot.wait_value == "rating":
        try:
            bot.rating = int(message.text)
        except ValueError:
            pass
    elif bot.wait_value == "tag":
        bot.tags.append(message.text)
    else:
        bot.text += message.text + " "
        bot.send_message(message.chat.id, bot.text, reply_markup=voice_markup())
    

bot.infinity_polling()