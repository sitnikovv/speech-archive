import unittest
from pathlib import Path
from unittest import mock

from speech_archive_lib import playback


class PlaybackTests(unittest.TestCase):
    def test_ffplay_command_targets_time_range_without_persistent_sample_file(self):
        cmd = playback.build_play_command(Path("audio.wav"), 12.345, 15.678, player="ffplay")
        self.assertEqual(cmd[:3], ["ffplay", "-nodisp", "-autoexit"])
        self.assertIn("-ss", cmd)
        self.assertIn("12.345", cmd)
        self.assertIn("-t", cmd)
        self.assertIn("3.333", cmd)
        self.assertEqual(cmd[-1], "audio.wav")

    def test_mpv_command_targets_time_range_without_persistent_sample_file(self):
        cmd = playback.build_play_command(Path("audio.wav"), 1.0, 2.25, player="mpv")
        self.assertIn("--start=1.000", cmd)
        self.assertIn("--length=1.250", cmd)
        self.assertEqual(cmd[-1], "audio.wav")

    def test_invalid_range_is_rejected(self):
        with self.assertRaises(ValueError):
            playback.build_play_command(Path("audio.wav"), 5.0, 5.0, player="ffplay")
    def test_play_segment_does_not_share_prompt_stdin_with_player(self):
        with mock.patch("speech_archive_lib.playback.build_play_command", return_value=["player", "audio.wav"]), \
             mock.patch("speech_archive_lib.playback.subprocess.run") as run:
            self.assertTrue(playback.play_segment(Path("audio.wav"), 1.0, 2.0, player="ffplay"))
        run.assert_called_once_with(["player", "audio.wav"], check=False, stdin=playback.subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
