#!/usr/bin/env python3
"""Independent penalty-case search (operator authorization 2026-11-06): public documents only, no model calls.

  --prefilter   stages 1-4
      1 pool: cninfo announcements titled as receiving an administrative penalty decision, 2019-2025, SZ+SH
      2 pairing: the same company announced receiving an advance notice (事先告知书)
      3 batch pre-check: any stock code or short name found locally (working tree or git HEAD) -> rejected
      4 structure, from the downloaded document text: >= 8 penalized parties, >= 2 amount levels,
        total re-computable, an advance notice before the decision that names the same parties
  --audit N     stage 5 on the N best-ranked survivors: per-term check of code, names, every party and
                every case number in the working tree, git HEAD and full git history

Stages 1-2 are cached in POOL_CACHE.json. Criteria are never relaxed: every rejection is recorded with
its reason and the matching evidence.
"""
import argparse
import hashlib
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path('/root/research_outputs/static_pi/stage_d/independent_case_search')
RAW = OUT / 'raw'
CACHE = OUT / 'POOL_CACHE.json'
QUERY = 'http://www.cninfo.com.cn/new/hisAnnouncement/query'
STATIC = 'http://static.cninfo.com.cn/'
UA = {'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
      'Referer': 'http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search'}
LOCAL_ROOTS = ['/root/research_outputs', '/root/capital_opinion_pilot', '/root/r3_own_pool', '/root/cap_eval_bench_v1',
               '/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE', '/root/q_foundation', '/root/phase_c9_0', '/root/phase_e5_unified',
               '/root/.worktrees']
EXCLUDE = ['--exclude-dir=.git', '--exclude-dir=independent_case_search']
CRITERIA = dict(min_parties=8, min_amount_levels=2, both_documents=True, total_recomputable=True,
                notice_same_case_min_party_overlap=0.5,
                zero_local_hits=['stock code', 'short name', 'full name', 'party names', 'case numbers'])
# Pool construction only: drop announcements that are not about the listed company's own case. Structural
# criteria are applied later from the document text, never from the title.
SKIP_TITLE = ('子公司', '非本公司', '更正', '补充', '撤销', '进展', '复议', '诉讼', '期货', '证券公司')
PENALTY_RE = re.compile(r'对([^。；;：:]{1,300}?)(?:给予警告[，,]?)?并?(?:分别)?处以([\d,，.]+)万元(?:的)?罚款')
NAME_NOISE = re.compile(r'^(?:[一二三四五六七八九十]+、)|分别$|责令改正|给予警告|并$')
CASE_NO_RE = re.compile(r'[〔【\[]20\d\d[〕】\]]\d+号')


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S%z')


def post(params, tries=3):
    data = urllib.parse.urlencode(params).encode()
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(QUERY, data=data, headers=UA), timeout=30).read().decode())
        except Exception:
            time.sleep(2 + 2 * i)
    raise RuntimeError(f'query failed: {params.get("searchkey")} {params.get("stock")}')


def search(key, column, se_date, stock='', max_pages=60):
    out, page = [], 1
    while page <= max_pages:
        d = post(dict(pageNum=page, pageSize=30, column=column, tabName='fulltext', plate='', stock=stock, searchkey=key,
                      secid='', category='', trade='', seDate=se_date, sortName='', sortType='', isHLtitle='true'))
        anns = d.get('announcements') or []
        for a in anns:
            a['title'] = re.sub(r'</?em>', '', a.get('announcementTitle') or '')
        out += anns
        if not d.get('hasMore') or not anns:
            break
        page += 1
        time.sleep(0.6)
    return out


