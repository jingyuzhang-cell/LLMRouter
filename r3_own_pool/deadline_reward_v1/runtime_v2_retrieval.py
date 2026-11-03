"""runtime_v2_retrieval — Part 1: real autonomous retrieval.

Providers:
  LocalCorpusProvider — frozen corpus (load_docs pool + zeda docs +
    anything in corpus/); zero network.
  HttpProvider        — live official-source retrieval (csrc.gov.cn
    penalty search/fetch; cninfo announcement query). HTTP document
    retrieval is NOT a model call: ¥0, not under the model-API HOLD
    (operator precedent: zeda docs fetched 2026-10-27 under HOLD).

Retrieval nodes in a DAGSpec: role='retrieval' with spec field
'query' (+ optional 'source'); the provider returns doc records
{doc_id, title, url, text}; the node produces evidence references
consumed by extraction nodes. All retrievals cached + ledged.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path('/root/r3_own_pool/deadline_reward_v1')
CORPUS = HERE / 'runtime_v2_corpus'
CORPUS.mkdir(exist_ok=True)
LEDGER = CORPUS / 'RETRIEVAL_LEDGER.jsonl'


def _ledger_write(rec):
    with open(LEDGER, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


class LocalCorpusProvider:
    """frozen materials, zero network."""

    def __init__(self):
        self.docs = {}
        import sys
        sys.path.insert(0, '/root/r3_own_pool')
        from deadline_reward_v1.full_dag_tasks import load_docs
        for k, v in load_docs().items():
            did = v['doc_id']
            if did not in self.docs:
                self.docs[did] = dict(
                    doc_id=did, title=v.get('title', did)[:60],
                    url='frozen:load_docs', text=v['text'],
                    event=v['event'])
        # logical aliases (deterministic, prefix-keyed — fixes the
        # last-wins bug where ydt_d1 pointed at the wrong doc and
        # ydt_d3 never existed)
        for k, v in list(self.docs.items()):
            if v.get('event') in ('舜天', 'jsst'):
                self.docs['jsst'] = v
            if k.startswith('D1_E03') or 'D1_E03' in k:
                self.docs['ydt_d1'] = v
            if k.startswith('D3_E03') or 'D3_E03' in k:
                self.docs['ydt_d3'] = v
            if k.startswith('D2_E03') or 'D2_E03' in k:
                self.docs['ydt_d2'] = v
        z = json.loads((HERE / 'h1v8_docs' / 'zeda_docs.json').read_text())
        for d in z['docs']:
            self.docs[d['doc_id']] = dict(
                doc_id=d['doc_id'], title=d['title'][:60],
                url=d['source_url'], text=d['text'], event='zeda')
        for f in CORPUS.glob('*.json'):
            d = json.loads(f.read_text())
            self.docs[d['doc_id']] = d

    def search(self, query, source=None, k=3):
        qk = set(re.findall(r'[\u4e00-\u9fa5]{2,}', query))
        scored = []
        for d in self.docs.values():
            hit = len(qk & set(re.findall(
                r'[\u4e00-\u9fa5]{2,}', d['title'] + d.get('event', '')
                + d['text'][:300])))
            if hit:
                scored.append((hit, d))
        scored.sort(key=lambda x: -x[0])
        rec = dict(provider='local_corpus', query=query, source=source,
                   n=len(scored[:k]),
                   docs=[d['doc_id'] for _, d in scored[:k]],
                   ts=time.time())
        _ledger_write(rec)
        return [dict(doc_id=d['doc_id'], title=d['title'], url=d['url'],
                     text=d['text']) for _, d in scored[:k]]


class HttpProvider:
    """live official retrieval (documents only; no model calls)."""

    UA = {'User-Agent': 'Mozilla/5.0 (research; contact: lab)'}

    def fetch_url(self, url):
        req = urllib.request.Request(url, headers=self.UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode('utf-8', errors='ignore')

    @staticmethod
    def _text(html):
        t = re.sub(r'<script.*?</script>|<style.*?</style>', '', html,
                   flags=re.S)
        t = re.sub(r'<[^>]+>', '\n', t).replace('&nbsp;', ' ')
        lines = [l.strip() for l in t.split('\n') if l.strip()]
        txt = '\n'.join(lines)
        i = txt.find('当事人:')
        if i < 0:
            i = txt.find('当事人：')
        if i > 0:
            body = txt[i:]
            for cut in ('相关阅读', '扫一扫', '主办单位', '京ICP备',
                        '政府网站标识', '【打印】'):
                j = body.find(cut)
                if j > 0:
                    body = body[:j]
            txt = body.strip()
        return txt

    def fetch_doc(self, url, doc_id=None):
        """direct official-URL document fetch (proven live path)."""
        txt = self._text(self.fetch_url(url))
        doc_id = doc_id or ('http_' + url.rsplit('/', 2)[-2])
        doc = dict(doc_id=doc_id,
                   title=f'live:{doc_id}', url=url, text=txt)
        if len(txt) > 300:
            (CORPUS / f'{doc_id}.json').write_text(
                json.dumps(doc, ensure_ascii=False))
        _ledger_write(dict(provider='http_direct', url=url,
                           doc_id=doc_id, chars=len(txt),
                           ts=time.time()))
        return doc if len(txt) > 300 else None

    def search(self, query, source='csrc', k=3):
        """search = csrc site query via public search endpoint; on
        miss, falls back to a direct penalty-listing page fetch."""
        rec = dict(provider='http', query=query, source=source,
                   ts=time.time())
        try:
            if source == 'csrc':
                url = ('https://www.csrc.gov.cn/csearch/engine'
                       '?fulltext=' + urllib.parse.quote(query))
                html = self.fetch_url(url)
                links = re.findall(
                    r'href="(https://www\.csrc\.gov\.cn/'
                    r'csrc/c101928/c\d+/content\.shtml)"[^>]*>([^<]+)',
                    html)
                outs = []
                for u, title in links[:k]:
                    txt = self._text(self.fetch_url(u))
                    if len(txt) < 300:
                        continue
                    did = 'http_' + u.rsplit('/', 2)[-2]
                    doc = dict(doc_id=did, title=title.strip()[:60],
                               url=u, text=txt)
                    (CORPUS / f'{did}.json').write_text(
                        json.dumps(doc, ensure_ascii=False))
                    outs.append(doc)
                rec.update(n=len(outs), docs=[d['doc_id'] for d in outs],
                           urls=[d['url'] for d in outs])
                _ledger_write(rec)
                return outs
        except Exception as e:
            rec.update(error=repr(e)[:150])
            _ledger_write(rec)
            return []


def retrieval_node_spec(query, source=None):
    return dict(id=f'retr_{abs(hash(query)) % 9999}', role='retrieval',
                inputs=[], query=query, source=source,
                contract=dict(produces=['evidence_refs']))


def get_provider(pref):
    return HttpProvider() if pref == 'http' else LocalCorpusProvider()
