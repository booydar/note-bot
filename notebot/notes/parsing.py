"""Pure text munging: vault parsing, note cleaning, and message->note formatting.

No torch/faiss imports here — everything is unit-testable in milliseconds.
"""

from __future__ import annotations

import datetime
import os
import re

import pytz

# ---------------------------------------------------------------------------
# note cleaning (before embedding)
# ---------------------------------------------------------------------------

def clean(note):
    # remove wiki links [[...]] and other bracketed spans, keeping text between them
    note = re.sub(r'\[\[[^\]]*\]\]', '', note)
    note = re.sub(r'\[[^\]]*\]', '', note)
    # remove tags and headers
    note = re.sub(r'\#.*\n', '', note)
    # remove lines
    note = re.sub('---', ' ', note)
    # remove **
    note = re.sub(r'\*', '', note)

    return note


def clean_thought(thought):
    thought = re.sub(r'\(http\S+', '<LINK>', thought)
    thought = re.sub(r'http\S+', '<LINK>', thought)

    if thought[:2] == '- ':
        thought = thought[2:]

    if '<LINK>' in thought:
        linkless = re.sub('<LINK>', '', thought)
        linkless = re.sub('[^a-zA-Zа-яА-Я ]', '', linkless)
        linkless = linkless.strip()
        if len(linkless.split(' ')) < 2:
            return ''

    return thought.strip()


def filter_thought(thought, min_letters=30, min_words=10):
    if not thought:
        return False

    thought = str(thought)
    letters_only = re.sub('[^a-zA-Zа-яА-Я]', '', thought)
    if len(letters_only) < min_letters:
        return False

    words_only = re.sub('[^a-zA-Zа-яА-Я ]', '', thought)
    if len(words_only.split(' ')) < min_words:
        return False

    return True


def find_tags(note):
    """#tags anywhere in the note (latin/cyrillic/digits/underscore, EOF included)."""
    return tuple(re.findall(r"\B#([a-zA-Zа-яА-ЯёЁ0-9_]+)", note))


# ---------------------------------------------------------------------------
# vault -> note dicts
# ---------------------------------------------------------------------------

def parse_folder(db_path, len_thr=40):
    path, folders, files = next(os.walk(db_path))

    subfolder_dbs = []
    if len(folders) > 0:
        for f in folders:
            folder_path = os.path.join(path, f)
            folder_db = parse_folder(folder_path, len_thr)
            subfolder_dbs += folder_db

    db = []
    for fn in files:
        if not fn.endswith('.md'):
            continue

        filepath = os.path.join(path, fn)
        with open(filepath, 'r') as f:
            note = f.read()

        if len(note) < len_thr:
            continue
        cleaned_note = clean(note)
        tags = find_tags(note)
        note_dict = {'name': fn[:-len('.md')], 'path': filepath,
                     'note': note, 'cleaned_note': cleaned_note,
                     'tags': tags}
        db.append(note_dict)

    db = db + subfolder_dbs
    return db


def get_sentences(note, min_letters=30, min_words=10):
    import nltk  # heavy-ish; only needed when actually splitting
    sentences = [t for thought in re.split('\n|\t', note) for t in nltk.sent_tokenize(thought)]
    cleaned = list(map(clean_thought, sentences))
    filtered = list(filter(lambda x: filter_thought(x, min_letters, min_words), cleaned))
    return filtered


def get_paragraphs(note, min_letters=30, min_words=10):
    paragraphs = [p for p in re.split('\n\n', note)]
    cleaned = list(map(clean_thought, paragraphs))
    filtered = list(filter(lambda x: filter_thought(x, min_letters, min_words), cleaned))
    return filtered


def add_fields(note, text, min_letters=30, min_words=10):
    if not note.get('sentences'):
        note['sentences'] = get_sentences(text, min_letters, min_words)
    if not note.get('paragraphs'):
        note['paragraphs'] = get_paragraphs(text, min_letters, min_words)


# ---------------------------------------------------------------------------
# message -> note text + name
# ---------------------------------------------------------------------------

TEMPLATE = "{}\n{}\n\n---\n{}\n\n---"
FIRST_WORD_TRIGGERS = {"idea": "ideas", "project": "project", "life": "life", "diary": "diary",
                       "идея": "ideas", "проект": "project", "жизнь": "life", "дневник": "diary"}


def parse_message(message, tags=None, links=None):
    tags = tags or []
    links = links or []
    first_word = message.split(' ')[0].strip().lower()
    hashtags = ["#voice"]

    if tags:
        hashtags += ["#" + t for t in set(tags)]

    if first_word in FIRST_WORD_TRIGGERS:
        hashtags.append("#" + FIRST_WORD_TRIGGERS[first_word])
        message = message[len(first_word):].lstrip()

    if len(hashtags) == 1:
        hashtags.append("#random")

    dt = str(datetime.datetime.now(pytz.timezone('Europe/Moscow')))
    dt_pfx = re.sub(r"[:]", "-", dt.split(".")[0])

    note = TEMPLATE.format(' '.join(hashtags), dt_pfx, message)

    if len(links) > 0:
        note = note[:-3] + '\n'.join([f"[[{l}]]" for l in links]) + "\n\n---"

    name = message[:50]
    if ' ' in name:
        name = name[:-name[::-1].index(' ') - 1]
    name = re.sub(r"[^a-zA-Zа-яА-Я \-]", '', name).strip()
    return note, name
