from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Protocol

from . import voice_profiles


class Embedder(Protocol):
    model_id: str

    def embed(self, audio_path: Path, start: float | None = None, end: float | None = None) -> list[float]:
        ...


class PyannoteEmbeddingBackend:
    def __init__(self, model_id: str = "pyannote/embedding", token: str | None = None, device: str | None = None):
        self.model_id = model_id
        try:
            from pyannote.audio import Inference
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(f"pyannote.audio is not available: {exc}") from exc
        kwargs: dict[str, Any] = {"window": "whole"}
        if token:
            kwargs["use_auth_token"] = token
        self._inference = Inference(model_id, **kwargs)
        if device:
            try:
                import torch
                self._inference.to(torch.device(device))
            except Exception as exc:  # pragma: no cover - environment dependent
                raise RuntimeError(f"failed to move pyannote embedding model to {device}: {exc}") from exc

    def embed(self, audio_path: Path, start: float | None = None, end: float | None = None) -> list[float]:
        if start is not None and end is not None:
            try:
                from pyannote.core import Segment
            except Exception as exc:  # pragma: no cover - environment dependent
                raise RuntimeError(f"pyannote.core is not available: {exc}") from exc
            vector = self._inference.crop(str(audio_path), Segment(float(start), float(end)))
        else:
            vector = self._inference(str(audio_path))
        return _flatten_vector(vector)


def _flatten_vector(vector: Any) -> list[float]:
    if hasattr(vector, "data"):
        vector = vector.data
    if hasattr(vector, "detach"):
        vector = vector.detach().cpu().numpy()
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    if isinstance(vector, (int, float)):
        return [float(vector)]
    result: list[float] = []
    stack = [vector]
    while stack:
        item = stack.pop(0)
        if isinstance(item, (list, tuple)):
            stack = list(item) + stack
        else:
            result.append(float(item))
    return result


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("embeddings must be non-empty and have the same length")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def person_id_from_sample(sample: Path) -> str:
    # data/voice_profiles/<person_id>/samples/enrolled/<sample>.mp3
    try:
        return sample.parents[2].name
    except IndexError:
        return "UNKNOWN"


def profile_by_person_id(profiles: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(p.get("person_id")): p for p in profiles if p.get("person_id")}


def representative_spans(segments: list[dict[str, Any]], speaker_label: str, max_count: int = 3) -> list[dict[str, Any]]:
    spans = [
        s for s in segments
        if s.get("speaker_label") == speaker_label
        and not ({"MIXED", "OVERLAP"} & set(s.get("uncertainty", [])))
        and 1.0 <= float(s.get("end", 0)) - float(s.get("start", 0)) <= 12.0
    ]
    return spans[:max_count]


def match_speaker(
    *,
    embedder: Embedder,
    audio_path: Path,
    speaker_label: str,
    spans: list[dict[str, Any]],
    profiles_root: Path,
    profiles: list[dict[str, Any]],
    phone_resolution: dict[str, Any],
    auto_threshold: float = 0.78,
    confirm_threshold: float = 0.65,
) -> dict[str, Any]:
    priority_ids = {str(p.get("person_id")) for p in phone_resolution.get("priority_profiles", []) if p.get("person_id")}
    samples = voice_profiles.enrolled_samples(profiles_root, priority_ids)
    if not samples:
        return {"speaker_label": speaker_label, "status": "no_samples", "candidates": [], "best": None}
    if not spans:
        return {"speaker_label": speaker_label, "status": "no_candidate_span", "candidates": [], "best": None}

    profile_index = profile_by_person_id(profiles)
    candidate_rows: list[dict[str, Any]] = []
    for span in spans:
        probe = embedder.embed(audio_path, float(span["start"]), float(span["end"]))
        for sample in samples:
            person_id = person_id_from_sample(sample)
            enrolled = embedder.embed(sample)
            score = cosine_similarity(probe, enrolled)
            profile = profile_index.get(person_id, {})
            candidate_rows.append({
                "person_id": person_id,
                "full_name": profile.get("full_name"),
                "sample": str(sample),
                "score": score,
                "speaker_span": {"start": span.get("start"), "end": span.get("end"), "text": span.get("text")},
                "priority_by_phone": person_id in priority_ids,
            })
    if not candidate_rows:
        return {"speaker_label": speaker_label, "status": "no_samples", "candidates": [], "best": None}
    candidate_rows.sort(key=lambda c: (bool(c.get("priority_by_phone")), float(c["score"])), reverse=True)
    best = candidate_rows[0]
    if float(best["score"]) >= auto_threshold:
        status = "matched"
    elif float(best["score"]) >= confirm_threshold:
        status = "needs_confirmation"
    else:
        status = "no_match"
    return {"speaker_label": speaker_label, "status": status, "best": best, "candidates": candidate_rows[:10]}


def assignments_from_voice_id(voice_id: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assignments: dict[str, dict[str, Any]] = {}
    for item in voice_id.get("speaker_matches", []):
        if item.get("status") != "matched":
            continue
        best = item.get("best") or {}
        label = item.get("speaker_label")
        if not label:
            continue
        assignments[label] = {
            "name": best.get("full_name") or best.get("person_id") or "UNKNOWN",
            "method": "voice_embedding_auto_match",
            "evidence": {
                "voice_identification_artifact": voice_id.get("artifact"),
                "person_id": best.get("person_id"),
                "sample": best.get("sample"),
                "score": best.get("score"),
                "status": item.get("status"),
                "speaker_span": best.get("speaker_span"),
            },
        }
    return assignments
