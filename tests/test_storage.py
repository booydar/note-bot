import os

from notebot.storage import EventLog, load_npy, save_npy, write_note


def test_write_note_creates_dirs_and_file(tmp_path):
    path = write_note(str(tmp_path), 'voice/talk', 'my note', 'hello')
    assert os.path.exists(path)
    assert open(path).read() == 'hello'
    assert path.endswith('voice/talk/my note.md')


def test_write_note_never_overwrites(tmp_path):
    p1 = write_note(str(tmp_path), 'voice', 'same', 'first')
    p2 = write_note(str(tmp_path), 'voice', 'same', 'second')
    assert p1 != p2
    assert open(p1).read() == 'first'
    assert open(p2).read() == 'second'


def test_write_note_empty_name_fallback(tmp_path):
    path = write_note(str(tmp_path), 'voice', '   ', 'text')
    assert path.endswith('note.md')


def test_npy_roundtrip_atomic(tmp_path):
    db = [{'name': 'a', 'tags': ('x',)}, {'name': 'b', 'tags': ()}]
    path = str(tmp_path / 'note_db.npy')
    save_npy(path, db)
    loaded = list(load_npy(path))
    assert loaded == db
    assert not os.path.exists(path + '.tmp.npy')  # temp file cleaned up


def test_event_log(tmp_path):
    log = EventLog(str(tmp_path / 'cache' / 'events.sqlite'))
    log.record('telegram', 'note', raw_text='привет', artifact='/x/y.md', tags=['a'])
    log.record('nctalk', 'expense', amount=500, category='еда')
    rows = log.recent(10)
    assert len(rows) == 2
    assert rows[0][1] == 'nctalk' and rows[0][2] == 'expense'
    assert rows[1][3] == 'привет'
