"""Local LLM (ollama) helpers. Currently unused by the bots; kept for
extraction experiments (see notebooks/thoughts_refactor.ipynb)."""

from __future__ import annotations

import logging

logger = logging.getLogger("notebot.llm")


def llm(query, model='llama3'):
    import ollama
    response = ollama.chat(model=model, messages=[{'role': 'user', 'content': query}])
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
        logger.error("ollama error: %s", e)
        return None
