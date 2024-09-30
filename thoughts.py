import re
import os
import nltk
import numpy as np
from threading import Timer
from collections import Counter
import torch
import faiss                 
from transformers import AutoModel, AutoTokenizer
import ollama
os.environ["TOKENIZERS_PARALLELISM"] = "false"

def clean(note):
    # remove zero-links
    note = re.sub(r'\[.*\]', '', note)
    # remove tags and headers
    note = re.sub(r'\#.*\n', '', note)
    # remove lines
    note = re.sub('---', ' ', note)
    # remove **
    note = re.sub('\*', '', note)
    
    return note

def clean_thought(thought):
    thought = re.sub(r'\(http\S+', '<LINK>', thought)
    thought = re.sub(r'http\S+', '<LINK>', thought)

    if thought[:2] == '- ':
        thought = thought[2:]

    if '<LINK>' in thought:
        linkless = re.sub('<LINK>', '', thought)
        linkless = re.sub('[^a-zA-Zа-яА-Я ]', '',  linkless)
        linkless = linkless.strip()
        if len(linkless.split(' ')) < 2:
            return ''
    
    return thought.strip()


def filter_thought(thought):
    if not thought:
        return False
    
    thought = str(thought)
    letters_only = re.sub('[^a-zA-Zа-яА-Я]', '',  thought)
    if len(letters_only) < 30:
        return False
    
    words_only = re.sub('[^a-zA-Zа-яА-Я ]', '',  thought)
    if len(words_only.split(' ')) < 10:
        return False
    
    return True


def find_tags(note):
    tags = re.findall("\B(\#[a-zA-Z]+(\n|\ ))", note)
    tags = [t.split(s)[0][1:] for (t, s) in tags]
    return tuple(tags)


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
        if '.md' not in fn:
            continue

        filepath = os.path.join(path, fn)
        with open(filepath, 'r') as f:
            note = f.read()

        if len(note) < len_thr:
            continue
        cleaned_note = clean(note)
        tags = find_tags(note)
        # sentences = get_sentences(cleaned_note)
        # paragraphs = get_paragraphs(cleaned_note)
        # llm_thoughts = llm_get_thoughts(cleaned_note)
        note_dict = {'name': fn.split('.md')[0], 'path':filepath, 
                     'note':note, 'cleaned_note': cleaned_note, 
                    #  'llm_thoughts': llm_thoughts, 
                    #  'sentences': sentences, 
                    # "paragraphs": paragraphs, 
                     'tags': tags}
        db.append(note_dict)

    db = db + subfolder_dbs
    return db


def get_sentences(note):
    sentences = [t for thought in re.split('\n|\t', note) for t in nltk.sent_tokenize(thought)]
    cleaned = list(map(clean_thought, sentences))
    filtered = list(filter(filter_thought, cleaned))
    return filtered

def get_paragraphs(note):
    paragraphs = [p for p in re.split('\n\n', note)]
    cleaned = list(map(clean_thought, paragraphs))
    filtered = list(filter(filter_thought, cleaned))
    return filtered


def llm(query):
    response = ollama.chat(model='llama3',
                            messages=[{'role': 'user', 
                                        'content': query}])
    return response['message']['content']

def llm_get_thoughts(text):
    try:
        prompt = '''Summarize the following text in 2-3 sentences, formulate it very concisely. Text: {} Output only the concise summary, 2-3 sentences.'''
        query = prompt.format(text[:20_000])
        ans = llm(query)
        if '\n' in ans: 
            ans = ans.split('\n')[-1]
        thoughts = ans.split('.')
        thoughts = list(filter(len, thoughts))
        thoughts = [t.strip() for t in thoughts]
        return thoughts
    except Exception as e:
        print(f"Got error with ollama: {e}")
        return

def add_fields(note, text):
    if not note.get('llm_thoughts'):
        note['llm_thoughts'] = llm_get_thoughts(text)
    if not note.get('sentences'):
        note['sentences'] = get_sentences(text)
    if not note.get('paragraphs'):
        note['paragraphs'] = get_paragraphs(text)


