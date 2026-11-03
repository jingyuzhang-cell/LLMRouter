"""Standalone helpers for cap_eval_bench_v1 (no runtime dependency on other modules)."""
import hashlib
import json
import re

_CN = {'零': 0, '〇': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


def norm(s):
    return re.sub(r'[\s,，。;；:：、"\u201c\u201d\'\'『』()\[\]（）<>《》\-—_·]+', '', str(s))


def cn_year(s):
    return int(''.join(str(_CN[c]) for c in s))


def cn_num(s):
    if s.isdigit():
        return int(s)
    if s == '十':
        return 10
    if '十' in s:
        a, _, b = s.partition('十')
        return (cn_num(a) if a else 1) * 10 + (cn_num(b) if b else 0)
    return _CN[s]


def all_dates(text):
    out = re.findall(r'(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})日?', text)
    iso = [f'{int(a):04d}-{int(b):02d}-{int(c):02d}' for a, b, c in out]
    cn = []
    for m in re.finditer(r'([〇零一二三四五六七八九]{4})年([一二三四五六七八九十]{1,3})月([一二三四五六七八九十]{1,3})日', text):
        try:
            cn.append(f'{cn_year(m.group(1)):04d}-{cn_num(m.group(2)):02d}-{cn_num(m.group(3)):02d}')
        except Exception:
            pass
    seen, uniq = set(), []
    for d in iso + cn:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def sha(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
