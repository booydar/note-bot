from notebot.notes.parsing import clean, filter_thought, find_tags, parse_message


def test_clean_keeps_text_between_wiki_links():
    # the old greedy [.*] ate everything between the first and last bracket
    assert 'middle text' in clean('[[link one]] middle text [[link two]]')
    assert 'link one' not in clean('[[link one]] middle text [[link two]]')


def test_clean_removes_tag_lines_and_markup():
    out = clean('#voice #ideas\nreal content\n---\n**bold**')
    assert 'real content' in out
    assert '#voice' not in out
    assert '*' not in out
    assert '---' not in out


def test_find_tags_cyrillic_digits_eof():
    assert find_tags('#voice some text') == ('voice',)
    assert find_tags('text #идея2 more') == ('идея2',)
    assert find_tags('trailing tag #last') == ('last',)  # old regex missed EOF tags
    assert find_tags('# heading is not a tag') == ()


def test_filter_thought():
    assert not filter_thought('')
    assert not filter_thought('short')
    assert filter_thought('десять слов должно быть в этой мысли чтобы пройти фильтр длины')


def test_parse_message_basic():
    note, name = parse_message('простая заметка о чём-то важном')
    assert '#voice' in note and '#random' in note
    assert 'простая заметка о чём-то важном' in note
    assert name.startswith('простая')


def test_parse_message_first_word_trigger():
    note, _ = parse_message('идея сделать бота лучше')
    assert '#ideas' in note
    assert 'сделать бота лучше' in note
    assert 'идея сделать' not in note  # trigger word stripped from the body


def test_parse_message_single_trigger_word_does_not_crash():
    # the old version did message[message.index(' ') + 1:] -> ValueError
    note, _ = parse_message('идея')
    assert '#ideas' in note


def test_parse_message_tags_and_links():
    note, _ = parse_message('текст', tags=['work'], links=['other note'])
    assert '#work' in note
    assert '[[other note]]' in note


def test_parse_message_no_mutable_default_leak():
    parse_message('раз два три')
    note, _ = parse_message('раз два три')
    assert note.count('#') == 2  # only #voice #random, nothing leaked between calls
