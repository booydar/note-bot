import os
import sys
import json
import random
import pandas as pd
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
from transcribe import transcribe_audio, Punctuator
from parse import parse_message

from thoughts import *

class NoteBot(telebot.TeleBot):
    def __init__(self, api_token, note_db_path, lang='ru-RU'):
        super().__init__(api_token)
        self.db_path = note_db_path
        self.lang = lang
        self.tags = []
        self.links = []
        self.wait_value = False
        self.text = ""

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
        sv_path = os.path.join(self.db_path, f"{note_name}.md")
        
        with open(sv_path, "w") as f:
            f.write(note_text)
        self.clear()
        tm.parse_thoughts()

    def clear(self):
        self.text = ''
        self.wait_value = None
        self.tags = []
        self.links = []

with open('config.json', 'r') as f:
    config = json.load(f)
bot = NoteBot(config['tg_api_token'], config['note_db_path'], config['language'])
tm = ThoughtManager(config['note_db_path'], model_name=config["embedding_model"])
punct = Punctuator("./models/v2_4lang_q.pt")


def tag_markup():
    markup = InlineKeyboardMarkup()
    buttons = [InlineKeyboardButton('#'+bot.suggested_tags[i], callback_data=f"add_tag_{bot.suggested_tags[i]}") for i in range(len(bot.suggested_tags))]
    markup.row_width = len(buttons)
    markup.add(*buttons)
    return markup

def voice_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 3
    markup.add(InlineKeyboardButton("В заметки", callback_data="save_note"),
               InlineKeyboardButton("Похожее", callback_data="get_thoughts"),
               InlineKeyboardButton("+тэг", callback_data="hashtag"))
    return markup

def thoughts_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 5
    buttons = [InlineKeyboardButton(str(i+1), callback_data=f"add_link_{i}") for i in range(5)] 
    buttons += [InlineKeyboardButton("Следующие", callback_data="next_thoughts"), InlineKeyboardButton("Закончить", callback_data="clear")]
    markup.add(*buttons)
    return markup


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data == "save_note":
        bot.save_text()
        tm.parse_thoughts()    
        bot.answer_callback_query(call.id, "Note saved")    
    elif call.data == "hashtag":
        bot.answer_callback_query(call.id)
        bot.wait_value = "tag"
        bot.suggested_tags = tm.suggest_tags(bot.text)
        bot.send_message(bot.chat_id, "Введи название тега", reply_markup=tag_markup())
    elif call.data.startswith("add_tag_"):
        tag_name = call.data.split('add_tag_')[1]
        bot.tags.append(tag_name)
    elif call.data.startswith("add_link_"):
        link = int(call.data.split('add_link_')[1])
        bot.links.append(bot.nearest.name.values[link])
    elif call.data == "get_thoughts":
        bot.nearest = tm.get_nearest(bot.text, k=25)
        nearest = bot.nearest[:5]
        template = "{}\n{} [[{}]]\n\n"
        thoughts = [template.format(t, round(float(d), 2), n) for t, d, n in zip(nearest.thoughts, nearest.distance, nearest.name)]
        bot.send_message(bot.chat_id, ''.join(thoughts), reply_markup=thoughts_markup())
    elif call.data == "next_thoughts":
        bot.nearest = bot.nearest[5:]
        if len(bot.nearest) == 0:
            bot.send_message(bot.chat_id, "Конец")
            bot.clear()
        else:
            nearest = bot.nearest[:5]
            template = "{}\n{} [[{}]]\n\n"
            thoughts = [template.format(t, round(float(d), 2), n) for t, d, n in zip(nearest.thoughts, nearest.distance, nearest.name)]
            bot.send_message(bot.chat_id, ''.join(thoughts), reply_markup=thoughts_markup())
        
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
    elif bot.wait_value == "tag":
        bot.tags.append(message.text)
    else:
        bot.text += message.text + " "
        bot.send_message(message.chat.id, bot.text, reply_markup=voice_markup())
    

bot.infinity_polling()