def stages_1_2():
    if CACHE.exists():
        return json.loads(CACHE.read_text('utf-8'))
    started = now()
    pool = {}
    for column in ('szse', 'sse'):
        for a in search('行政处罚决定书', column, '2019-01-01~2025-12-31'):
            if '行政处罚决定书' not in a['title'] or any(s in a['title'] for s in SKIP_TITLE):
                continue
            c = pool.setdefault(a['secCode'], dict(code=a['secCode'], name=a['secName'], org_id=a.get('orgId'), column=column,
                                                   decisions=[]))
            if a['adjunctUrl'] not in {x['adjunct'] for x in c['decisions']}:
                c['decisions'].append(dict(title=a['title'], adjunct=a['adjunctUrl'], time=a['announcementTime']))
    for code, c in pool.items():
        notes = search('事先告知书', c['column'], '2018-01-01~2025-12-31', stock=f"{code},{c['org_id']}", max_pages=3)
        c['notices'] = [dict(title=a['title'], adjunct=a['adjunctUrl'], time=a['announcementTime']) for a in notes
                        if a.get('secCode') == code and '事先告知书' in a['title'] and not any(s in a['title'] for s in SKIP_TITLE)]
        time.sleep(0.4)
    data = dict(started=started, finished=now(), query=dict(pool_key='行政处罚决定书', notice_key='事先告知书',
                pool_dates='2019-01-01~2025-12-31', notice_dates='2018-01-01~2025-12-31', skip_title=SKIP_TITLE), pool=pool)
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1), 'utf-8')
    return data


def base_name(name):
    return re.sub(r'^S?T|^退市', '', name.replace('*', '')).strip() or name


def batch_found(codes, names):
    """One pass per pattern type over the working tree and git HEAD; returns the set of found strings."""
    found = set()
    code_pat = '(?<![0-9A-Za-z])(?:' + '|'.join(sorted(set(codes))) + ')(?![0-9A-Za-z])'
    names_file = OUT / '_names.txt'
    names_file.write_text('\n'.join(sorted(set(n for n in names if n))) + '\n', 'utf-8')
    for cmd in (['grep', '-rhoP', *EXCLUDE, code_pat, *LOCAL_ROOTS],
                ['grep', '-rhoF', *EXCLUDE, '-f', str(names_file), *LOCAL_ROOTS],
                ['git', '-C', '/root', 'grep', '-hoP', code_pat, 'HEAD'],
                ['git', '-C', '/root', 'grep', '-hoF', '-f', str(names_file), 'HEAD']):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode not in (0, 1):
            raise RuntimeError(f'search failed: {cmd[:3]} {r.stderr[:200]}')
        found |= parse_tokens(r.stdout)
    return found


def parse_tokens(text):
    """grep/git-grep output -> the matched strings; 'Binary file X matches' lines name the file."""
    out = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('Binary file ') and line.endswith(' matches'):
            out.add(line[len('Binary file '):-len(' matches')])
        else:
            out.add(line[len('HEAD:'):] if line.startswith('HEAD:') else (line.split(':')[0] if ':' in line else line))
    return out


def download(adjunct, name):
    path = RAW / name
    url = STATIC + adjunct
    if not path.exists():
        body = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=60).read()
        path.write_bytes(body)
        retrieved = now()
        time.sleep(0.5)
    else:
        body, retrieved = path.read_bytes(), json.loads((RAW / (name + '.meta.json')).read_text('utf-8'))['retrieved_at']
    txt_path = RAW / (name + '.txt')
    if not txt_path.exists():
        txt_path.write_text(subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True).stdout, 'utf-8')
    txt = txt_path.read_text('utf-8')
    meta = dict(url=url, retrieved_at=retrieved, sha256=hashlib.sha256(body).hexdigest(), bytes=len(body), file=str(path),
                text_chars=len(txt), text_sha256=hashlib.sha256(txt.encode()).hexdigest())
    (RAW / (name + '.meta.json')).write_text(json.dumps(meta, ensure_ascii=False, indent=1), 'utf-8')
    return meta, txt


def clean_name(n):
    prev = None
    while prev != n:
        prev, n = n, NAME_NOISE.sub('', n)
    return n


def penalty_table(text):
    t = re.sub(r'\s+', '', text)
    rows = []
    for names, amount in PENALTY_RE.findall(t):
        parties = [n for n in (clean_name(x) for x in re.split(r'[、，,和及]', names)) if 2 <= len(n) <= 40]
        try:
            rows.append((parties, float(amount.replace(',', '').replace('，', ''))))
        except ValueError:
            pass
    return rows


