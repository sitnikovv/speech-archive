from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Protocol

from . import artifacts, io_utils, voice_profiles


class Embedder(Protocol):
    model_id: str

    def embed(self, audio_path: Path, start: float | None = None, end: float | None = None) -> list[float]:
        ...


class PyannoteEmbeddingBackend:
    def __init__(self, model_id: str = "pyannote/embedding", token: str | None = None, device: str | None = None):
        self.model_id = model_id
        try:
            from pyannote.audio import Inference, Model
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(f"pyannote.audio is not available: {exc}") from exc
        try:
            model = Model.from_pretrained(model_id, token=token)
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(f"failed to load pyannote embedding model {model_id}: {exc}") from exc
        if model is None:
            raise RuntimeError(f"failed to load pyannote embedding model {model_id}: model is None")
        torch_device = None
        if device:
            try:
                import torch
                torch_device = torch.device(device)
            except Exception as exc:  # pragma: no cover - environment dependent
                raise RuntimeError(f"invalid torch device {device}: {exc}") from exc
        self._inference = Inference(model, window="whole", device=torch_device)

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


class SpeechBrainEcapaBackend:
    def __init__(self, model_id: str = "speechbrain/spkrec-ecapa-voxceleb", device: str = "cpu", savedir: Path | None = None):
        self.model_id = model_id
        self.device = "cpu" if device == "auto" else device
        try:
            import torch
            from speechbrain.inference.speaker import EncoderClassifier
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(f"speechbrain ECAPA backend is not available: {exc}") from exc
        self._torch = torch
        try:
            self._classifier = EncoderClassifier.from_hparams(
                source=model_id,
                savedir=str(savedir) if savedir else None,
                run_opts={"device": self.device},
            )
        except Exception as exc:  # pragma: no cover - network/model dependent
            raise RuntimeError(f"failed to load SpeechBrain ECAPA model {model_id}: {exc}") from exc

    def embed(self, audio_path: Path, start: float | None = None, end: float | None = None) -> list[float]:
        wav = _load_audio_for_speechbrain(audio_path, start, end)
        try:
            with self._torch.no_grad():
                emb = self._classifier.encode_batch(wav.to(self.device)).squeeze().detach().cpu().float()
        except RuntimeError as exc:
            if self.device != "cpu" and "CUDNN" in str(exc).upper():  # pragma: no cover - CUDA runtime dependent
                self.device = "cpu"
                with self._torch.no_grad():
                    emb = self._classifier.encode_batch(wav.to("cpu")).squeeze().detach().cpu().float()
            else:
                raise
        emb = self._torch.nn.functional.normalize(emb, dim=0)
        return [float(v) for v in emb.tolist()]


def _load_audio_for_speechbrain(audio_path: Path, start: float | None, end: float | None):
    try:
        import torch
        import torchaudio
        import torchaudio.functional as F
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(f"torchaudio is not available for SpeechBrain ECAPA audio loading: {exc}") from exc
    wav, loaded_rate = torchaudio.load(str(audio_path))
    if start is not None or end is not None:
        rate = int(loaded_rate)
        frame_start = int(max(0.0, float(start or 0.0)) * rate)
        frame_end = wav.shape[-1] if end is None else int(max(float(start or 0.0) + 0.001, float(end)) * rate)
        wav = wav[..., frame_start:max(frame_start + 1, min(frame_end, wav.shape[-1]))]
    if wav.ndim == 1:
        wav = wav.unsqueeze(0)
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    if int(loaded_rate) != 16000:
        wav = F.resample(wav, int(loaded_rate), 16000)
    if wav.numel() == 0:
        wav = torch.zeros(1, 1)
    return wav


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


PYANNOTE_BACKEND_NAME = "pyannote_embedding"


def voice_embedding_cache_path(sample: Path, backend_name: str, model_id: str) -> Path:
    # data/voice_profiles/<person_id>/samples/enrolled/<sample>.mp3
    profile_dir = sample.parents[2]
    return (
        profile_dir
        / "voice_embeddings"
        / artifacts.safe_model_id(backend_name)
        / artifacts.safe_model_id(model_id)
        / f"{sample.stem}.json"
    )


def legacy_embedding_cache_path(sample: Path, model_id: str) -> Path:
    profile_dir = sample.parents[2]
    return profile_dir / "embeddings" / artifacts.safe_model_id(model_id) / f"{sample.stem}.json"


