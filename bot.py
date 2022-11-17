import os
import re
import datetime
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
from transcribe import ogg2wav, transcribe_audio

class NoteBot(telebot.TeleBot):
    def __init__(self, cred_path='creds.txt'):
        with open('creds.txt', 'r') as f:
            API_TOKEN = f.read()
        super().__init__(API_TOKEN)
        self.lang = 'ru-RU'

        with open('template.md', 'r') as f:
            self.template = f.read()

    def transcribe_message(self, message):
        file_info = self.get_file(message.voice.file_id)
        voice_file = self.download_file(file_info.file_path)
        with open('tmp.ogg', 'wb') as new_file:
            new_file.write(voice_file)

        wav_path = ogg2wav('tmp.ogg')
        transcription = transcribe_audio(wav_path, self.lang)
        self.last_message = transcription
        os.system('rm tmp.*')
        return transcription

    def save_last_message(self, sv_folder='saved_notes'):
        dt = str(datetime.datetime.now())
        dt_pfx = re.sub(r'[^0-9]', '', dt.split('.')[0])
        sv_path = f'{sv_folder}/{dt_pfx}.md'
        
        note = self.template.format(self.last_message)
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
    markup.row_width = 1
    markup.add(InlineKeyboardButton("Save", callback_data='save'))
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
        bot.save_last_message()     
        bot.answer_callback_query(call.id, "Note saved")


@bot.message_handler(commands=['start'])
def start_message(message):    
    bot.send_message(message.chat.id,'Привет!\nМожешь отправить мне голосовую заметку, я всё сохраню.\nВыбери язык:', reply_markup=lang_markup())


@bot.message_handler(content_types=['voice'])
def process_voice(message):
    transcription = bot.transcribe_message(message)
    bot.send_message(message.chat.id, transcription, reply_markup=save_markup())
    

bot.infinity_polling()