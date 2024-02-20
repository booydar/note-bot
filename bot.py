import os
import sys
import json
import random
import pandas as pd
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
from transcribe import transcribe_audio, Punctuator
from parse import parse_message

from finance import SheetWriter
from movies import get_movies, get_info, MovieSaver
from thoughts import ThoughtManager

CONFIG_FOLDER = os.getenv("config")
config_path = os.path.join(CONFIG_FOLDER, 'var.json')
with open(config_path, 'r') as f:
    config = json.load(f)
    sys.path.append(config['ffprobe'])
    gsheets_cred = os.path.join(CONFIG_FOLDER, 'gsheets.json')

class NoteBot(telebot.TeleBot):
    def __init__(self, api_token, note_db_path, admin_chat_id):
        super().__init__(api_token)
        self.to_delete = []
        self.db_path = note_db_path
        self.admin_chat_id = admin_chat_id
        self.lang = "ru-RU"
        self.clear()

    def transcribe_message(self, message):
        self.tags = []
        file_info = self.get_file(message.voice.file_id)
        voice_file = self.download_file(file_info.file_path)
        with open("tmp.ogg", "wb") as new_file:
            new_file.write(voice_file)

        raw = transcribe_audio("tmp.ogg", self.lang)
        os.system("rm tmp.ogg")
        punctuated = punct.apply(raw)
        return raw, punctuated
    
    def save_text(self):
        note_text, note_name = parse_message(self.text, self.tags, self.links)
        sv_path = os.path.join(self.db_path, f"voice/{note_name}.md")
        
        with open(sv_path, "w") as f:
            f.write(note_text)
        self.clear()
        tm.parse_thoughts()
        
    def handle_expense(self, amount):
        self.amount = amount
        self.wait_value = 'comment'
        msg = self.send_message(self.chat_id, f"Сумма: {amount}\nУкажите категорию", reply_markup=category_markup())
        return msg.message_id

    def clear(self):
        self.text = ''
        self.movie = self.rating = self.year = self.comment = self.amount = None
        self.wait_value = None
        self.tags = []
        self.links = []
        print(f'Deleting {self.to_delete}')
        for msg_id in self.to_delete:
            try:
                bot.delete_message(bot.chat_id, msg_id)
            except Exception:
                print(f'Cannot delete message {msg_id}')
        self.to_delete = []


bot = NoteBot(config['tg_api_token'], config['note_db_path'], config['admin_chat_id'])
sheet_writer = SheetWriter(gsheets_cred)
punct = Punctuator(config['punct_model'])
ms = MovieSaver(gsheets_cred, config['tmdb_api_key'])
tm = ThoughtManager(config['note_db_path'], model_name=config['embedding_model'], save_path=config['cache_path'], batch_size=int(config['batch_size']))

def expense_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 1
    markup.add(InlineKeyboardButton("Сохранить", callback_data="save_expense"))
    return markup

def category_markup():
    markup = InlineKeyboardMarkup()
    buttons = [InlineKeyboardButton(c, callback_data='category_' + c) for c in sheet_writer.categories]
    markup.row_width = 2
    markup.add(*buttons)
    return markup

def tag_markup():
    markup = InlineKeyboardMarkup()
    buttons = [InlineKeyboardButton('#'+bot.suggested_tags[i], callback_data=f"add_tag_{bot.suggested_tags[i]}") for i in range(len(bot.suggested_tags))]
    markup.row_width = len(buttons)
    markup.add(*buttons)
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
    markup.row_width = 2
    markup.add(InlineKeyboardButton("В заметки", callback_data="save_note"),
               InlineKeyboardButton("В фильмы", callback_data="find_film"),
               InlineKeyboardButton("Мысли", callback_data="get_thoughts"),
               InlineKeyboardButton("+тэг", callback_data="hashtag"))
    return markup

