from notebot.integrations.finance import get_most_similar, parse_expense, similarity

CATEGORIES = ['еда', 'транспорт', 'развлечения']


def test_similarity_identical():
    assert similarity('еда', 'еда') == 1


def test_get_most_similar():
    cat, score = get_most_similar('еда', CATEGORIES)
    assert cat == 'еда' and score == 1


def test_parse_expense_plain():
    amount, category, comment = parse_expense('500 еда обед', CATEGORIES)
    assert (amount, category, comment) == (500, 'еда', 'обед')


def test_parse_expense_fuzzy_order():
    # amount and category anywhere in the sentence
    amount, category, comment = parse_expense('потратил на еду 300', CATEGORIES)
    assert amount == 300
    assert category == 'еда'
