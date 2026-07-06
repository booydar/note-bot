"""Sentence-embedding model wrapper (the only torch-touching module besides faiss)."""

from __future__ import annotations

import logging
import os

import torch
from transformers import AutoModel, AutoTokenizer

os.environ["TOKENIZERS_PARALLELISM"] = "false"

logger = logging.getLogger("notebot.embed")


class Embedder:
    def __init__(self, model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                 device='cpu'):
        logger.info("loading embedding model %s", model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name)
        self.model.eval()
        self.model.to(device)
        self.device = device

    @property
    def hidden_size(self):
        return self.model.config.hidden_size

    def embed(self, texts, batch_size=32):
        embeddings = []
        for i in range(0, len(texts), batch_size):
            text_batch = texts[i:i + batch_size]
            tokenized = self.tokenizer.batch_encode_plus(
                text_batch, return_tensors='pt', padding='max_length', truncation=True)
            for t in tokenized:
                tokenized[t] = tokenized[t].to(self.device)
            with torch.no_grad():
                encoded = self.model(**tokenized)
            for bn, states in enumerate(encoded.last_hidden_state):
                emb = states[tokenized['attention_mask'][bn] == 1].mean(dim=0).cpu().detach()
                embeddings.append(emb)

        return embeddings
