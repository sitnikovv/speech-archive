import json
import tempfile
import unittest
from pathlib import Path

from speech_archive_lib import artifacts, io_utils, merge, export


class ArtifactTests(unittest.TestCase):
    def test_safe_model_id_and_paths_are_deterministic(self):
        base = "Яна Ситникова(0079263717233)_20260509182759"
        self.assertEqual(artifacts.safe_model_id("Systran/faster-whisper-large-v3"), "Systran_faster-whisper-large-v3")
        paths = artifacts.paths_for(Path("data"), base, "Systran/faster-whisper-large-v3", "pyannote/speaker-diarization-3.1")
        self.assertEqual(str(paths.asr_segments), f"data/artifacts/04_asr/{base}.asr.Systran_faster-whisper-large-v3.segments.v1.json")
        self.assertEqual(str(paths.diarization_segments), f"data/artifacts/05_diarization/{base}.diarization.pyannote_speaker-diarization-3.1.segments.v1.json")

    def test_atomic_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nested" / "file.json"
            io_utils.write_json(p, {"a": 1})
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"a": 1})


class MergeTests(unittest.TestCase):
    def test_assigns_speaker_by_largest_overlap_and_marks_mixed(self):
        asr_segments = [{"id": 1, "start": 0.0, "end": 10.0, "text": "текст"}]
        diar_segments = [
            {"id": 1, "start": 0.0, "end": 7.0, "speaker": "SPEAKER_00"},
            {"id": 2, "start": 7.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]
        merged = merge.merge_segments(asr_segments, diar_segments)
        self.assertEqual(merged[0]["speaker_label"], "SPEAKER_00")
        self.assertIn("MIXED", merged[0]["uncertainty"])
        self.assertEqual(len(merged[0]["overlaps"]), 2)

    def test_no_overlap_becomes_no_speaker(self):
        merged = merge.merge_segments(
            [{"id": 1, "start": 20.0, "end": 22.0, "text": "тишина"}],
            [{"id": 1, "start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"}],
        )
        self.assertEqual(merged[0]["speaker_label"], "NO_SPEAKER")
        self.assertIn("NO_SPEAKER", merged[0]["uncertainty"])


class ExportTests(unittest.TestCase):
    def test_transcript_line_format_uses_names_and_hhmmssmmm(self):
        merged = {
            "source_mp3": "call.mp3",
            "asr_model": "asr",
            "diarization_model": "dia",
            "segments": [{"start": 83.45, "end": 90.0, "speaker_label": "SPEAKER_00", "text": "привет", "uncertainty": []}],
        }
        speakers = {"assignments": {"SPEAKER_00": {"name": "Яна"}}}
        text = export.render_transcript(merged, speakers, generated_at="2026-06-03T00:00:00")
        self.assertIn("Original mp3: call.mp3", text)
        self.assertIn("00:01:23.450 | Яна | привет", text)


if __name__ == "__main__":
    unittest.main()