def structure(c):
    """Most recent decision of the company that meets the structure criteria, with its matching notice."""
    tried = []
    for dec in sorted(c['decisions'], key=lambda x: x['time'], reverse=True):
        try:
            dmeta, dtxt = download(dec['adjunct'], f"{c['code']}_decision_{dec['time']}.pdf")
        except Exception as exc:
            tried.append(dict(dec, error=f'download failed: {exc}'))
            continue
        table = penalty_table(dtxt)
        parties = sorted({p for ps, _ in table for p in ps})
        levels = sorted({a for _, a in table})
        info = dict(dec, **dmeta, penalty_lines=len(table), parties=len(parties), amount_levels=levels,
                    total_wan=round(sum(len(ps) * a for ps, a in table), 4))
        if len(parties) < CRITERIA['min_parties'] or len(levels) < CRITERIA['min_amount_levels']:
            tried.append(dict(info, reason=f'{len(parties)} parties, {len(levels)} amount levels'))
            continue
        flat = re.sub(r'\s+', '', dtxt)
        for note in sorted((n for n in c.get('notices', []) if n['time'] < dec['time']), key=lambda x: x['time'], reverse=True):
            try:
                nmeta, ntxt = download(note['adjunct'], f"{c['code']}_notice_{note['time']}.pdf")
            except Exception as exc:
                tried.append(dict(info, notice=note, reason=f'notice download failed: {exc}'))
                continue
            ntable = penalty_table(ntxt)
            nflat = re.sub(r'\s+', '', ntxt)
            overlap = sum(p in nflat for p in parties) / len(parties)
            if not ntable or overlap < CRITERIA['notice_same_case_min_party_overlap']:
                tried.append(dict(info, notice=dict(note, **nmeta), reason=f'notice penalty lines {len(ntable)}, party overlap {overlap:.2f}'))
                continue
            proposed = {p: a for ps, a in ntable for p in ps}
            final = {p: a for ps, a in table for p in ps}
            return dict(code=c['code'], name=c['name'], decision=info, notice=dict(note, **nmeta), party_names=parties,
                        notice_party_overlap=round(overlap, 3), proposed_total_wan=round(sum(proposed.values()), 4),
                        adjusted=sorted(p for p in final if p in proposed and proposed[p] != final[p]),
                        dropped_at_final=sorted(set(proposed) - set(final)),
                        case_numbers=sorted(set(CASE_NO_RE.findall(flat)))), tried
        tried.append(dict(info, reason='no matching advance notice before this decision'))
    return None, tried


def prefilter():
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(exist_ok=True)
    data = stages_1_2()
    pool = data['pool']
    paired = {k: v for k, v in pool.items() if v.get('notices')}
    print('stage 1 companies:', len(pool), '| stage 2 paired:', len(paired), flush=True)

    found = batch_found(list(paired), [base_name(c['name']) for c in paired.values()])
    rejected, clean = [], {}
    for code, c in paired.items():
        hit = [t for t in (code, base_name(c['name'])) if t in found]
        if hit:
            rejected.append(dict(code=code, name=c['name'], stage=3, reason='local hit (batch pre-check)', terms=hit))
        else:
            clean[code] = c
    print('stage 3 kept:', len(clean), flush=True)

    survivors = []
    for i, (code, c) in enumerate(sorted(clean.items())):
        rec, tried = structure(c)
        if rec:
            survivors.append(rec)
        else:
            rejected.append(dict(code=code, name=c['name'], stage=4, reason='structure criteria not met', tried=tried))
        if (i + 1) % 25 == 0:
            print(f'  stage 4 progress {i + 1}/{len(clean)} survivors {len(survivors)}', flush=True)
    survivors.sort(key=lambda r: (-r['decision']['parties'], -len(r['adjusted']), r['code']))
    print('stage 4 survivors:', len(survivors), flush=True)
    log = dict(stage='prefilter', finished=now(), criteria=CRITERIA, counts=dict(pool=len(pool), paired=len(paired),
               after_batch_check=len(clean), structure_survivors=len(survivors)), survivors=survivors, rejected=rejected,
               pool_cache=dict(file=str(CACHE), sha256=hashlib.sha256(CACHE.read_bytes()).hexdigest()))
    (OUT / 'PREFILTER_LOG.json').write_text(json.dumps(log, ensure_ascii=False, indent=1), 'utf-8')
    for r in survivors:
        print(f"  {r['code']} {r['name']} parties={r['decision']['parties']} levels={r['decision']['amount_levels']} "
              f"total={r['decision']['total_wan']} adjusted={len(r['adjusted'])} dropped={len(r['dropped_at_final'])}")


