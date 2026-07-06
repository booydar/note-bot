"""Expense tracking -> the 'финансы' Google sheet."""

from __future__ import annotations

import re

import numpy as np

SPREADSHEET = 'финансы'


def similarity(query, reference):
    common_letters = set(query).intersection(set(reference))
    precision = len(common_letters) / len(set(query))
    recall = len(common_letters) / len(set(reference))
    try:
        f1 = 2 * precision * recall / (precision + recall)
    except ZeroDivisionError:
        f1 = 0
    return f1


def get_most_similar(query, categories):
    similarities = list(map(lambda cat: similarity(query, cat), categories))
    return categories[np.argmax(similarities)], max(similarities)


def parse_expense(text, categories):
    if "трат" in text[:15].lower():
        text = text[text.index('трат') + 4 + 2:]
    elif "расход" in text[:15].lower():
        text = text[text.index('расход') + 6 + 2:]

    try:
        amount, category, *comment = text.split(' ')
        amount = int(re.sub(r'\.', '', amount))
        comment = ' '.join(comment)

        if category not in categories:
            category, sim = get_most_similar(category, categories)
            if sim < 0.85:
                raise ValueError
    except ValueError:
        words = text.strip().split(' ')

        amount_candidates = [re.sub('[^0-9]', '', w) for w in words]
        amount_ind = np.argmax(list(map(len, amount_candidates)))
        amount = int(amount_candidates[amount_ind])

        similarity_scores = [get_most_similar(w, categories) for w in words]
        category_ind = np.argmax(list(map(lambda x: x[1], similarity_scores)))
        category = similarity_scores[category_ind][0]

        comment = ' '.join([w for i, w in enumerate(words) if i not in {amount_ind, category_ind}])

    return amount, category, comment


class SheetWriter:
    def __init__(self, gsheets):
        self.gs = gsheets
        self.categories = self.get_categories()

    def write_expense(self, amount, category, comment):
        with self.gs.ctx() as client:
            sheet = client.open(SPREADSHEET).worksheets()[0]
            write_row_ind = len(sheet.col_values(1)) + 1
            sheet.update(f"B{write_row_ind}:D{write_row_ind}", [[amount, category, comment]])

    def get_categories(self):
        with self.gs.ctx() as client:
            sheet = client.open(SPREADSHEET).worksheets()[2]
            return sheet.col_values(1)
