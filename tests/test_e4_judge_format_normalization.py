import pytest
from phase_e4_1.judge_format_normalization import parse_scores

def test_wrapped_array_and_literal_newlines():
    assert parse_scores('```json\\n[\\n{"label":"A","score":2,"reason":"ok"}\\n]\\n```',['A'])=={'A':2}

def test_escaped_apostrophe_and_string_newline_preserved():
    assert parse_scores(r'''{"scores":[{"label":"A","score":3,"reason":"firm\'s\nreason"}]}''',['A'])=={'A':3}

@pytest.mark.parametrize('text',[
    '{"scores":[{"label":"A","score":true,"reason":"ok"}]}',
    '[{"label":"A","score":5,"reason":"ok"}]',
    '[{"label":"A","score":2,"reason":"ok"},{"label":"A","score":2,"reason":"ok"}]',
    '[{"label":"B","score":2,"reason":"ok"}]',
    '[{"label":"A","score":2,"reason":""}]',
    'prefix [{"label":"A","score":2,"reason":"ok"}]',
    '[{"label":"A","score":2,"reason":"ok"}',
])
def test_fail_closed(text):
    with pytest.raises((ValueError,TypeError)): parse_scores(text,['A'])
