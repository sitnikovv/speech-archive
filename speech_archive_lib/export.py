from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def fmt_time(seconds: float) -> str:
    ms_total = int(round(float(seconds) * 1000))
    h, rem = divmod(ms_total, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def speaker_display(label: str, speakers: dict[str, Any], uncertainty: list[str] | None = None) -> str:
    if label in {"NO_SPEAKER", "MIXED", "OVERLAP"}:
        return label
    item = speakers.get("assignments", {}).get(label, {})
    name = item.get("name")
    if name and name not in {"UNKNOWN", "UNCERTAIN"}:
        return name
    if name:
        return f"{label}/{name}"
    if uncertainty:
        if "MIXED" in uncertainty or "OVERLAP" in uncertainty:
            return "MIXED/OVERLAP"
    return f"{label}/UNKNOWN" if label.startswith("SPEAKER_") else label


def render_transcript(merged: dict[str, Any], speakers: dict[str, Any], generated_at: str | None = None) -> str:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        f"Original mp3: {merged.get('source_mp3')}",
        f"ASR model: {merged.get('asr_model')}",
        f"Diarization model: {merged.get('diarization_model')}",
        f"Speakers mapping: {speakers.get('mapping_file', '<embedded>')}",
        f"Generated at: {generated_at}",
        "Warning: text is verbatim ASR; speaker names are a derived file-local layer.",
        "",
    ]
    for seg in merged.get("segments", []):
        sp = speaker_display(seg.get("speaker_label", "NO_SPEAKER"), speakers, seg.get("uncertainty", []))
        text = " ".join(str(seg.get("text", "")).split())
        lines.append(f"{fmt_time(float(seg.get('start', 0.0)))} | {sp} | {text}")
    return "\n".join(lines) + "\n"
