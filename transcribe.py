import sys
from torch import package
import speech_recognition as sr
from pydub import AudioSegment

MODEL_PATH = "../models/silero/v2_4lang_q.pt"
sys.path.append('/home/booydar/Desktop/projects/tg_notebot/env_notebot/lib/python3.9/site-packages/ffprobe')

def ogg2wav(ogg_path):
    sound = AudioSegment.from_ogg(ogg_path)
    wav_path = ogg_path.split('.ogg')[0] + '.wav'
    sound.export(wav_path, format="wav")
    return wav_path


def transcribe_audio(file_path, language="ru-RU"):
    rec = sr.Recognizer()
    with sr.AudioFile(file_path) as source:
        audio = rec.record(source)
    transcription = rec.recognize_google(audio, language=language)
    return transcription


class Punctuator:
    def __init__(self):
        imp = package.PackageImporter(MODEL_PATH)
        self.model = imp.load_pickle("te_model", "model")

    def apply(self, text, lang='ru'):
        # print('raw text: ', text)
        # print('enhanced: ', self.model.enhance_text(text, lang))
        text = text[0].lower() + text[1:]
        return self.model.enhance_text(text, lang)