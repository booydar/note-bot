import sys
import torch
from torch import package
from speech_recognition import Recognizer, AudioData
from pydub import AudioSegment

# torch.backends.quantized.engine = 'qnnpack'

def transcribe_audio(file_path, language="ru-RU"):
    rec = Recognizer()
    sound = AudioSegment.from_ogg(file_path)
    raw_sound = sound.raw_data

    sample_size = 50 * sound.frame_rate * 4
    sample, raw_sound = raw_sound[:sample_size], raw_sound[sample_size:]
    audio = AudioData(sample, sample_rate=sound.frame_rate, sample_width=sound.frame_width)
    transcription = rec.recognize_google(audio, language=language)

    while len(raw_sound) > 0:
        sample, raw_sound = raw_sound[:sample_size], raw_sound[sample_size:]
        audio = AudioData(sample, sample_rate=sound.frame_rate, sample_width=sound.frame_width)
        transcription += ' ' + rec.recognize_google(audio, language=language)
    return transcription


class Punctuator:
    def __init__(self, MODEL_PATH):
        imp = package.PackageImporter(MODEL_PATH)
        self.model = imp.load_pickle("te_model", "model")

    def apply(self, text, lang='ru'):
        return self.model.enhance_text(text.lower(), lang)        