def thoughts_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 5
    buttons = [InlineKeyboardButton(str(i+1), callback_data=f"add_link_{i}") for i in range(5)] 
    buttons += [InlineKeyboardButton("Следующие", callback_data="next_thoughts"), InlineKeyboardButton("Сохранить", callback_data="save_note")]
    markup.add(*buttons)
    return markup


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data == "save_note":
        if str(bot.chat_id) == str(bot.admin_chat_id):
            bot.save_text()
            bot.answer_callback_query(call.id, "Note saved")
        else:
            bot.answer_callback_query(call.id, "Not available")
            bot.send_message(bot.admin_chat_id, f"{bot.chat_id} пытается сохранить тебе заметку!")

    elif call.data == "find_film":
        msg = bot.send_message(bot.chat_id, "Укажи год, если возможно.", reply_markup=film_tv_markup())
        bot.to_delete.append(msg.message_id)
        bot.year = None
        bot.wait_value = 'year'
    elif call.data == "save_movie":
        bot.type = 'movie'
        bot.movies = get_movies(bot.text, year=bot.year, language='ru', type='movie')
        if len(bot.movies) == 0:
            bot.send_message(bot.chat_id, "Фильм не найден :(")
            bot.clear()
            bot.answer_callback_query(call.id, "Film search ended")
        else:
            movie = bot.movies[0]
            info = get_info(movie, type=bot.type)
            description = f"{info['название']} ({info['год']})\n{info['режиссер']}\n{movie['overview'][:400]}..."
            os.system(f"wget https://image.tmdb.org/t/p/w600_and_h900_bestv2{movie.pop('poster_path')} -O tmp.jpg")
            with open('tmp.jpg', 'rb') as img:
                msg = bot.send_photo(bot.chat_id, img, caption=description, reply_markup=check_movie_markup())
            os.system('rm -r tmp.jpg')
            bot.to_delete.append(msg.message_id)
    elif call.data == "save_tv":
        bot.type = 'tv'
        bot.movies = get_movies(bot.text, year=bot.year, language='ru', type='tv')
        if len(bot.movies) == 0:
            bot.send_message(bot.chat_id, "Фильм не найден :(")
            bot.clear()
            bot.answer_callback_query(call.id, "Film search ended")
        else:
            movie = bot.movies[0]
            info = get_info(movie, type=bot.type)
            description = f"{info['название']} ({info['год']})\n{info['режиссер']}\n{movie['overview'][:400]}..."
            os.system(f"wget https://image.tmdb.org/t/p/w600_and_h900_bestv2{movie.pop('poster_path')} -O tmp.jpg")
            with open('tmp.jpg', 'rb') as img:
                msg = bot.send_photo(bot.chat_id, img, caption=description, reply_markup=check_movie_markup())
            os.system('rm -r tmp.jpg')
            bot.to_delete.append(msg.message_id)
    elif call.data == "another_movie":
        bot.delete_message(bot.chat_id, bot.to_delete[-1])
        bot.movies = bot.movies[1:]
        if len(bot.movies) > 0:
            movie = bot.movies[0]
            info = get_info(movie, type=bot.type)
            description = f"{info['название']} ({info['год']})\n{info['режиссер']}\n{movie['overview'][:400]}..."
            os.system(f"wget https://image.tmdb.org/t/p/w600_and_h900_bestv2{movie.pop('poster_path')} -O tmp.jpg")
            with open('tmp.jpg', 'rb') as img:
                msg = bot.send_photo(bot.chat_id, img, caption=description, reply_markup=check_movie_markup())
            os.system('rm -r tmp.jpg')
            bot.to_delete.append(msg.message_id)
        else:
            bot.send_message(bot.chat_id, "Фильм не найден :(")
            bot.clear()
            bot.answer_callback_query(call.id, "Film search ended")
    elif call.data == "get_rating":
        msg = bot.send_message(bot.chat_id, "Введи оценку от 1 до 10", reply_markup=write_movie_markup())
        bot.to_delete.append(msg.message_id)
        bot.wait_value = 'rating'
    elif call.data == "write_movie":
        if str(bot.chat_id) == str(bot.admin_chat_id):
            ms.save(bot.movies[0], bot.rating, bot.type, bot.comment)
        bot.clear()
        bot.answer_callback_query(call.id, "Film saved")
    elif call.data == "to_watchlist":
        if str(bot.chat_id) == str(bot.admin_chat_id):
            ms.save(bot.movies[0], bot.rating, bot.type, sheet=1)
            bot.answer_callback_query(call.id, "Film added to watchlist")
        bot.clear()
    elif call.data == "hashtag":
        bot.answer_callback_query(call.id)
        bot.wait_value = "tag"
        bot.suggested_tags = tm.suggest_tags(bot.text)
        msg = bot.send_message(bot.chat_id, "Введи название тега", reply_markup=tag_markup())
        bot.to_delete.append(msg.message_id)
    elif call.data.startswith("add_tag_"):
        tag_name = call.data.split('add_tag_')[1]
        bot.tags.append(tag_name)
    elif call.data.startswith("add_link_"):
        link = int(call.data.split('add_link_')[1])
        bot.links.append(bot.nearest.name.values[link])
    elif call.data == "get_thoughts":
        bot.nearest = tm.get_nearest(bot.text, k=25)
        nearest = bot.nearest[:5]
        template = "[{}] {}\n{} [[{}]]\n\n"
        thoughts = [template.format(i+1, t, round(float(d), 2), n) \
                    for i, (t, d, n) in enumerate(zip(nearest.thoughts, nearest.distance, nearest.name))]
        msg = bot.send_message(bot.chat_id, ''.join(thoughts), reply_markup=thoughts_markup())
        bot.to_delete.append(msg.message_id)
    elif call.data == "next_thoughts":
        bot.nearest = bot.nearest[5:]
        if len(bot.nearest) == 0:
            msg = bot.send_message(bot.chat_id, "Конец")
            bot.to_delete.append(msg.message_id)
            bot.clear()
        else:
            nearest = bot.nearest[:5]
            template = "[{}] {}\n{} [[{}]]\n\n"
            thoughts = [template.format(i+1, t, round(float(d), 2), n) \
                    for i, (t, d, n) in enumerate(zip(nearest.thoughts, nearest.distance, nearest.name))]
            bot.delete_message(bot.chat_id, bot.to_delete[-1])
            msg = bot.send_message(bot.chat_id, ''.join(thoughts), reply_markup=thoughts_markup())
            bot.to_delete.append(msg.message_id)
        
    elif call.data.startswith("category_"):
        category = call.data.split('category_')[1]
        sheet_writer.write_to_gsheet(bot.amount, category, bot.comment)
        bot.answer_callback_query(call.id, "Expense saved")
        bot.clear()
    elif call.data == "clear":
        bot.clear()


