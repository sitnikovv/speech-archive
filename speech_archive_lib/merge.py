from __future__ import annotations

from typing import Any


def overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def merge_segments(asr_segments: list[dict[str, Any]], diarization_segments: list[dict[str, Any]], mixed_threshold: float = 0.20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for seg in asr_segments:
        start, end = float(seg["start"]), float(seg["end"])
        dur = max(0.001, end - start)
        overlaps = []
        totals: dict[str, float] = {}
        for d in diarization_segments:
            ov = overlap(start, end, float(d["start"]), float(d["end"]))
            if ov > 0:
                speaker = d.get("speaker", "NO_SPEAKER")
                overlaps.append({"diarization_id": d.get("id"), "speaker": speaker, "start": d["start"], "end": d["end"], "overlap": ov})
                totals[speaker] = totals.get(speaker, 0.0) + ov
        uncertainty: list[str] = []
        if not totals:
            label = "NO_SPEAKER"
            uncertainty.append("NO_SPEAKER")
        else:
            label = max(totals.items(), key=lambda kv: kv[1])[0]
            if len(totals) > 1:
                uncertainty.append("MIXED")
            covered = sum(totals.values()) / dur
            if covered < 0.5:
                uncertainty.append("UNCERTAIN")
            if any(v / dur >= mixed_threshold for sp, v in totals.items() if sp != label):
                if "OVERLAP" not in uncertainty:
                    uncertainty.append("OVERLAP")
        out.append({
            "id": seg.get("id"), "start": start, "end": end, "speaker_label": label,
            "speaker_name": None, "text": seg.get("text", ""), "uncertainty": uncertainty,
            "overlaps": overlaps, "asr_segment_id": seg.get("id"),
        })
    return out
