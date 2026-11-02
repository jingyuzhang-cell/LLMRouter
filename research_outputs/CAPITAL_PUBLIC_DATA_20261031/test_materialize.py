import copy
import json
from pathlib import Path
import tempfile
import unittest
from materialize import ROOT, build, digest

class SourceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.events = json.loads((ROOT/'EVENT_INDEX.json').read_text())
        self.manifest = json.loads((ROOT/'SOURCE_MANIFEST.json').read_text())

    def test_real_packages_preserve_text_and_exclude_future(self):
        for event in self.events:
            p = build(ROOT, event, self.manifest)
            self.assertEqual(len(p['documents']), 2)
            for d in p['documents']:
                self.assertLessEqual(d['publication_date'], p['information_cutoff'])
                for page in d['pages']:
                    self.assertEqual(digest(page['text'].encode()), page['text_sha256'])
        r = build(ROOT, self.events[1], self.manifest)
        self.assertNotIn('PENALTY_PRENOTICE', [d['source_id'] for d in r['documents']])

    def test_future_source_rejected_even_if_added_to_allowlist(self):
        e = copy.deepcopy(self.events[1])
        e['excluded_future_sources'] = []
        e['sources'].append('PENALTY_PRENOTICE')
        with self.assertRaisesRegex(ValueError, 'FUTURE_SOURCE'):
            build(ROOT, e, self.manifest)

    def test_reference_metadata_never_projected(self):
        e = copy.deepcopy(self.events[0])
        for key in ('answers', 'references', 'gold', 'documents'):
            e[key] = 'PRIVATE_REFERENCE_SENTINEL'
        p = build(ROOT, e, self.manifest)
        self.assertNotIn('PRIVATE_REFERENCE_SENTINEL', json.dumps(p))

    def test_missing_failed_duplicate_and_missing_date_rejected(self):
        for mode in ('missing', 'failed', 'duplicate', 'date'):
            m = copy.deepcopy(self.manifest)
            if mode == 'missing': m.pop(0)
            if mode == 'failed': m[0]['status'] = 'FAILED_OR_PARTIAL'
            if mode == 'duplicate': m.append(copy.deepcopy(m[0]))
            if mode == 'date': m[0]['publication_date_from_listing'] = ''
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                build(ROOT, self.events[0], m)

    def test_modified_text_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'raw').write_bytes(b'raw')
            (root/'text').write_bytes(b'changed')
            e = dict(event='E', cutoff='2026-01-01', sources=['S'], question='Q')
            m = [dict(event='E', source_id='S', status='DOWNLOADED',
                      publication_date_from_listing='2026-01-01', file='raw',
                      sha256=digest(b'raw'), text_file='text',
                      text_sha256=digest(b'original'), url='local-test')]
            with self.assertRaisesRegex(ValueError, 'SOURCE_HASH_MISMATCH'):
                build(root,e,m)

if __name__ == '__main__': unittest.main()
