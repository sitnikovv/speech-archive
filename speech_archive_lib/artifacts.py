from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


def base_name(path: Path) -> str:
    return path.name[:-4] if path.name.lower().endswith(".mp3") else path.stem


def safe_model_id(model_id: str) -> str:
    s = model_id.replace("/", "_").replace(" ", "_")
    return re.sub(r"[^0-9A-Za-zА-Яа-яЁё._-]+", "_", s).strip("_")


def hf_flat_model_id(model_id: str) -> str:
    return model_id.replace("/", "__")


def hf_snapshot_model_id(model_id: str) -> str:
    return "models--" + model_id.replace("/", "--")


def model_cache_candidates(data_dir: Path, model_id: str) -> list[Path]:
    return [
        data_dir / "models-cache" / "huggingface" / hf_flat_model_id(model_id),
        data_dir / "models-cache" / "huggingface" / hf_snapshot_model_id(model_id),
        data_dir / "models-cache" / "faster-whisper" / hf_snapshot_model_id(model_id),
    ]


@dataclass(frozen=True)
class ArtifactPaths:
    input_mp3: Path
    input_manifest: Path
    audio_wav: Path
    audio_manifest: Path
    asr_smoke_report: Path
    asr_raw: Path
    asr_segments: Path
    diarization_raw: Path
    diarization_segments: Path
    merged: Path
    speakers: Path
    transcript: Path
    audit_candidates: Path


def paths_for(data_dir: Path, base: str, asr_model: str = "selected", diar_model: str = "pyannote/speaker-diarization-3.1") -> ArtifactPaths:
    asr = safe_model_id(asr_model)
    dia = safe_model_id(diar_model)
    return ArtifactPaths(
        input_mp3=data_dir / "input" / "raw" / f"{base}.mp3",
        input_manifest=data_dir / "input" / "raw" / f"{base}.input.json",
        audio_wav=data_dir / "work" / "audio" / f"{base}.normalized.wav",
        audio_manifest=data_dir / "work" / "audio" / f"{base}.normalized.json",
        asr_smoke_report=data_dir / "work" / "asr" / f"{base}.asr-smoke-report.json",
        asr_raw=data_dir / "work" / "asr" / f"{base}.asr.raw.{asr}.json",
        asr_segments=data_dir / "work" / "asr" / f"{base}.asr.segments.{asr}.json",
        diarization_raw=data_dir / "work" / "diarization" / f"{base}.diarization.raw.{dia}.json",
        diarization_segments=data_dir / "work" / "diarization" / f"{base}.diarization.segments.{dia}.json",
        merged=data_dir / "work" / "merge" / f"{base}.merged.{asr}.{dia}.json",
        speakers=data_dir / "work" / "speakers" / f"{base}.speakers.json",
        transcript=data_dir / "exports" / f"{base}.transcript.with-names.txt",
        audit_candidates=data_dir / "work" / "audit" / f"{base}.audit.candidates.json",
    )


def stage_dir(data_dir: Path, number: str, name: str) -> Path:
    return data_dir / "artifacts" / f"{number}_{name}"


def versioned_path(stage_directory: Path, stem_without_version: str, suffix: str, version: int) -> Path:
    if not suffix.startswith("."):
        suffix = "." + suffix
    return stage_directory / f"{stem_without_version}.v{version}{suffix}"


def next_version(stage_directory: Path, stem_without_version: str, suffix: str) -> int:
    if not suffix.startswith("."):
        suffix = "." + suffix
    max_v = 0
    if stage_directory.exists():
        for p in stage_directory.glob(f"{stem_without_version}.v*{suffix}"):
            middle = p.name.removeprefix(stem_without_version + ".v").removesuffix(suffix)
            if middle.isdigit():
                max_v = max(max_v, int(middle))
    return max_v + 1


def latest_versioned_path(stage_directory: Path, stem_without_version: str, suffix: str) -> Path | None:
    v = next_version(stage_directory, stem_without_version, suffix) - 1
    if v < 1:
        return None
    return versioned_path(stage_directory, stem_without_version, suffix, v)


def manifest_for(artifact_path: Path) -> Path:
    if artifact_path.suffix:
        return artifact_path.with_name(artifact_path.name[: -len(artifact_path.suffix)] + ".manifest.json")
    return artifact_path.with_name(artifact_path.name + ".manifest.json")


def ensure_dirs(root: Path) -> list[Path]:
    dirs = [
        root / "scripts", root / "speech_archive_lib",
        stage_dir(root / "data", "00", "doctor"),
        stage_dir(root / "data", "01", "input"),
        stage_dir(root / "data", "02", "audio"),
        stage_dir(root / "data", "03", "asr_smoke"),
        stage_dir(root / "data", "04", "asr"),
        stage_dir(root / "data", "05", "diarization"),
        stage_dir(root / "data", "06", "merge"),
        stage_dir(root / "data", "07", "voice_identification"),
        stage_dir(root / "data", "08", "speakers"),
        stage_dir(root / "data", "09", "transcript"),
        stage_dir(root / "data", "10", "role_consistency_review"),
        stage_dir(root / "data", "11", "voice_profile_embeddings"),
        stage_dir(root / "data", "99", "check"),
        root / "data" / "voice_profiles",
        root / "data" / "state",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    return dirs
