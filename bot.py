import os
import re
import datetime
import json
import random
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
from transcribe import ogg2wav, transcribe_audio
from parse import parse_message
from neural import Model


class NoteBot(telebot.TeleBot):
    def __init__(self, cred_path='creds.txt'):
        with open('config.json', 'r') as f:
            d = json.load(f)
            api_token = d['token']
            self.db_path = d['db_path']
            self.correct_chat_id = d['chat_id']
        super().__init__(api_token)
        self.lang = 'ru-RU'
        self.tags = []
        self.model = Model()
        self.wait_value = False


    def transcribe_message(self, message):
        self.tags = []
        file_info = self.get_file(message.voice.file_id)
        voice_file = self.download_file(file_info.file_path)
        with open('tmp.ogg', 'wb') as new_file:
            new_file.write(voice_file)

        wav_path = ogg2wav('tmp.ogg')
        transcription = transcribe_audio(wav_path, self.lang)
        self.last_message = transcription
        os.system('rm tmp.*')
        return transcription

    
    def save_last_message(self):
        dt = str(datetime.datetime.now())
        dt_pfx = re.sub(r'[:]', '-', dt.split('.')[0])
        sv_path = os.path.join(self.db_path, f'{dt_pfx}.md')
        
        note = parse_message(self.last_message, self.tags)
        with open(sv_path, 'w') as f:
            f.write(note)

    
bot = NoteBot()


def lang_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 2
    markup.add(InlineKeyboardButton("Ru", callback_data="ru-RU"),
                InlineKeyboardButton("En", callback_data="en-EN"))
    return markup


def save_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 3
    markup.add(InlineKeyboardButton("Сохранить", callback_data='save'),
                InlineKeyboardButton("Добавить тэг", callback_data='hashtag'),
                InlineKeyboardButton("Продолжить", callback_data='continue'))
    return markup


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data == "ru-RU":
        bot.answer_callback_query(call.id, "Russian")
        bot.lang = call.data
    elif call.data == "en-EN":
        bot.answer_callback_query(call.id, "English")
        bot.lang = call.data
    elif call.data == 'save':
        # print('chat id', bot.chat_id)
        if str(bot.chat_id) == str(bot.correct_chat_id):
            bot.save_last_message()     
            bot.answer_callback_query(call.id, "Note saved")
        else:
            bot.send_message(bot.chat_id, "Ты не Айдар, не буду ничего сохранять!")
            bot.send_message(bot.correct_chat_id, f"{bot.chat_id} пытается сохранить тебе заметку!")
    elif call.data == 'hashtag':
        bot.answer_callback_query(call.id)
        bot.wait_value = 'tag'
        bot.send_message(bot.chat_id, "Введи название тега")
    elif call.data == 'continue':
        text = bot.model.generate(bot.last_message)
        bot.send_message(bot.chat_id, text)


@bot.message_handler(commands=['start'])
def start_message(message):    
    bot.chat_id = message.chat.id
    bot.send_message(message.chat.id,'Привет!\nМожешь отправить мне голосовую заметку, я всё сохраню.\nВыбери язык:', reply_markup=lang_markup())


@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    bot.chat_id = message.chat.id
    transcription = bot.transcribe_message(message)
    bot.send_message(message.chat.id, transcription, reply_markup=save_markup())


@bot.message_handler(content_types=['text'])
def handle_text(message):
    bot.chat_id = message.chat.id
    if message.text.startswith('/random_number'):
        bot.send_message(message.chat.id, random.randint(0, 100))
    elif message.text.startswith('/yes_or_no'):
        bot.send_message(message.chat.id, random.choice(('yes', 'no')))
    elif message.text.startswith('/language'):
        bot.send_message(message.chat.id, 'Выбери язык:', reply_markup=lang_markup())
    elif message.text.startswith('/set_min_gen_length'):
        bot.send_message(message.chat.id, 'to what value?')
        bot.wait_value = 'min_length'
    elif message.text.startswith('/set_max_gen_length'):
        bot.send_message(message.chat.id, 'to what value?')
        bot.wait_value = 'max_length'
    elif message.text.startswith('/set_num_beams'):
        bot.send_message(message.chat.id, 'to what value?')
        bot.wait_value = 'num_beams'
    elif bot.wait_value == 'tag':
        bot.tags.append(message.text)
        bot.wait_value = False
    elif bot.wait_value:
        bot.model.config[bot.wait_value] = int(message.text)
        bot.wait_value = False
    else:
        bot.last_message = message.text
        bot.send_message(message.chat.id, message.text, reply_markup=save_markup())
        
    

bot.infinity_polling()