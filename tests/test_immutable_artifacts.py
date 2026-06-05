import tempfile
import unittest
from pathlib import Path

from speech_archive_lib import artifacts


class ImmutableArtifactTests(unittest.TestCase):
    def test_next_version_starts_at_v1_and_increments(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            stage = root / "data" / "artifacts" / "04_asr"
            self.assertEqual(artifacts.next_version(stage, "sound.asr.model.segments", ".json"), 1)
            stage.mkdir(parents=True)
            (stage / "sound.asr.model.segments.v1.json").write_text("{}")
            self.assertEqual(artifacts.next_version(stage, "sound.asr.model.segments", ".json"), 2)

    def test_versioned_path_format(self):
        p = artifacts.versioned_path(Path("data/artifacts/04_asr"), "sound.asr.model.segments", ".json", 3)
        self.assertEqual(str(p), "data/artifacts/04_asr/sound.asr.model.segments.v3.json")

    def test_stage_dir_uses_number_and_name(self):
        self.assertEqual(str(artifacts.stage_dir(Path("data"), "04", "asr")), "data/artifacts/04_asr")

    def test_ensure_dirs_includes_late_review_and_embedding_stages(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            artifacts.ensure_dirs(root)
            self.assertTrue((root / "data" / "artifacts" / "07_voice_identification").is_dir())
            self.assertTrue((root / "data" / "artifacts" / "10_role_consistency_review").is_dir())
            self.assertTrue((root / "data" / "artifacts" / "11_voice_profile_embeddings").is_dir())
            self.assertTrue((root / "data" / "artifacts" / "99_check").is_dir())


if __name__ == "__main__":
    unittest.main()