def term_hits(term):
    if re.fullmatch(r'\d{6}', term):
        pat = f'(?<![0-9A-Za-z]){term}(?![0-9A-Za-z])'
        tree = sorted(parse_tokens(subprocess.run(['grep', '-rlsP', *EXCLUDE, pat, *LOCAL_ROOTS], capture_output=True, text=True).stdout))
        head = sorted(parse_tokens(subprocess.run(['git', '-C', '/root', 'grep', '-lP', pat, 'HEAD'], capture_output=True, text=True).stdout))
    else:
        tree = sorted(parse_tokens(subprocess.run(['grep', '-rlsF', *EXCLUDE, term, *LOCAL_ROOTS], capture_output=True, text=True).stdout))
        head = sorted(parse_tokens(subprocess.run(['git', '-C', '/root', 'grep', '-lF', term, 'HEAD'], capture_output=True, text=True).stdout))
    history = subprocess.run(['git', '-C', '/root', 'log', '--all', '--oneline', '-F', '-S', term], capture_output=True,
                             text=True, timeout=900).stdout.splitlines()
    return dict(working_tree=tree[:5], git_head=head[:5], git_history=history[:5])


def audit(n):
    log = json.loads((OUT / 'PREFILTER_LOG.json').read_text('utf-8'))
    results = []
    for rec in log['survivors'][:n]:
        dtxt = Path(rec['decision']['file'] + '.txt').read_text('utf-8')
        full = re.findall(r'当事人[：:]\s*([^，,（(\s]{4,40}?有限公司)', re.sub(r'\s+', '', dtxt))
        terms = [rec['code'], base_name(rec['name'])] + sorted(set(full))[:2] + rec['party_names'] + rec['case_numbers']
        hits = {}
        for t in dict.fromkeys(terms):
            h = term_hits(t)
            if any(h.values()):
                hits[t] = h
        results.append(dict(code=rec['code'], name=rec['name'], terms_checked=len(dict.fromkeys(terms)), hits=hits,
                            independent=not hits))
        print(f"  {rec['code']} {rec['name']} terms={len(dict.fromkeys(terms))} hits={len(hits)} -> "
              f"{'INDEPENDENT' if not hits else 'REJECTED ' + ', '.join(list(hits)[:4])}", flush=True)
    (OUT / 'AUDIT_LOG.json').write_text(json.dumps(dict(finished=now(), audited=len(results), results=results),
                                                   ensure_ascii=False, indent=1), 'utf-8')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--prefilter', action='store_true')
    ap.add_argument('--audit', type=int, default=0)
    a = ap.parse_args()
    if a.prefilter:
        prefilter()
    if a.audit:
        audit(a.audit)


CASE_ID_RE = re.compile(r'([\u4e00-\u9fa5]{1,12}[〔【\[]20\d\d[〕】\]]\d+号)')


def case_ids(flat):
    return sorted({c for c in CASE_ID_RE.findall(flat) if any(k in c for k in ('罚', '禁入', '调查', '决定'))})


