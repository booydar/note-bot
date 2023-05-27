import re
import os
import nltk
import numpy as np
import pandas as pd
from collections import Counter
import torch
import faiss                 
from transformers import AutoModel, AutoTokenizer

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
    if len(letters_only) < 10:
        return False
    
    words_only = re.sub('[^a-zA-Zа-яА-Я ]', '',  thought)
    if len(words_only.split(' ')) < 3:
        return False
    
    return True


def find_tags(note):
    tags = re.findall("\B(\#[a-zA-Z]+(\n|\ ))", note)
    tags = [t.split(s)[0][1:] for (t, s) in tags]
    return tuple(tags)


def parse_note_db(db_path, len_thr):
    path, folders, files = next(os.walk(db_path))

    note_dfs = []
    if len(folders) > 0:
        for f in folders:
            folder_path = os.path.join(path, f)
            folder_df = parse_note_db(folder_path, len_thr)
            note_dfs.append(folder_df)

    db_df = pd.DataFrame()
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
        note_dict = {'name': fn.split('.md')[0], 'path':filepath, 'note':[note], 'cleaned_note': [cleaned_note], 'tags': ', '.join(tags)}
        db_df = pd.concat([db_df, pd.DataFrame(note_dict)])

    note_dfs.append(db_df)
    res_df = pd.concat(note_dfs)
    return res_df


def get_thoughts(note):
    thoughts = [t for thought in re.split('\n|\t', note) for t in nltk.sent_tokenize(thought)]
    cleaned_thoughts = list(map(clean_thought, thoughts))
    filtered_thoughts = list(filter(filter_thought, cleaned_thoughts))
    return filtered_thoughts


class ThoughtManager:
    def __init__(self, db_path='/home/booydar/Documents/Sync/obsidian-db/', 
                        model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                        index_path=None,
                        device='cuda',
                        batch_size=32):
        self.init_model(model_name, device)
        self.db_path, self.index_path, self.batch_size = db_path, index_path, batch_size
        self.init_thoughts()
    
    def init_thoughts(self):
        self.note_db = parse_note_db(self.db_path, len_thr=40)
        self.extract_thoughts()
        
        if self.index_path and os.path.exists(self.index_path):
            self.embeddings = np.load(self.index_path)
        else:
            self.index_path = "../index/thoughts.npy"
            self.embeddings = self.embed(list(self.note_db.thoughts.values), self.batch_size)
            np.save(self.index_path, self.embeddings)
        self.create_index(self.embeddings)

    def get_knn(self, text, k=5, return_distances=False):
        text_embedding = self.embed([text])

        D, I = self.index.search(text_embedding, k)
        nearest = self.note_db.iloc[I[0]].copy()
        nearest['distance'] = D[0]
        return nearest

    def create_index(self, emb_matrix):
        self.index = faiss.IndexFlatL2(self.model.config.hidden_size)
        self.index.add(emb_matrix)
  
    def embed(self, texts, batch_size=32):
        embeddings = []
        for i in range(0, len(texts), batch_size):
            text_batch = texts[i:i+batch_size]
            tokenized = self.tokenizer.batch_encode_plus(text_batch, return_tensors='pt', padding='max_length')
            for t in tokenized:
                tokenized[t] = tokenized[t].to(self.device)
            with torch.no_grad():
                encoded = self.model(**tokenized)
            for bn, states in enumerate(encoded.last_hidden_state):
                emb = states[tokenized['attention_mask'][bn] == 1].mean(dim=0).cpu().detach()
                embeddings.append(emb)

        return torch.vstack(embeddings)

    def init_model(self, model_name, device):
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name)
        self.model.eval()
        self.model.to(device)
        self.device = device

    def extract_thoughts(self):
        thoughts = self.note_db.cleaned_note.apply(get_thoughts)
        self.note_db['thoughts'] = thoughts
        self.note_db = self.note_db.explode('thoughts').dropna(subset=['thoughts'])

    def suggest_tags(self, text):
        drop_tags = {'', 'voice'}
        nearest = self.get_knn(text, 5)
        all_tags = ', '.join(nearest.tags).split(', ')
        all_tags = list(filter(lambda x: x not in drop_tags, all_tags))
        suggested_tags = [t[0] for t in Counter(all_tags).most_common(3)]
        return suggested_tags