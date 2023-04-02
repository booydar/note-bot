import re
import os
import nltk
import numpy as np
import pandas as pd
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

def clean_thought(note):
    thought, name = note
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
    
    return thought.strip(), name


def filter_thought(note):
    thought, name = note
    if not thought:
        return False
    
    letters_only = re.sub('[^a-zA-Zа-яА-Я]', '',  thought)
    if len(letters_only) < 10:
        return False
    
    words_only = re.sub('[^a-zA-Zа-яА-Я ]', '',  thought)
    if len(words_only.split(' ')) < 3:
        return False
    
    return True


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
        note_dict = {'name': fn.split('.md')[0], 'path':filepath, 'note':[note], 'cleaned_note': [cleaned_note], }#'tags': ', '.join(tags)}
        db_df = pd.concat([db_df, pd.DataFrame(note_dict)])

    note_dfs.append(db_df)
    res_df = pd.concat(note_dfs)
    return res_df


class ThoughtManager:
    def __init__(self, db_path='/home/booydar/Documents/Sync/obsidian-db/', 
                        # model_name='bert-base-multilingual-cased',
                        model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                        index_path=None,#'../index/thoughts.npy',
                        device='cuda',
                        batch_size=32):
        self.init_model(model_name, device)
        self.db_path, self.index_path, self.batch_size = db_path, index_path, batch_size
        self.init_thoughts()
    
    def init_thoughts(self):
        self.note_db = parse_note_db(self.db_path, len_thr=40)
        self.thoughts = self.extract_thoughts(self.note_db)
        
        if self.index_path and os.path.exists(self.index_path):
            self.embeddings = np.load(self.index_path)
        else:
            self.index_path = "../index/thoughts.npy"
            self.embeddings = self.embed(self.thoughts, self.batch_size)
            np.save(self.index_path, self.embeddings)
        self.create_index(self.embeddings)

    def get_knn(self, text, k=5, return_distances=False):
        text_embedding = self.embed([text])

        D, I = self.index.search(text_embedding, k)
        nearest = [self.thoughts[i] for i in I[0]]
        if return_distances:
            return nearest, D
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

    def extract_thoughts(self, db_df):
        notes = list(zip(db_df.cleaned_note.values, db_df.name.values))
        thoughts = list(map(lambda note: (re.split('\n|\t', note[0]), note[1]), notes))

        thoughts = [(t, name) for (thought, name) in thoughts for t in thought]
        thoughts = list(map(clean_thought, thoughts))
        cleaned_thoughts = list(filter(len, thoughts))
        filtered_thoughts = list(filter(filter_thought, cleaned_thoughts))

        granularized_thoughts = [(nltk.sent_tokenize(t), n) for t, n in filtered_thoughts]
        granularized_thoughts = [(t, name) for (thought, name) in granularized_thoughts for t in thought]

        final_thoughts = list(filter(filter_thought, granularized_thoughts))
        final_thoughts = list(map(clean_thought, final_thoughts))
        return final_thoughts