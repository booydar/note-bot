"""NoteManager: the vault index — parse, embed, FAISS search.

Changes vs the original thoughts.py:
  - logging instead of prints;
  - an internal lock so a reindex can't race a search (and a `schedule_reindex`
    helper so frontends reindex in the background instead of blocking a save);
  - atomic cache writes + an inter-process file lock (both frontends share
    note_db.npy);
  - `get_nearest` default field fixed ('sentences'; 'sentence' was a KeyError).
"""

from __future__ import annotations

import logging
import os
import threading
from collections import Counter

import faiss
import torch
from tqdm import tqdm

from notebot import storage
from notebot.notes import parsing
from notebot.notes.embed import Embedder

logger = logging.getLogger("notebot.notes")

SEARCH_FIELDS = ['sentences', 'paragraphs']


class NoteManager:
    def __init__(self, db_path,
                 model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                 device='cpu',
                 save_path='../saved',
                 batch_size=32,
                 from_scratch=False):
        os.makedirs(save_path, exist_ok=True)

        self.db_path, self.save_path, self.batch_size = db_path, save_path, batch_size
        self._lock = threading.Lock()          # reindex vs search, in-process
        self._reindexing = threading.Event()   # at most one background reindex
        self.embedder = Embedder(model_name, device)
        self.load_db(from_scratch)
        self.parse_notes()

    @property
    def cache_file(self):
        return os.path.join(self.save_path, 'note_db.npy')

    # ------------------------------------------------------------------ search
    def get_nearest(self, text, k=5, by_field='sentences'):
        with self._lock:
            index = self.index[by_field]
            text_emb = self.embedder.embed([parsing.clean(text)])
            D, I = index.search(torch.stack(text_emb), k)

            nearest = self.get_notes_by_field(by_field, I[0])
        for i, n in enumerate(nearest):
            n['distance'] = D[0][i]
        nearest = sorted(nearest, key=lambda n: n['distance'])
        return nearest

    def get_nearest_all_fields(self, text, k=5):
        note = {}
        # much more lenient filters for query text than for vault notes
        parsing.add_fields(note, text, min_letters=5, min_words=2)
        nearest = []
        for field in note:
            note_f = note[field]
            if not note_f or field not in self.index:
                continue
            if isinstance(note_f, str):
                note_f = [note_f]
            for chunk in note_f:
                nearest_f = self.get_nearest(chunk, k, field)
                for n in nearest_f:
                    n['search_field'] = field
                nearest += nearest_f
        logger.debug("nearest search: %d candidates over %d fields", len(nearest), len(note))
        return sorted(nearest, key=lambda n: n['distance'])

    def suggest_tags(self, text):
        drop_tags = {''}
        nearest = self.get_nearest_all_fields(text, 10)

        all_tags = [t for n in nearest for t in n['tags']]
        all_tags = list(filter(lambda x: x not in drop_tags, all_tags))
        suggested_tags = [t[0] for t in Counter(all_tags).most_common(4)]
        logger.debug("suggest_tags -> %s", suggested_tags)
        return suggested_tags

    # ---------------------------------------------------------------- indexing
    def parse_notes(self):
        """Full reparse + (incremental) re-embed + index rebuild. Blocking."""
        with self._lock:
            logger.info("parsing notes ...")
            loaded = parsing.parse_folder(self.db_path, len_thr=40)
            self.add_notes(loaded)
            self.extract_thoughts()
            self.build_index()
            self.embed_database()
            self.save()
            logger.info("index ready: %d notes", len(self.db))

    def schedule_reindex(self):
        """Reindex in a background thread so saves don't block the frontend."""
        if self._reindexing.is_set():
            return

        def run():
            self._reindexing.set()
            try:
                self.parse_notes()
            except Exception:
                logger.exception("background reindex failed")
            finally:
                self._reindexing.clear()

        threading.Thread(target=run, daemon=True).start()

    def add_notes(self, notes):
        # dictionaries for fast lookups by 'path'
        db_dict = {n['path']: n for n in self.db}
        loaded_db_dict = {n['path']: n for n in notes}

        new_notes = {path: n for path, n in loaded_db_dict.items() if path not in db_dict}
        changed_notes = {path: n for path, n in loaded_db_dict.items()
                         if path in db_dict and db_dict[path]['note'] != n['note']}
        deleted_note_paths = {path for path in db_dict if path not in loaded_db_dict}

        for path in changed_notes:
            del db_dict[path]

        for path in deleted_note_paths:
            del db_dict[path]

        self.db = list(db_dict.values()) + list(new_notes.values()) + list(changed_notes.values())

    def extract_thoughts(self):
        for n in tqdm(self.db, desc="Extracting fields"):
            parsing.add_fields(n, n['cleaned_note'])

    def build_index(self):
        self.f2i = dict()
        for field in SEARCH_FIELDS:
            note_inds = []
            field_inds = []
            for note_ind, note in enumerate(self.db):
                nf = note[field]
                if isinstance(nf, str):
                    note_inds.append(note_ind)
                    field_inds.append(0)
                elif isinstance(nf, list):
                    note_inds += [note_ind] * len(nf)
                    field_inds += list(range(len(nf)))
            element_inds = range(len(note_inds))
            self.f2i[field] = dict(zip(element_inds, zip(note_inds, field_inds)))

    def embed_database(self):
        self.index = dict()
        for field in SEARCH_FIELDS:
            embeddings = []
            emb_field = f"{field}_emb"
            for note in tqdm(self.db, desc=f"Embedding {field}"):
                if emb_field in note:
                    emb = note[emb_field]
                else:
                    nf = note[field]
                    if isinstance(nf, str):
                        emb = self.embedder.embed([nf])
                    else:
                        emb = self.embedder.embed(nf)
                    note[emb_field] = emb
                embeddings += emb
            if not embeddings:
                logger.warning("field %r has no embeddings", field)
                continue

            index = faiss.IndexFlatL2(self.embedder.hidden_size)
            index.add(torch.vstack(embeddings))
            self.index[field] = index
        logger.debug("indexed fields: %s", list(self.index.keys()))

    def get_notes_by_field(self, by_field, inds):
        f2i = self.f2i[by_field]
        out = []
        for i in inds:
            o = dict(**self.db[f2i[i][0]])
            o['nearest_field'] = f2i[i][1]
            out.append(o)
        return out

    # ----------------------------------------------------------------- storage
    def load_db(self, from_scratch=False):
        if not os.path.exists(self.cache_file) or from_scratch:
            logger.info("no cache at %s, starting empty", self.cache_file)
            self.db = []
        else:
            with storage.file_lock(self.cache_file + '.lock'):
                self.db = list(storage.load_npy(self.cache_file))
            logger.info("loaded cache: %d notes", len(self.db))

    def save(self):
        os.makedirs(self.save_path, exist_ok=True)
        with storage.file_lock(self.cache_file + '.lock'):
            storage.save_npy(self.cache_file, self.db)
