TEMPLATE = "{}\n\n---\n{}\n\n---"
FIRST_WORD_TRIGGERS = {"idea": "ideas", "project": "project", "life": "life", "идея": "ideas", "проект": "project", "жизнь": "life"}

def parse_message(message, tags=[]):
    first_word = message.split(' ')[0].strip().lower()
    hashtags = ["#voice"]
    
    if tags:
        hashtags += ["#" + t for t in set(tags)]

    if first_word in FIRST_WORD_TRIGGERS:
        hashtags.append("#" + FIRST_WORD_TRIGGERS[first_word])
        message = message[message.index(' ') + 1:]  
    
    if len(hashtags) == 1:
        hashtags.append("#random")
    
    note = TEMPLATE.format(' '.join(hashtags), message)
    return note