def hits_by_term(terms):
    """Batched: one scan per source over all terms; returns term -> list of 'source:file' (first 5)."""
    terms = [t for t in dict.fromkeys(terms) if t]
    f = OUT / '_terms.txt'
    f.write_text('\n'.join(terms) + '\n', 'utf-8')
    out = {t: [] for t in terms}
    for source, cmd in (('tree', ['grep', '-rHoF', *EXCLUDE, '-f', str(f), *LOCAL_ROOTS]),
                        ('head', ['git', '-C', '/root', 'grep', '-HoF', '-f', str(f), 'HEAD'])):
        r = subprocess.run(cmd, capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if line.startswith('Binary file '):
                continue
            path, _, match = line.rpartition(':')
            if match in out and len(out[match]) < 5:
                out[match].append(f'{source}:{path}')
    alternation = '|'.join(re.escape(t) for t in terms)
    r = subprocess.run(['git', '-C', '/root', 'log', '--all', '--format=%h %s', '-G', alternation], capture_output=True,
                       text=True, timeout=1800)
    commits = r.stdout.splitlines()
    if commits:
        for t in terms:
            h = subprocess.run(['git', '-C', '/root', 'log', '--all', '--format=%h', '-F', '-S', t], capture_output=True,
                               text=True, timeout=900).stdout.split()
            out[t] += [f'history:{c}' for c in h[:3]]
    return {t: v for t, v in out.items() if v}, len(commits)


def audit_codes(codes):
    log = json.loads((OUT / 'PREFILTER_LOG.json').read_text('utf-8'))
    by = {r['code']: r for r in log['survivors']}
    results = []
    for code in codes:
        rec = by[code]
        flat = re.sub(r'\s+', '', Path(rec['decision']['file'] + '.txt').read_text('utf-8'))
        nflat = re.sub(r'\s+', '', Path(rec['notice']['file'] + '.txt').read_text('utf-8'))
        full = sorted(set(re.findall(r'([\u4e00-\u9fa5（）()]{4,40}?股份有限公司)', flat)))[:3]
        cids = sorted(set(case_ids(flat) + case_ids(nflat)))
        strong = [code, base_name(rec['name'])] + full + cids
        names = rec['party_names']
        hits, n_commits = hits_by_term(strong + names)
        strong_hits = {t: h for t, h in hits.items() if t in strong}
        name_hits = {t: h for t, h in hits.items() if t in names and t not in strong}
        verdict = 'REJECTED' if strong_hits else ('NAME_COLLISION_ONLY' if name_hits else 'INDEPENDENT')
        res = dict(code=code, name=rec['name'], verdict=verdict, terms=dict(strong=strong, party_names=names),
                   strong_hits=strong_hits, name_hits=name_hits, history_commits_matching_any_term=n_commits)
        results.append(res)
        print(f"  {code} {rec['name']:<8} {verdict:<20} strong={list(strong_hits)[:3]} names={list(name_hits)[:4]} "
              f"terms={len(strong) + len(names)}", flush=True)
    path = OUT / 'AUDIT_LOG.json'
    prior = json.loads(path.read_text('utf-8'))['results'] if path.exists() else []
    keep = [r for r in prior if r['code'] not in codes]
    path.write_text(json.dumps(dict(finished=now(), results=keep + results), ensure_ascii=False, indent=1), 'utf-8')


def code_hits(code):
    """Six-digit code with digit/letter boundaries; history hits are verified against the commit diff."""
    pat = f'(?<![0-9A-Za-z]){code}(?![0-9A-Za-z])'
    tree = sorted(parse_tokens(subprocess.run(['grep', '-rlsP', *EXCLUDE, pat, *LOCAL_ROOTS], capture_output=True, text=True).stdout))
    head = sorted(parse_tokens(subprocess.run(['git', '-C', '/root', 'grep', '-lP', pat, 'HEAD'], capture_output=True, text=True).stdout))
    hist = []
    for c in subprocess.run(['git', '-C', '/root', 'log', '--all', '--format=%h', '-S', code], capture_output=True,
                            text=True, timeout=900).stdout.split()[:10]:
        r = subprocess.run(['git', '-C', '/root', 'grep', '-lP', pat, c], capture_output=True, text=True, errors='replace')
        if r.stdout.strip():
            hist.append(c)
    return [f'tree:{p}' for p in tree[:5]] + [f'head:{p}' for p in head[:5]] + [f'history:{c}' for c in hist[:3]]


_audit_codes_v1 = audit_codes


def audit_codes(codes):
    """As before, but the stock code is checked with boundaries instead of a plain substring."""
    global hits_by_term
    plain = hits_by_term

    def with_code_boundary(terms):
        codes_ = [t for t in terms if re.fullmatch(r'\d{6}', t)]
        hits, n = plain([t for t in terms if t not in codes_])
        for c in codes_:
            h = code_hits(c)
            if h:
                hits[c] = h
        return hits, n
    hits_by_term = with_code_boundary
    try:
        _audit_codes_v1(codes)
    finally:
        hits_by_term = plain
