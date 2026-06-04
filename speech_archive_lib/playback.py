from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def build_play_command(audio: Path, start: float, end: float, player: str = "auto") -> list[str]:
    start = float(start)
    end = float(end)
    duration = end - start
    if duration <= 0:
        raise ValueError(f"invalid playback range: start={start}, end={end}")

    if player == "auto":
        player = detect_player()
    if player == "ffplay":
        return [
            "ffplay",
            "-nodisp",
            "-autoexit",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            str(audio),
        ]
    if player == "mpv":
        return ["mpv", "--no-video", f"--start={start:.3f}", f"--length={duration:.3f}", str(audio)]
    if player == "none":
        return []
    raise ValueError(f"unsupported player: {player}")


def detect_player() -> str:
    for candidate in ("ffplay", "mpv"):
        if shutil.which(candidate):
            return candidate
    return "none"


def play_segment(audio: Path, start: float, end: float, player: str = "auto") -> bool:
    cmd = build_play_command(audio, start, end, player=player)
    if not cmd:
        return False
    # Keep the media player away from the interactive prompt stdin.
    # ffplay/mpv can read terminal controls from stdin; the next Python input()
    # must receive only the user's answer to our prompt.
    subprocess.run(cmd, check=False, stdin=subprocess.DEVNULL)
    return True