def legacy_backend_embedding_cache_path(sample: Path, backend_name: str, model_id: str) -> Path:
    profile_dir = sample.parents[2]
    return profile_dir / "voice_identification" / artifacts.safe_model_id(backend_name) / "embeddings" / artifacts.safe_model_id(model_id) / f"{sample.stem}.json"


def embedding_cache_path(sample: Path, model_id: str) -> Path:
    return voice_embedding_cache_path(sample, PYANNOTE_BACKEND_NAME, model_id)


def backend_embedding_cache_path(sample: Path, backend_name: str, model_id: str) -> Path:
    return voice_embedding_cache_path(sample, backend_name, model_id)


def cached_sample_embedding(embedder: Embedder, sample: Path, *, write_cache: bool = True) -> list[float]:
    cache = embedding_cache_path(sample, embedder.model_id)
    return cached_sample_embedding_at(cache, embedder, sample, write_cache=write_cache)


def cached_sample_embedding_for_backend(
    embedder: Embedder,
    sample: Path,
    backend_name: str,
    *,
    write_cache: bool = True,
) -> list[float]:
    cache = backend_embedding_cache_path(sample, backend_name, embedder.model_id)
    return cached_sample_embedding_at(cache, embedder, sample, write_cache=write_cache)


def cached_sample_embedding_at(cache: Path, embedder: Embedder, sample: Path, *, write_cache: bool = True) -> list[float]:
    sample_hash = io_utils.sha256_file(sample)
    if cache.exists():
        try:
            data = io_utils.read_json(cache)
        except Exception:
            data = None
        if (
            isinstance(data, dict)
            and data.get("model") == embedder.model_id
            and data.get("sample_file") == sample.name
            and data.get("sample_sha256") == sample_hash
            and isinstance(data.get("embedding"), list)
        ):
            return [float(x) for x in data["embedding"]]
    embedding = embedder.embed(sample)
    if write_cache:
        io_utils.write_json(cache, {
            "sample_id": sample.stem,
            "sample_file": sample.name,
            "sample_sha256": sample_hash,
            "model": embedder.model_id,
            "embedding": embedding,
            "created_at": io_utils.utc_now(),
        })
    return embedding


def representative_spans(segments: list[dict[str, Any]], speaker_label: str, max_count: int = 3) -> list[dict[str, Any]]:
    spans = [
        s for s in segments
        if s.get("speaker_label") == speaker_label
        and not ({"MIXED", "OVERLAP"} & set(s.get("uncertainty", [])))
        and 1.0 <= float(s.get("end", 0)) - float(s.get("start", 0)) <= 12.0
    ]
    return spans[:max_count]


def clean_representative_spans(
    segments: list[dict[str, Any]],
    speaker_label: str,
    max_count: int = 5,
    *,
    min_duration: float = 2.0,
    max_duration: float = 12.0,
    allow_uncertain_fallback: bool = True,
) -> list[dict[str, Any]]:
    def duration(span: dict[str, Any]) -> float:
        return float(span.get("end", 0)) - float(span.get("start", 0))

    def good_text(span: dict[str, Any]) -> bool:
        return len(str(span.get("text") or "").strip()) >= 3

    strict = [
        s for s in segments
        if s.get("speaker_label") == speaker_label
        and not set(s.get("uncertainty", []))
        and min_duration <= duration(s) <= max_duration
        and good_text(s)
    ]
    strict.sort(key=lambda s: (duration(s), len(str(s.get("text") or ""))), reverse=True)
    if strict or not allow_uncertain_fallback:
        return strict[:max_count]
    relaxed = [
        s for s in segments
        if s.get("speaker_label") == speaker_label
        and not ({"MIXED", "OVERLAP"} & set(s.get("uncertainty", [])))
        and 1.0 <= duration(s) <= max_duration
        and good_text(s)
    ]
    relaxed.sort(key=lambda s: (duration(s), len(str(s.get("text") or ""))), reverse=True)
    return relaxed[:max_count]


