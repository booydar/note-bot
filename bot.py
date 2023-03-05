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
from finance import SheetWriter

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
        self.model = Model()
        self.wait_value = False
        self.text = ""

    def transcribe_message(self, message):
        self.tags = []
        file_info = self.get_file(message.voice.file_id)
        voice_file = self.download_file(file_info.file_path)
        with open("tmp.ogg", "wb") as new_file:
            new_file.write(voice_file)

        wav_path = ogg2wav("tmp.ogg")
        transcription = transcribe_audio(wav_path, self.lang)
        os.system("rm tmp.*")
        return transcription
    
    def save_text(self):
        dt = str(datetime.datetime.now())
        dt_pfx = re.sub(r"[:]", "-", dt.split(".")[0])
        sv_path = os.path.join(self.db_path, f"{dt_pfx}.md")
        
        note = parse_message(self.text, self.tags)
        with open(sv_path, "w") as f:
            f.write(note)
        self.text = ""
    
    def get_config(self):
        return self.model.config

    def handle_expense(self, text):
        values = sheet_writer.parse_expense(text)
        self.expense = values
        confirm_message = "Сумма: {}\nКатегория: {}\nКомментарий: {}".format(*values)
        self.send_message(self.chat_id, confirm_message, reply_markup=expense_markup())

    def clear(self):
        self.text = ''


bot = NoteBot()
sheet_writer = SheetWriter()
model = Model()

def expense_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 1
    markup.add(InlineKeyboardButton("Сохранить", callback_data="save_expense"))
    return markup

def voice_markup():
    markup = InlineKeyboardMarkup()
    markup.row_width = 3
    markup.add(InlineKeyboardButton("В расходы", callback_data="parse_expense"),
               InlineKeyboardButton("В заметки", callback_data="save_note"),
               InlineKeyboardButton("+тэг", callback_data="hashtag"),
               InlineKeyboardButton("Ответ", callback_data="answer"))
    return markup


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data == "save_note":
        if str(bot.chat_id) == str(bot.admin_chat_id):
            bot.save_text()
            bot.answer_callback_query(call.id, "Note saved")
        else:
            bot.send_message(bot.chat_id, "Ты не Айдар, не буду ничего сохранять!")
            bot.send_message(bot.admin_chat_id, f"{bot.chat_id} пытается сохранить тебе заметку!")
    elif call.data == "parse_expense":
        bot.handle_expense(bot.text)
    elif call.data == "save_expense":
        sheet_writer.write_to_gsheet(*bot.expense)
        bot.clear()
        bot.answer_callback_query(call.id, "Expense saved")
    elif call.data == "hashtag":
        bot.answer_callback_query(call.id)
        bot.wait_value = "tag"
        bot.send_message(bot.chat_id, "Введи название тега")
    elif call.data == "answer":
        answer = model.answer(bot.text)
        bot.send_message(bot.chat_id, answer)
        bot.clear()


@bot.message_handler(commands=["start"])
def start_message(message):
    bot.text = ""
    bot.chat_id = message.chat.id
    bot.send_message(message.chat.id, "Привет!")


@bot.message_handler(content_types=["voice"])
def handle_voice(message):
    bot.chat_id = message.chat.id
    transcription = bot.transcribe_message(message)
    if "трат" in transcription[:15]:
        bot.handle_expense(transcription)
    else:
        bot.text += transcription + " "
        bot.send_message(message.chat.id, transcription, reply_markup=voice_markup())


@bot.message_handler(content_types=["text"])
def handle_text(message):
    bot.chat_id = message.chat.id
    if message.text.startswith("/clear"):
        model.clear_context()
        bot.clear()
    elif message.text.startswith("/random_number"):
        bot.send_message(message.chat.id, random.randint(0, 100))
    elif message.text.startswith("/yes_or_no"):
        bot.send_message(message.chat.id, random.choice(("yes", "no")))
    elif message.text.startswith("/set_"):
        bot.wait_value = message.text.split("/set_")[1]
        bot.send_message(message.chat.id, f"set {bot.wait_value} to what value?")
    elif message.text.startswith("/config"):
        msg = "; ".join([f"{k}-{v}" for k, v in bot.get_config().items()])
        bot.send_message(message.chat.id, msg)
    elif message.text.startswith("/show_history"):
        history = model.show_history()
        if not history:
            history = 'История пуста.'
        bot.send_message(message.chat.id, history)
    elif bot.wait_value == "tag":
        bot.tags.append(message.text)
        bot.wait_value = False
    elif bot.wait_value:
        if "." in message.text:
            bot.model.config[bot.wait_value] = float(message.text)
        else:
            bot.model.config[bot.wait_value] = int(message.text)
        bot.wait_value = False
    else:
        bot.text += message.text + " "
        bot.send_message(message.chat.id, bot.text, reply_markup=voice_markup())
    

bot.infinity_polling()