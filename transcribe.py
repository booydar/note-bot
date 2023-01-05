import speech_recognition as sr
from pydub import AudioSegment
import sys

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
    