@bot.message_handler(commands=["start"])
def start_message(message):
    bot.text = ""
    bot.chat_id = message.chat.id
    bot.send_message(message.chat.id, "Привет!")


@bot.message_handler(content_types=["voice"])
def handle_voice(message):
    bot.chat_id = message.chat.id
    raw, punctuated = bot.transcribe_message(message)

    if bot.wait_value == 'comment':
        bot.comment = punctuated
        msg = bot.send_message(message.chat.id, punctuated)
        bot.to_delete.append(msg.message_id)
    else:
        bot.text_raw = bot.text
        bot.text_raw += raw + " "
        bot.text += punctuated + " "
        msg = bot.send_message(message.chat.id, punctuated, reply_markup=voice_markup())
        bot.to_delete.append(msg.message_id)


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
            bot.send_message(message.chat.id, "### Error processing year, try again. ###")
    elif bot.wait_value == "rating":
        try:
            bot.rating = int(message.text)
            bot.wait_value = "comment"
            bot.send_message(message.chat.id, "Добавь комментарий", reply_markup=write_movie_markup())
        except ValueError:
            bot.send_message(message.chat.id, "### Error processing rating, try again. ###")

    elif bot.wait_value == "comment":
        bot.comment = message.text
    elif bot.wait_value == "tag":
        bot.tags.append(message.text)
    else:
        try:
            amount = int(message.text)
            msg_id = bot.handle_expense(amount)
            bot.to_delete.append(msg_id)
            return
        except ValueError:
            bot.text += message.text + " "
            msg = bot.send_message(message.chat.id, bot.text, reply_markup=voice_markup())
            bot.to_delete.append(msg.message_id)
    

bot.infinity_polling()