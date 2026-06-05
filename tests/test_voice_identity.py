import tempfile
import unittest
from pathlib import Path

from speech_archive_lib import voice_identity, voice_profiles


class FakeEmbedder:
    model_id = "fake"

    def __init__(self):
        self.calls = []

    def embed(self, audio_path: Path, start=None, end=None):
        self.calls.append((str(audio_path), start, end))
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
                auto_threshold=0.9,
                confirm_threshold=0.5,
            )
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["best"]["person_id"], "Яна Ситникова")

    def test_profile_person_id_preserves_entered_display_name(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "voice_profiles"
            profile = voice_profiles.create_profile(root, "Вячеслав Ситников")

        self.assertEqual(profile["person_id"], "Вячеслав Ситников")
        self.assertTrue(profile["profile_dir"].endswith("Вячеслав Ситников"))

    def test_cached_sample_embedding_is_reused_and_points_only_to_sample(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "voice_profiles"
            profile = voice_profiles.create_profile(root, "Яна Ситникова")
            sample_dir = Path(profile["profile_dir"]) / "samples" / "enrolled"
            sample_dir.mkdir(parents=True)
            sample = sample_dir / "Яна_Ситникова.sample.abc123.mp3"
            sample.write_bytes(b"fake")
            embedder = FakeEmbedder()

            first = voice_identity.cached_sample_embedding(embedder, sample)
            second = voice_identity.cached_sample_embedding(embedder, sample)
            cache = voice_identity.embedding_cache_path(sample, embedder.model_id)
            data = __import__("json").loads(cache.read_text(encoding="utf-8"))

            self.assertEqual(first, second)
            self.assertEqual(embedder.calls, [(str(sample), None, None)])
            self.assertEqual(data["sample_file"], sample.name)
            self.assertEqual(data["sample_id"], sample.stem)
            self.assertNotIn("source_audio", data)
            self.assertNotIn("source_mp3", data)

    def test_assignments_from_voice_id_uses_only_matched(self):
        data = {"artifact": "voice.json", "speaker_matches": [
            {"speaker_label": "SPEAKER_00", "status": "matched", "best": {"person_id": "yana", "full_name": "Яна", "score": 0.91, "sample": "s.mp3"}},
            {"speaker_label": "SPEAKER_01", "status": "needs_confirmation", "best": {"person_id": "slava", "score": 0.7}},
        ]}
        result = voice_identity.assignments_from_voice_id(data)
        self.assertEqual(result["SPEAKER_00"]["name"], "Яна")
        self.assertNotIn("SPEAKER_01", result)

    def test_backend_cache_paths_use_unified_voice_embeddings_root(self):
        sample = Path("/tmp/voice_profiles/Яна/samples/enrolled/yana.mp3")
        pyannote = voice_identity.embedding_cache_path(sample, "pyannote/embedding")
        ecapa = voice_identity.backend_embedding_cache_path(sample, "speechbrain_ecapa", "speechbrain/spkrec-ecapa-voxceleb")
        self.assertIn("voice_embeddings/pyannote_embedding/pyannote_embedding", pyannote.as_posix())
        self.assertIn("voice_embeddings/speechbrain_ecapa/speechbrain_spkrec-ecapa-voxceleb", ecapa.as_posix())
        self.assertNotEqual(pyannote.parent, ecapa.parent)

    def test_match_speaker_aggregated_uses_topk_mean_and_margin(self):
        class AggregateFakeEmbedder:
            model_id = "fake-aggregate"
            def embed(self, audio_path: Path, start=None, end=None):
                if "yana" in str(audio_path):
                    return [1.0, 0.0]
                if "slava" in str(audio_path):
                    return [0.0, 1.0]
                if start in {1.0, 2.0}:
                    return [1.0, 0.0]
                return [0.0, 1.0]

        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "voice_profiles"
            yana = voice_profiles.create_profile(root, "Яна Ситникова")
            slava = voice_profiles.create_profile(root, "Вячеслав Ситников")
            for profile, name in ((yana, "yana.mp3"), (slava, "slava.mp3")):
                sample_dir = Path(profile["profile_dir"]) / "samples" / "enrolled"
                sample_dir.mkdir(parents=True)
                (sample_dir / name).write_bytes(b"fake")
            result = voice_identity.match_speaker_aggregated(
                embedder=AggregateFakeEmbedder(),
                backend_name="speechbrain_ecapa",
                audio_path=Path("call.wav"),
                speaker_label="SPEAKER_00",
                spans=[{"start": 1.0, "end": 4.0, "text": "hello"}, {"start": 2.0, "end": 5.0, "text": "again"}],
                profiles_root=root,
                profiles=voice_profiles.load_profiles(root),
                auto_threshold=0.8,
                confirm_threshold=0.5,
                margin_threshold=0.2,
                top_k=2,
            )
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["best"]["person_id"], "Яна Ситникова")
        self.assertGreater(result["best"]["margin"], 0.2)
        self.assertEqual(len(result["score_matrix"]), 4)


if __name__ == "__main__":
    unittest.main()
