"""TMDb search + saving watched films / watchlist to the 'фильмы' sheet."""

from __future__ import annotations

import re

import pandas as pd
import requests
import tmdbsimple as tmdb

from notebot import storage

SPREADSHEET = 'фильмы'

TEMPLATE = '''{date}\n#movies\n\n---\nRating: {rating}\n\n{text}\n'''
COLUMNS = ['Your Rating', 'название', 'год', 'дата просмотра', 'дата выхода', 'Type', 'Name',
           'Rating', 'TMDb ID', 'IMDb ID', 'режиссер', 'сценарист', 'проюсер', 'актеры',
           'студия', 'комментарий']


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
        'poster_path': info['poster_path'],
    }
    return film_info


class MovieSaver:
    def __init__(self, note_db_path, gsheets, tmdb_api_key, proxy=None, user_id=None):
        tmdb.API_KEY = tmdb_api_key
        tmdb.REQUESTS_TIMEOUT = (30, 30)
        tmdb.REQUESTS_SESSION = requests.Session()
        if proxy:
            tmdb.REQUESTS_SESSION.proxies.update({'http': proxy, 'https': proxy})
        self.gs = gsheets
        self.note_db_path = note_db_path
        self.user_id = user_id

    def save(self, movie, rating, type, comment=None, sheet=0):
        info = get_info(movie, type)
        info['Your Rating'] = rating
        info['дата просмотра'] = str(pd.Timestamp.today().date())
        if comment is None:
            comment = '-'
        info['комментарий'] = comment
        film_info = [info[c] for c in COLUMNS]
        self.write_to_gsheet(film_info, sheet)
        if sheet == 0 and comment != '-':
            self.save_note(info)
        return info

    def save_note(self, info):
        date = re.sub('-', '.', info['дата просмотра'])
        note_name = f"{re.sub('[^a-zA-Zа-яА-Я1-9ёЁ -]', '', info['название'])} - {info['год']}"
        note_text = TEMPLATE.format(date=date, rating=info['Your Rating'], text=info['комментарий'])
        storage.write_note(self.note_db_path, "art/movies", note_name, note_text, self.user_id)

    def write_to_gsheet(self, film_info, sheet_num):
        with self.gs.ctx() as client:
            sheet = client.open(SPREADSHEET).worksheets()[sheet_num]
            write_row_ind = max({len(sheet.col_values(1)), len(sheet.col_values(2))}) + 1
            sheet.update(f"A{write_row_ind}:P{write_row_ind}", [film_info])

    def download_poster(self, poster_path, out_path='tmp.jpg'):
        if not poster_path:
            return
        url = f"https://image.tmdb.org/t/p/w600_and_h900_bestv2{poster_path}"
        response = tmdb.REQUESTS_SESSION.get(url, timeout=30)
        with open(out_path, 'wb') as f:
            f.write(response.content)