# SEARCH_FIELDS = ['cleaned_note', 'sentences', 'paragraphs', 'llm_thoughts']
SEARCH_FIELDS = ['sentences', 'paragraphs', 'llm_thoughts']
class NoteManager:
    def __init__(self, db_path, 
                        model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                        device='cpu',
                        save_path='../saved',
                        batch_size=32,
                        from_scratch=False):
        os.makedirs(save_path, exist_ok=True)
        
        self.db_path, self.save_path, self.batch_size = db_path, save_path, batch_size
        self.init_model(model_name, device)
        self.load_db(from_scratch)
        self.parse_notes()
        # self.start_timer()
    
    def get_nearest(self, text, k=5, by_field='sentence'):
        index = self.index[by_field]

        text_emb = self.embed([clean(text)])
        D, I = index.search(torch.stack(text_emb), k)

        nearest = self.get_notes_by_field(by_field, I[0])
        for i, n in enumerate(nearest):
            n['distance'] = D[0][i]
        nearest = sorted(nearest, key=lambda n: n['distance'])
        return nearest

    def get_nearest_all_fields(self, text, k=5):
        note = {}
        add_fields(note, text)
        nearest = []
        for field in note:
            note_f = note[field]
            if not note_f:
                continue
            if type(note_f) == str:
                note_f = [note_f]
            for text in note_f:
                nearest_f = self.get_nearest(text, k, field) 
                for n in nearest_f:
                    n['search_field'] = field
                nearest += nearest_f
        return sorted(nearest, key=lambda n: n['distance'])
    
    def suggest_tags(self, text):
        drop_tags = {''}
        nearest = self.get_nearest_all_fields(text, 10)
        
        all_tags = [t for n in nearest for t in n['tags']]
        all_tags = list(filter(lambda x: x not in drop_tags, all_tags))
        suggested_tags = [t[0] for t in Counter(all_tags).most_common(4)]
        return suggested_tags
    
    def parse_notes(self):
        print("### Parsing notes ###")
        loaded = parse_folder(self.db_path, len_thr=40)

        self.add_notes(loaded)
        self.extract_thoughts()
        self.build_index()
        self.embed_database()
        self.save()

    def add_notes(self, notes):
        print("### Adding notes ###")
        # Create dictionaries for fast lookups by 'path'
        db_dict = {n['path']: n for n in self.db}
        loaded_db_dict = {n['path']: n for n in notes}

        new_notes = {path: n for path, n in loaded_db_dict.items() if path not in db_dict}
        changed_notes = {path: n for path, n in loaded_db_dict.items() if path in db_dict and db_dict[path]['note'] != n['note']}
        deleted_note_paths = {path for path in db_dict if path not in loaded_db_dict}

        for path in changed_notes:
            del db_dict[path]

        for path in deleted_note_paths:
            del db_dict[path]

        # Update database with new notes
        self.db = list(db_dict.values()) + list(new_notes.values()) + list(changed_notes.values())
    
    def extract_thoughts(self):
        print("### Extracting thoughts ###")
        for n in self.db:
            cn = n['cleaned_note']
            add_fields(n, cn)
    
    def build_index(self):
        print("### Buliding index ###")
        self.f2i = dict()
        for field in SEARCH_FIELDS:
            note_inds = []
            field_inds = []
            for note_ind, note in enumerate(self.db):
                nf = note[field]
                if type(nf) == str:
                    note_inds.append(note_ind)
                    field_inds.append(0)
                elif type(nf) == list:
                    note_inds += [note_ind] * len(nf)
                    field_inds += list(range(len(nf)))
            element_inds = range(len(note_inds))
            self.f2i[field] = dict(zip(element_inds, zip(note_inds, field_inds)))
    
    def embed_database(self):
        print("### Embedding DB ###")
        self.index = dict()
        for field in SEARCH_FIELDS:
            embeddings = []
            emb_field = f"{field}_emb"
            for note in self.db:
                if emb_field in note:
                    emb = note[emb_field]
                else:
                    nf = note[field]
                    if type(nf) == str:
                        emb = self.embed([nf])
                    elif type(nf) == list:
                        emb = self.embed(nf)

                    note[emb_field] = emb
                embeddings += emb 
            if not embeddings:
                continue
            
            index = faiss.IndexFlatL2(self.model.config.hidden_size)
            index.add(torch.vstack(embeddings))
            self.index[field] = index
    
    def get_notes_by_field(self, by_field, inds):
        f2i = self.f2i[by_field]
        out = []
        for i in inds:
            o = dict(**self.db[f2i[i][0]])
            o['nearest_field'] = f2i[i][1]
            out.append(o)
        return out

    def create_index(self, emb_matrix):
        self.index = faiss.IndexFlatL2(self.model.config.hidden_size)
        self.index.add(emb_matrix)
  
    def embed(self, texts, batch_size=32):
        embeddings = []
        for i in range(0, len(texts), batch_size):
            text_batch = texts[i:i+batch_size]
            tokenized = self.tokenizer.batch_encode_plus(text_batch, return_tensors='pt', padding='max_length', truncation=True)
            for t in tokenized:
                tokenized[t] = tokenized[t].to(self.device)
            with torch.no_grad():
                encoded = self.model(**tokenized)
            for bn, states in enumerate(encoded.last_hidden_state):
                emb = states[tokenized['attention_mask'][bn] == 1].mean(dim=0).cpu().detach()
                embeddings.append(emb)

        return embeddings

    def init_model(self, model_name, device):
        print("### Loading model ###")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name)
        self.model.eval()
        self.model.to(device)
        self.device = device

    def load_db(self, from_scratch=False):
        db_path = os.path.join(self.save_path, 'note_db.npy')
        if not os.path.exists(db_path) or from_scratch:
            self.db = []
        else:
            self.db = np.load(db_path, allow_pickle=True)
    
    def save(self):
        os.makedirs(self.save_path, exist_ok=True)
        db_path = os.path.join(self.save_path, 'note_db.npy')
        np.save(db_path, self.db)
    
    def start_timer(self):
        class RepeatTimer(Timer):
            def run(self):
                while not self.finished.wait(self.interval):
                    self.function(*self.args, **self.kwargs)

        self.timer = RepeatTimer(1800, self.parse_notes)
        self.timer.start()