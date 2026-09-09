from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from router_v2 import embed_queries as e


class EmbeddingTests(unittest.TestCase):
    def test_coverage_check_does_not_pollute_import_path(self):
        before=list(sys.path)
        result=e.local_complete(e.ROOT/'data/cohort_full_v2')
        self.assertIsInstance(result,bool)
        self.assertEqual(before,sys.path)

    def test_gpu_ownership_check(self):
        with patch.object(e.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'123\n','')):
            self.assertFalse(e.gpu_free())
        with patch.object(e.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')):
            self.assertTrue(e.gpu_free())
        with patch.object(e.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','error')):
            with self.assertRaisesRegex(RuntimeError,'ownership'):
                e.gpu_free()

    def test_no_encoder_until_collection_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'collect/logs').mkdir(parents=True)
            with patch.object(e,'ROOT',root),patch.object(e,'plan',return_value={}),patch.object(e,'local_complete',return_value=False),patch.object(e,'gpu_free') as gpu:
                with self.assertRaisesRegex(RuntimeError,'no encoder loaded'):
                    e.encode('unused','unused',root/'job',wait=False)
                gpu.assert_not_called()

    def test_refuse_completed_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'EMBEDDINGS.npz').write_bytes(b'completed')
            with self.assertRaises(FileExistsError):e.encode('unused','unused',root)
            self.assertEqual((root/'EMBEDDINGS.npz').read_bytes(),b'completed')

if __name__=='__main__':unittest.main()