def match_speaker(
    *,
    embedder: Embedder,
    audio_path: Path,
    speaker_label: str,
    spans: list[dict[str, Any]],
    profiles_root: Path,
    profiles: list[dict[str, Any]],
    auto_threshold: float = 0.78,
    confirm_threshold: float = 0.65,
    write_embedding_cache: bool = True,
) -> dict[str, Any]:
    samples = voice_profiles.enrolled_samples(profiles_root)
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
            enrolled = cached_sample_embedding(embedder, sample, write_cache=write_embedding_cache)
            score = cosine_similarity(probe, enrolled)
            profile = profile_index.get(person_id, {})
            candidate_rows.append({
                "person_id": person_id,
                "full_name": profile.get("full_name"),
                "sample": str(sample),
                "score": score,
                "speaker_span": {"start": span.get("start"), "end": span.get("end"), "text": span.get("text")},
            })
    if not candidate_rows:
        return {"speaker_label": speaker_label, "status": "no_samples", "candidates": [], "best": None}
    candidate_rows.sort(key=lambda c: float(c["score"]), reverse=True)
    best = candidate_rows[0]
    if float(best["score"]) >= auto_threshold:
        status = "matched"
    elif float(best["score"]) >= confirm_threshold:
        status = "needs_confirmation"
    else:
        status = "no_match"
    return {"speaker_label": speaker_label, "status": status, "best": best, "candidates": candidate_rows[:10]}


def match_speaker_aggregated(
    *,
    embedder: Embedder,
    backend_name: str,
    audio_path: Path,
    speaker_label: str,
    spans: list[dict[str, Any]],
    profiles_root: Path,
    profiles: list[dict[str, Any]],
    auto_threshold: float = 0.65,
    confirm_threshold: float = 0.45,
    margin_threshold: float = 0.08,
    top_k: int = 3,
    write_embedding_cache: bool = True,
) -> dict[str, Any]:
    samples = voice_profiles.enrolled_samples(profiles_root)
    if not samples:
        return {"speaker_label": speaker_label, "status": "no_samples", "candidates": [], "best": None}
    if not spans:
        return {"speaker_label": speaker_label, "status": "no_candidate_span", "candidates": [], "best": None}

    profile_index = profile_by_person_id(profiles)
    score_matrix: list[dict[str, Any]] = []
    scores_by_person: dict[str, list[float]] = defaultdict(list)
    samples_by_person: dict[str, set[str]] = defaultdict(set)
    span_embeddings: list[tuple[dict[str, Any], list[float]]] = []
    for span in spans:
        probe = embedder.embed(audio_path, float(span["start"]), float(span["end"]))
        span_embeddings.append((span, probe))

    for span, probe in span_embeddings:
        for sample in samples:
            person_id = person_id_from_sample(sample)
            enrolled = cached_sample_embedding_for_backend(
                embedder,
                sample,
                backend_name,
                write_cache=write_embedding_cache,
            )
            score = cosine_similarity(probe, enrolled)
            scores_by_person[person_id].append(score)
            samples_by_person[person_id].add(str(sample))
            score_matrix.append({
                "person_id": person_id,
                "sample": str(sample),
                "sample_sha256": io_utils.sha256_file(sample),
                "score": score,
                "speaker_span": {"start": span.get("start"), "end": span.get("end"), "text": span.get("text")},
            })

    if not score_matrix:
        return {"speaker_label": speaker_label, "status": "no_samples", "candidates": [], "best": None}

    candidates: list[dict[str, Any]] = []
    for person_id, scores in scores_by_person.items():
        ordered = sorted(scores, reverse=True)
        selected = ordered[:max(1, min(top_k, len(ordered)))]
        aggregate = sum(selected) / len(selected)
        profile = profile_index.get(person_id, {})
        candidates.append({
            "person_id": person_id,
            "full_name": profile.get("full_name"),
            "aggregate_score": aggregate,
            "aggregation": f"top{len(selected)}_mean",
            "scores_seen": len(scores),
            "samples_seen": len(samples_by_person[person_id]),
            "top_scores": selected,
        })
    candidates.sort(key=lambda c: float(c["aggregate_score"]), reverse=True)
    best = candidates[0]
    second_score = float(candidates[1]["aggregate_score"]) if len(candidates) > 1 else -1.0
    margin = float(best["aggregate_score"]) - second_score
    best["margin"] = margin
    best["second_best_score"] = second_score if second_score >= 0 else None

    if float(best["aggregate_score"]) >= auto_threshold and margin >= margin_threshold:
        status = "matched"
    elif float(best["aggregate_score"]) >= confirm_threshold:
        status = "needs_confirmation"
    else:
        status = "no_match"
    return {
        "speaker_label": speaker_label,
        "status": status,
        "best": best,
        "candidates": candidates[:10],
        "probe_spans": [{"start": s.get("start"), "end": s.get("end"), "text": s.get("text"), "uncertainty": s.get("uncertainty", [])} for s in spans],
        "score_matrix": sorted(score_matrix, key=lambda r: float(r["score"]), reverse=True),
    }


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
