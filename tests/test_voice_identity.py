import tempfile
import unittest
from pathlib import Path

from speech_archive_lib import voice_identity, voice_profiles


class FakeEmbedder:
    model_id = "fake"

    def embed(self, audio_path: Path, start=None, end=None):
        key = f"{audio_path}:{start}:{end}"
        if "yana" in str(audio_path) or start == 1.0:
            return [1.0, 0.0]
        return [0.0, 1.0]


class VoiceIdentityTests(unittest.TestCase):
    def test_cosine_similarity(self):
        self.assertAlmostEqual(voice_identity.cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(voice_identity.cosine_similarity([1, 0], [0, 1]), 0.0)

    def test_match_speaker_auto_matches_best_enrolled_sample(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "voice_profiles"
            profile = voice_profiles.create_profile(root, "Яна Ситникова", aliases=["Яна"])
            sample_dir = Path(profile["profile_dir"]) / "samples" / "enrolled"
            sample_dir.mkdir(parents=True)
            sample = sample_dir / "yana.mp3"
            sample.write_bytes(b"fake")
            result = voice_identity.match_speaker(
                embedder=FakeEmbedder(),
                audio_path=Path("call.wav"),
                speaker_label="SPEAKER_00",
                spans=[{"start": 1.0, "end": 2.0, "text": "hello"}],
                profiles_root=root,
                profiles=voice_profiles.load_profiles(root),
                phone_resolution={"priority_profiles": []},
                auto_threshold=0.9,
                confirm_threshold=0.5,
            )
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["best"]["person_id"], "яна_ситникова")

    def test_assignments_from_voice_id_uses_only_matched(self):
        data = {"artifact": "voice.json", "speaker_matches": [
            {"speaker_label": "SPEAKER_00", "status": "matched", "best": {"person_id": "yana", "full_name": "Яна", "score": 0.91, "sample": "s.mp3"}},
            {"speaker_label": "SPEAKER_01", "status": "needs_confirmation", "best": {"person_id": "slava", "score": 0.7}},
        ]}
        result = voice_identity.assignments_from_voice_id(data)
        self.assertEqual(result["SPEAKER_00"]["name"], "Яна")
        self.assertNotIn("SPEAKER_01", result)


if __name__ == "__main__":
    unittest.main()
