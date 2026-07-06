from notebot.integrations.ocr import get_text


def box(y_min, y_max):
    return [[0, y_min], [10, y_min], [10, y_max], [0, y_max]]


def test_same_row_joined_with_space():
    result = [(box(0, 10), 'hello', 0.9), (box(1, 11), 'world', 0.9)]
    assert get_text(result) == 'hello world'


def test_rows_split_by_newline():
    result = [(box(0, 10), 'first', 0.9), (box(20, 30), 'second', 0.9)]
    assert get_text(result) == 'first\nsecond'


def test_last_row_not_dropped():
    # regression: the final line was never flushed
    result = [(box(0, 10), 'only', 0.9)]
    assert get_text(result) == 'only'
