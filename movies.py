import numpy as np
import pandas as pd
import requests
import tmdbsimple as tmdb
import gspread
from oauth2client.service_account import ServiceAccountCredentials

tmdb.API_KEY = '<TMDB_API_KEY>'
tmdb.REQUESTS_TIMEOUT = (2, 5)
tmdb.REQUESTS_SESSION = requests.Session()

def get_movies(name, year=None, language=None, type='movie'):
    search = tmdb.Search()
    if type == 'movie':
        response = search.movie(query=name, year=year, language=language)
    elif type == 'tv':
        response = search.tv(query=name, year=year, language=language)
    else:
        raise ValueError(f'Unknown type: {type}')
    return response['results']

def get_info(film, type='movie'):
    if type == 'movie':
        movie = tmdb.Movies(film['id'])
    else:
        movie = tmdb.TV(film['id'])
    info = movie.info()
    cast = movie.credits()
    # return movie

    director = [m['name'] for m in cast['crew'] if m['job'] == 'Director' or m['job'] == 'Executive Producer']
    producer = [m['name'] for m in cast['crew'] if m['job'] == 'Producer']
    writer = [m['name'] for m in cast['crew'] if m['job'] == 'Screenplay' or m['job'] == 'Writer']
    actor = [m['name'] for m in cast['cast'][:5]]

    date = pd.to_datetime(film.get('release_date', film.get('first_air_date')))
    name = film.get('title', film.get('name'))
    original_name = film.get('original_title', film.get('original_name'))

    film_info = {
                'название': name, 
                'год': date.year, 
                'дата выхода': str(date.date()),
                'Name': original_name, 
                'Rating': ','.join(str(round(film['vote_average'], 2)).split('.')), 
                'Type': type,
                'TMDb ID': film['id'],
                'IMDb ID': info.get('imdb_id'),
                'режиссер': ', '.join(director), 
                'сценарист': ', '.join(writer), 
                'актеры': ', '.join(actor),
                'проюсер': ', '.join(producer), 
                'студия': ', '.join([c['name'] for c in info['production_companies']]), 
                'poster_path': info['poster_path']
                }
    return film_info

columns = ['Your Rating', 'название', 'год', 'дата просмотра', 'дата выхода', 'Type', 'Name', 'Rating', 'TMDb ID', 'IMDb ID', 'режиссер', 'сценарист', 'проюсер', 'актеры', 'студия']
class MovieSaver:
    def __init__(self, cred_path="./config/gsheets.json"):
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        self.credentials = ServiceAccountCredentials.from_json_keyfile_name(cred_path, scopes) 

    def save(self, movie, rating, type, sheet=0):
        info = get_info(movie, type)
        info['Your Rating'] = rating
        info['дата просмотра'] = str(pd.Timestamp.today().date())
        film_info = [info[c] for c in columns]
        self.write_to_gsheet(film_info, sheet)

    def write_to_gsheet(self, film_info, sheet_num):
        file = gspread.authorize(self.credentials) 
        sheet = file.open('фильмы').worksheets()[sheet_num]
        write_row_ind = max({len(sheet.col_values(1)), len(sheet.col_values(2))}) + 1
        sheet.update(f"A{write_row_ind}:P{write_row_ind}", [film_info])

