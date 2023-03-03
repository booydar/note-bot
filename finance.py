import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials

def parse_expense(text):
    if "трат" in text[:15]:
        text = text[text.index('трат') + 4 + 2:]
    amount, category, *comment = text.split(' ') 
    amount = int(re.sub('\.', '', amount))
    comment = ' '.join(comment)
    return amount, category, comment

class SheetWriter:
    def __init__(self, cred_path="config/gsheets.json"):
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        self.credentials = ServiceAccountCredentials.from_json_keyfile_name(cred_path, scopes) 

    def write_to_gsheet(self, amount, category, comment):
        file = gspread.authorize(self.credentials) 
        sheet = file.open('финансы').worksheets()[0]
        write_row_ind = len(sheet.col_values(1)) + 1
        sheet.update(f"B{write_row_ind}:D{write_row_ind}", [[amount, category, comment]])