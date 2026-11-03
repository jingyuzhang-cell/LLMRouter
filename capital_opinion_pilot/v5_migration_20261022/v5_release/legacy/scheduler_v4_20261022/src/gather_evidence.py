"""Task 1: build the frozen evidence library for the Jiangsu Shuntian (600287) pilot.

Downloads the four public documents, hashes the raw files, extracts text,
records in-document public dates, and enforces the 2024-07-10 information cutoff.
No model calls.
"""
import hashlib
import html.parser
import json
import re
import subprocess
import urllib.request
from pathlib import Path

from pilot_common import PILOT_DIR, all_dates

CUTOFF = '2024-07-10'

DOCS = [
    {'doc_id': 'csrc_penalty_2024_41',
     'title': '中国证监会行政处罚决定书（江苏舜天〕〔2024〕41号）',
     'url': 'https://www.csrc.gov.cn/csrc/c101928/c7491450/content.shtml',
     'kind': 'html'},
    {'doc_id': 'st_announce_2024_020',
     'title': '江苏舜天股份有限公司临2024-020公告（收到行政处罚决定书）',
     'url': 'https://static.cninfo.com.cn/finalpage/2024-07-06/1220540317.PDF',
     'kind': 'pdf'},
    {'doc_id': 'st_announce_2024_021',
     'title': '江苏舜天股份有限公司临2024-021公告（风险警示相关安排）',
     'url': 'https://static.cninfo.com.cn/finalpage/2024-07-06/1220540316.PDF',
     'kind': 'pdf'},
    {'doc_id': 'st_advance_notice_2023',
     'title': '江苏舜天2023年行政处罚事先告知公告（上海证券报电子版）',
     'url': 'https://paper.cnstock.com/html/2023-07/03/content_1789561.htm',
     'kind': 'html'},
]

RAW = PILOT_DIR / 'evidence' / 'raw'
TXT = PILOT_DIR / 'evidence' / 'text'
RAW.mkdir(parents=True, exist_ok=True)
TXT.mkdir(parents=True, exist_ok=True)


class TextExtract(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def http_date_hint(url):
    m = re.search(r'/(\d{4}-\d{2}-\d{2})/', url)
    return f'{m.group(1)}' if m else None


def main():
    manifest = []
    for doc in DOCS:
        dest = RAW / (doc['doc_id'] + ('.html' if doc['kind'] == 'html' else '.pdf'))
        req = urllib.request.Request(doc['url'], headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'})
        with urllib.request.urlopen(req, timeout=60) as r:
            blob = r.read()
            ctype = r.headers.get('content-type', '')
        dest.write_bytes(blob)
        sha = hashlib.sha256(blob).hexdigest()

        if doc['kind'] == 'html':
            raw_text = blob.decode('utf-8', errors='replace')
            p = TextExtract()
            p.feed(raw_text)
            text = '\n'.join(p.parts)
        else:
            r = subprocess.run(['pdftotext', '-layout', str(dest), '-'], capture_output=True)
            text = r.stdout.decode('utf-8', errors='replace')
        text = re.sub(r'[ \t]+', ' ', re.sub(r'\n{3,}', '\n\n', text)).strip()
        (TXT / f'{doc["doc_id"]}.txt').write_text(text)

        dates_in_doc = all_dates(''.join(text.split()))
        url_date = http_date_hint(doc['url'])
        # page-level publish dates only exist in raw HTML metadata
        meta_dates = re.findall(r'20\d{2}-\d{2}-\d{2}', blob.decode('utf-8', errors='replace')) if doc['kind'] == 'html' else []
        # public date = URL-embedded date (cninfo/cnstock paths) else page meta date (csrc)
        candidates = ([url_date] if url_date else []) + meta_dates
        public_date = next((d for d in candidates if d), None)
        manifest.append({
            'doc_id': doc['doc_id'], 'title': doc['title'], 'url': doc['url'],
            'retrieval_status': 'OK', 'http_content_type': ctype, 'bytes': len(blob),
            'sha256_raw_file': sha, 'raw_file': str(dest), 'text_file': str(TXT / f'{doc["doc_id"]}.txt'),
            'text_chars': len(text), 'dates_found_in_document': dates_in_doc[:20],
            'page_meta_dates': meta_dates[:5],
            'url_embedded_date': url_date, 'declared_public_date': public_date,
            'cutoff_2024_07_10_respected': bool(public_date and public_date <= CUTOFF),
        })
    out = PILOT_DIR / 'evidence_manifest.json'
    out.write_text(json.dumps({'event': '江苏舜天(600287)信息披露违法违规事件',
                               'information_cutoff': CUTOFF,
                               'gathered_at': __import__('time').strftime('%Y-%m-%dT%H:%M:%S'),
                               'method': 'direct HTTP download, no model calls',
                               'documents': manifest}, ensure_ascii=False, indent=2))
    for m in manifest:
        print(f"{m['doc_id']}: {m['bytes']}B sha={m['sha256_raw_file'][:12]} text={m['text_chars']}c "
              f"pub={m['declared_public_date']} cutoff_ok={m['cutoff_2024_07_10_respected']}")
    print('manifest ->', out)


if __name__ == '__main__':
    main()
