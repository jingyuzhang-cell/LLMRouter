import json
from pathlib import Path
from phase_e4_1.deterministic_extractor import extract_final_answer, score_deterministic

CONTRACT = json.loads(Path('phase_e4_1/E4_1_NUMERIC_UNIT_CONTRACT_FROZEN.json').read_text())
BY_ID = {t['task_id']: t for t in CONTRACT['tasks']}


def _c(tid):
    return BY_ID[tid]


# --- extract_final_answer: representation normalization (gold-independent) ---
def test_percent_strips_percent_suffix():
    assert extract_final_answer('The repurchase was 0.96%.', 'percent') == 0.96
    assert extract_final_answer('0.96', 'percent') == 0.96
    assert extract_final_answer('96%', 'percent') == 96.0  # NOT auto-converted to 0.96


def test_no_blind_factor_100():
    # A bare decimal is taken at face value, never x100 to reach the reference.
    assert extract_final_answer('0.0096', 'percent') == 0.0096


def test_currency_amount_suffix_normalization():
    # canonical scale = 1e6 (USD millions)
    assert extract_final_answer('11.1 million', 'currency_amount', 1e6) == 11.1
    assert extract_final_answer('$11.1M', 'currency_amount', 1e6) == 11.1
    # bare number presumed already in canonical (millions) scale
    assert extract_final_answer('11.1', 'currency_amount', 1e6) == 11.1
    # documented limitation: bare absolute amount without a scale suffix is NOT
    # converted (no gold-peeking by magnitude); candidate should use a suffix.
    assert extract_final_answer('11,100,000', 'currency_amount', 1e6) == 11100000.0


def test_currency_amount_thousands_scale():
    # canonical scale = 1e3 (USD thousands)
    assert extract_final_answer('15712', 'currency_amount', 1e3) == 15712.0
    assert extract_final_answer('$15.712 million', 'currency_amount', 1e3) == 15712.0
    # documented limitation: bare absolute without a suffix is taken at face value.
    assert extract_final_answer('15,712,000', 'currency_amount', 1e3) == 15712000.0


def test_match_currency_thousands_suffixed():
    r = score_deterministic('$15.712 million', _c('c9_d348703a46b76301d955'))
    assert r['score'] == 1.0


def test_per_share_strips_dollar_and_commas():
    assert extract_final_answer('$93.22 per share', 'currency_per_share') == 93.22
    assert extract_final_answer('6.65', 'currency_per_share') == 6.65


def test_ratio_face_value():
    assert extract_final_answer('the ratio is 1.74', 'ratio') == 1.74


def test_answer_cue_narrows_to_last_answer():
    # number before the cue is ignored; the stated answer after 'is' is used
    assert extract_final_answer('In 2021 it was 1.50. The ratio is 1.74.', 'ratio') == 1.74


def test_no_number_returns_none():
    assert extract_final_answer('cannot determine', 'ratio') is None


# --- score_deterministic: full match against frozen contract (synthetic candidates) ---
def test_match_percent_exact():
    r = score_deterministic('0.96%', _c('c9_4c21fc5143ea20b04f9b'))
    assert r['score'] == 1.0 and r['within_tolerance']


def test_reject_percent_wrong_magnitude():
    r = score_deterministic('96%', _c('c9_4c21fc5143ea20b04f9b'))
    assert r['score'] == 0.0  # 96 != 0.96


def test_match_currency_millions_suffixed():
    r = score_deterministic('11.1 million', _c('c9_8399c2ea076354fdaf6d'))
    assert r['score'] == 1.0


def test_bare_absolute_without_suffix_does_not_match():
    # documented limitation: an absolute dollar amount with no scale suffix is
    # taken at face value in canonical units and does NOT match the thousands
    # reference (15712). Candidate should use a scale suffix (e.g. '$15.712 million').
    r = score_deterministic('$15,712,000', _c('c9_d348703a46b76301d955'))
    assert r['score'] == 0.0


def test_reject_wrong_sign():
    r = score_deterministic('-11.1', _c('c9_8399c2ea076354fdaf6d'))
    assert r['score'] == 0.0


def test_reject_unrelated_number_not_closest_gold():
    # candidate rambles a wrong number then states the real one; extractor must use
    # the stated answer (after cue), not scan for the closest number to gold.
    r = score_deterministic('SG&A was 50.0. The ratio is 1.74.', _c('c9_5520e79f10692ace1df3'))
    assert r['score'] == 1.0 and r['extracted'] == 1.74


def test_no_number_scores_zero():
    r = score_deterministic('unable to determine', _c('c9_5520e79f10692ace1df3'))
    assert r['score'] == 0.0 and r['reason'] == 'no_number_extracted'
