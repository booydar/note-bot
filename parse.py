import re
import pytz
import datetime
TEMPLATE = "{}\n{}\n\n---\n{}\n\n---"
FIRST_WORD_TRIGGERS = {"idea": "ideas", "project": "project", "life": "life", "diary": "diary", "идея": "ideas", "проект": "project", "жизнь": "life", "дневник": "diary"}

def parse_message(message, tags=[], links=[]):
    first_word = message.split(' ')[0].strip().lower()
    hashtags = ["#voice"]
    
    if tags:
        hashtags += ["#" + t for t in set(tags)]

    if first_word in FIRST_WORD_TRIGGERS:
        hashtags.append("#" + FIRST_WORD_TRIGGERS[first_word])
        message = message[message.index(' ') + 1:]  
    
    if len(hashtags) == 1:
        hashtags.append("#random")
    
    dt = str(datetime.datetime.now(pytz.timezone('Europe/Moscow')))
    dt_pfx = re.sub(r"[:]", "-", dt.split(".")[0])
    
    note = TEMPLATE.format(' '.join(hashtags), dt_pfx, message)

    if len(links) > 0:
        note = note[:-3] + '\n'.join([f"[[{l}]]" for l in links]) +  "\n\n---"

    name = message[:50]
    if ' ' in name: 
        name = name[:-name[::-1].index(' ') - 1]
    return note, name
