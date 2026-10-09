"""Opt-in backend: reuse verified file hashes while identity is unchanged.
Does not change model arguments, prompts, dispatch ordering or response caching.
New backend object per campaign; never install into an already-running process.
"""
import hashlib
import types
import tempfile
from pathlib import Path

class VerifiedHashCache:
    def __init__(self):
        self.entries = {}
        self.hash_reads = 0
        self.cache_hits = 0
        self.precision = {}

    def metadata_reliable(self, path):
        parent = path.resolve().parent
        if parent not in self.precision:
            # Fail closed on filesystems with unchanged metadata after rewrite.
            try:
                with tempfile.NamedTemporaryFile(dir=parent) as probe:
                    probe.write(b'aaa'); probe.flush()
                    before = self.identity(Path(probe.name))
                    probe.seek(0); probe.write(b'bbb'); probe.flush()
                    self.precision[parent] = self.identity(Path(probe.name)) != before
            except OSError:
                self.precision[parent] = False
        return self.precision[parent]

    @staticmethod
    def identity(path):
        s = path.stat()
        return (str(path.resolve()), s.st_dev, s.st_ino, s.st_size,
                s.st_mtime_ns, s.st_ctime_ns)

    def __call__(self, name):
        path = Path(name)
        before = self.identity(path)
        reusable = self.metadata_reliable(path)
        if reusable and before in self.entries:
            self.cache_hits += 1
            return self.entries[before]
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                h.update(block)
        if self.identity(path) != before:
            raise RuntimeError('Checkpoint changed during verification: ' + str(path))
        self.hash_reads += 1
        if reusable:
            self.entries[before] = h.hexdigest()
        return h.hexdigest()

class FastBackend:
    def __init__(self, engine):
        self.engine = engine
        self.OUT = engine.OUT
        self.verified_hash = VerifiedHashCache()

    def start_model(self, slot):
        # Clone function globals, avoiding mutation of the production module.
        namespace = dict(self.engine.start_model.__globals__)
        namespace.update(sha=self.verified_hash, OUT=self.OUT)
        start = types.FunctionType(self.engine.start_model.__code__, namespace,
                                   self.engine.start_model.__name__,
                                   self.engine.start_model.__defaults__,
                                   self.engine.start_model.__closure__)
        return start(slot)

    def stop_model(self, *args):
        return self.engine.stop_model(*args)

    def call_model(self, *args):
        return self.engine.call_model(*args)
