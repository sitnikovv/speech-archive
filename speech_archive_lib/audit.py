from __future__ import annotations

from typing import Any


def audit_candidates(merged: dict[str, Any], speakers: dict[str, Any]) -> dict[str, Any]:
    # First version: evidence-preserving placeholder. It creates a valid candidates file
    # and never mutates ASR/diarization/speaker mapping artifacts.
    candidates: list[dict[str, Any]] = []
    prev = None
    for seg in merged.get("segments", []):
        un = set(seg.get("uncertainty", []))
        if un & {"MIXED", "OVERLAP", "UNCERTAIN"}:
            candidates.append({
                "id": len(candidates) + 1,
                "start": seg.get("start"), "end": seg.get("end"),
                "current_speaker": seg.get("speaker_label"),
                "reason": "segment has uncertainty markers: " + ",".join(sorted(un)),
                "confidence": 0.5, "status": "pending", "segment_id": seg.get("id"),
            })
        if prev and prev.get("speaker_label") != seg.get("speaker_label"):
            text = str(seg.get("text", "")).strip().lower()
            if text.startswith(("и ", "а ", "ну ", "вот ", "то ")) and len(text) < 80:
                candidates.append({
                    "id": len(candidates) + 1,
                    "start": seg.get("start"), "end": seg.get("end"),
                    "current_speaker": seg.get("speaker_label"),
                    "reason": "short continuation-like phrase after speaker change",
                    "confidence": 0.35, "status": "pending", "segment_id": seg.get("id"),
                })
        prev = seg
    return {"status": "heuristic_placeholder", "candidates": candidates}
