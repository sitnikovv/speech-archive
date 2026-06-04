import unittest
from pathlib import Path
from speech_archive_lib import artifacts


class ModelPathTests(unittest.TestCase):
    def test_model_cache_candidates_include_snapshot_and_flat_hf_names(self):
        paths = artifacts.model_cache_candidates(Path('data'), 'nvidia/parakeet-tdt-0.6b-v3')
        text = [str(p) for p in paths]
        self.assertIn('data/models-cache/huggingface/nvidia__parakeet-tdt-0.6b-v3', text)
        self.assertIn('data/models-cache/huggingface/models--nvidia--parakeet-tdt-0.6b-v3', text)


if __name__ == '__main__':
    unittest.main()
