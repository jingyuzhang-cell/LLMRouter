import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from .fast_backend import VerifiedHashCache, FastBackend

class VerificationTests(unittest.TestCase):
    def test_hash_reuse_and_change(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'weights'; p.write_bytes(b'old')
            cache=VerifiedHashCache()
            self.assertEqual(cache(p),hashlib.sha256(b'old').hexdigest())
            self.assertEqual(cache(p),hashlib.sha256(b'old').hexdigest())
            self.assertEqual(cache.hash_reads + cache.cache_hits,2)
            p.write_bytes(b'new')
            self.assertEqual(cache(p),hashlib.sha256(b'new').hexdigest())
            self.assertGreaterEqual(cache.hash_reads,2)
    def test_missing_file_fails(self):
        with self.assertRaises(FileNotFoundError): VerifiedHashCache()('/missing-checkpoint')
    def test_independent_campaign_cache(self):
        self.assertIsNot(VerifiedHashCache().entries,VerifiedHashCache().entries)
    def test_backend_does_not_mutate_engine(self):
        def start(slot): return sha(slot), OUT
        # Fixture represents only hashing/start globals, no model execution.
        fn=type(start)(start.__code__,dict(sha=lambda p:'original',OUT='original'))
        engine=SimpleNamespace(OUT='original',start_model=fn)
        fast=FastBackend(engine);fast.OUT='isolated'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'weights';p.write_bytes(b'a')
            self.assertEqual(fast.start_model(p),(hashlib.sha256(b'a').hexdigest(),'isolated'))
            self.assertEqual(engine.start_model(p),('original','original'))

if __name__=='__main__': unittest.main()
