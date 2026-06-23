import re
import os
import contextlib
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials

def similarity(query, reference):
    common_letters = set(query).intersection(set(reference))
    precision = len(common_letters) / len(set(query))
    recall = len(common_letters) / len(set(reference))
    try:
        f1 = 2 * precision * recall / (precision + recall)
    except(ZeroDivisionError):
        f1 = 0
    return f1

def get_most_similar(query, categories):
    similarities = list(map(lambda cat: similarity(query, cat), categories))
    return categories[np.argmax(similarities)], max(similarities)


class SheetWriter:
    def __init__(self, cred_path, proxy=None):
        self.proxy = proxy
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        self.credentials = ServiceAccountCredentials.from_json_keyfile_name(cred_path, scopes) 
        self.categories = self.get_categories()

    @contextlib.contextmanager
    def _proxy_ctx(self):
        if not self.proxy:
            yield
            return
        saved = {k: os.environ.get(k) for k in ('HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy')}
        for k in saved:
            os.environ[k] = self.proxy
        try:
            yield
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def write_to_gsheet(self, amount, category, comment):
        with self._proxy_ctx():
            file = gspread.authorize(self.credentials)
            sheet = file.open('финансы').worksheets()[0]
            write_row_ind = len(sheet.col_values(1)) + 1
            sheet.update(f"B{write_row_ind}:D{write_row_ind}", [[amount, category, comment]])

    def parse_expense(self, text):
        if "трат" in text[:15].lower():
            text = text[text.index('трат') + 4 + 2:]
        elif "расход" in text[:15].lower():
            text = text[text.index('расход') + 6 + 2:]

        try:
            amount, category, *comment = text.split(' ')
            amount = int(re.sub('\.', '', amount))
            comment = ' '.join(comment)

            if category not in self.categories:
                category, similarity = get_most_similar(category, self.categories)
                if similarity < 0.85:
                    raise ValueError
        except ValueError:
            words = text.strip().split(' ')

            amount_candidates = [re.sub('[^0-9]', '', w) for w in words]
            amount_ind = np.argmax(list(map(len, amount_candidates)))
            amount = int(amount_candidates[amount_ind])

            similarity_scores = [get_most_similar(w, self.categories) for w in words]
            category_ind = np.argmax(list(map(lambda x: x[1], similarity_scores)))
            category = similarity_scores[category_ind][0]

            comment = ' '.join([w for i, w in enumerate(words) if i not in {amount_ind, category_ind}])

        return amount, category, comment

    def get_categories(self):
        with self._proxy_ctx():
            file = gspread.authorize(self.credentials)
            sheet = file.open('финансы').worksheets()[2]
            return sheet.col_values(1)