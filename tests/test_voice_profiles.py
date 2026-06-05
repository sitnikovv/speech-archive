import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from speech_archive_lib import voice_profiles


class VoiceProfileTests(unittest.TestCase):
    def test_parse_call_filename_extracts_name_phone_and_datetime(self):
        meta = voice_profiles.parse_call_filename("Яна Ситникова(0079263717233)_20260509182759.input.v1.mp3")
        self.assertEqual(meta["display_name"], "Яна Ситникова")
        self.assertEqual(meta["phone_e164"], "+79263717233")
        self.assertEqual(meta["call_datetime"], "2026-05-09T18:27:59")

    def test_phone_without_dates_is_always_valid(self):
        profiles = [{"person_id": "yana", "phones": [{"e164": "+79991234567"}]}]
        result = voice_profiles.resolve_phone_profiles(profiles, "+79991234567", "2026-05-09T18:27:59")
        self.assertEqual(result["status"], "matched")

    def test_date_matching_prefers_profile_valid_at_call_time(self):
        profiles = [
            {"person_id": "old", "phones": [{"e164": "+79991234567", "valid_to": "2024-12-31"}]},
            {"person_id": "current", "phones": [{"e164": "+79991234567", "valid_from": "2026-01-01", "valid_to": "2026-12-31"}]},
        ]
        result = voice_profiles.resolve_phone_profiles(profiles, "+79991234567", "2026-05-09T18:27:59")
        self.assertEqual([p["person_id"] for p in result["priority_profiles"]], ["current"])

    def test_phone_seen_but_no_valid_period_is_conflict(self):
        profiles = [{"person_id": "old", "phones": [{"e164": "+79991234567", "valid_to": "2024-12-31"}]}]
        result = voice_profiles.resolve_phone_profiles(profiles, "+79991234567", "2026-05-09T18:27:59")
        self.assertEqual(result["status"], "conflict")

    def test_create_profile_alias_and_phone(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "voice_profiles"
            profile = voice_profiles.create_profile(root, "Яна Ситникова", aliases=["Яна"])
            self.assertTrue(voice_profiles.alias_exists(profile, "Яна"))
            self.assertIsNone(voice_profiles.add_alias(profile, "Яна"))
            added = voice_profiles.add_phone_binding(profile, "+79991234567", observed_at="2026-05-09T18:27:59")
            self.assertEqual(added["valid_from"], None)
            self.assertEqual(added["valid_to"], None)
            loaded = voice_profiles.load_profiles(root)
            self.assertEqual(voice_profiles.find_profiles_by_name_or_alias(loaded, "Яна")[0]["person_id"], profile["person_id"])
            self.assertTrue(voice_profiles.phone_valid_for_profile(loaded[0], "+79991234567", "2030-01-01T00:00:00"))

    def test_find_source_mp3_uses_latest_input_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            stage = root / "data" / "artifacts" / "01_input"
            stage.mkdir(parents=True)
            (stage / "call.input.v1.mp3").write_bytes(b"old")
            (stage / "call.input.v2.mp3").write_bytes(b"new")
            self.assertEqual(voice_profiles.find_source_mp3(root, "call.mp3").name, "call.input.v2.mp3")

    def test_save_enrolled_mp3_sample_writes_mp3_and_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "voice_profiles"
            source = Path(d) / "source.mp3"
            source.write_bytes(b"fake")
            profile = voice_profiles.create_profile(root, "Яна Ситникова", aliases=["Яна"])
            with mock.patch("speech_archive_lib.voice_profiles.subprocess.run") as run:
                result = voice_profiles.save_enrolled_mp3_sample(
                    profile=profile,
                    source_mp3_path=source,
                    source_mp3="call.mp3",
                    speaker_label="SPEAKER_00",
                    span={"start": 1.0, "end": 2.0, "text": "привет"},
                    call_meta={"phone_e164": "+79991234567"},
                )
            self.assertTrue(result["sample"].endswith(".mp3"))
            self.assertTrue(Path(result["sample"]).name.startswith("Яна_Ситникова.sample."))
            self.assertNotIn("call", Path(result["sample"]).name)
            self.assertNotIn("SPEAKER_00", Path(result["sample"]).name)
            meta = json.loads(Path(result["metadata"]).read_text(encoding="utf-8"))
            self.assertEqual(meta["status"], "enrolled_manual_voice_confirmation")
            self.assertEqual(meta["person_id"], profile["person_id"])
            self.assertNotIn("source_audio", meta)
            self.assertNotIn("source_mp3", meta)
            self.assertNotIn("call_metadata", meta)
            self.assertNotIn("speaker_label", meta)
            self.assertNotIn("start", meta)
            self.assertNotIn("end", meta)
            self.assertFalse(Path(meta["audio_file"]).is_absolute())
            run.assert_called_once()
            self.assertIn("-c", run.call_args.args[0])
            self.assertIn("copy", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
