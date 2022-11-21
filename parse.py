TEMPLATE = "{}\n\n---\n{}\n\n---"
FIRST_WORD_TRIGGERS = {"idea": "ideas", "project": "project", "life": "life", "идея": "ideas", "проект": "project", "жизнь": "life"}

def parse_message(message):
    first_word = message.split(' ')[0].strip().lower()
    hashtags = ["#voice"]
    if first_word in FIRST_WORD_TRIGGERS:
        hashtags.append("#" + FIRST_WORD_TRIGGERS[first_word])
        message = message[message.index(' ') + 1:]
    else:
        hashtags.append("#random")
    
    note = TEMPLATE.format(' '.join(hashtags), message)
    return note
