#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from speech_archive_lib import artifacts, io_utils

ASR_PARAMETERS: dict[str, Any] = {
    "language": "ru",
    "vad_filter": True,
    "beam_size": 10,
    "word_timestamps": True,
    "condition_on_previous_text": False,
}


def clean_base(path: Path) -> str:
    base = artifacts.base_name(path)
    if ".audio.normalized.v" in base:
        return base.split(".audio.normalized.v")[0]
    return base


def transcribe_faster_whisper(audio: Path, model_id: str):
    from faster_whisper import WhisperModel

    model_dir = ROOT / "data" / "models-cache" / "huggingface" / "Systran__faster-whisper-large-v3"
    last_error = None
    model = None
    for device, compute_type in [("cuda", "float16"), ("cpu", "int8")]:
        try:
            model = WhisperModel(str(model_dir), device=device, compute_type=compute_type, local_files_only=True)
            break
        except Exception as exc:
            last_error = exc
    if model is None:
        raise last_error

    segments, info = model.transcribe(str(audio), **ASR_PARAMETERS)
    raw_segments = []
    norm = []
    for i, segment in enumerate(segments, 1):
        words = [
            {
                "start": word.start,
                "end": word.end,
                "word": word.word,
                "probability": getattr(word, "probability", None),
            }
            for word in (getattr(segment, "words", None) or [])
        ]
        item = {
            "id": i,
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
            "avg_logprob": getattr(segment, "avg_logprob", None),
            "no_speech_prob": getattr(segment, "no_speech_prob", None),
            "words": words,
        }
        raw_segments.append(item)
        norm.append(
            {
                "id": i,
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text.strip(),
                "confidence": None,
                "raw_ref": i,
                "words": words,
            }
        )
    raw = {
        "model": model_id,
        "language": getattr(info, "language", "ru"),
        "duration": getattr(info, "duration", None),
        "parameters": ASR_PARAMETERS,
        "segments": raw_segments,
    }
    return raw, norm


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("--smoke-report")
    parser.add_argument("--model")
    parser.add_argument("--new-version", action="store_true")
    args = parser.parse_args()

    audio = Path(args.audio)
    base = clean_base(audio)
    model_id = args.model
    if model_id is None and args.smoke_report:
        model_id = io_utils.read_json(Path(args.smoke_report)).get("selected_asr_model")
    model_id = model_id or "Systran/faster-whisper-large-v3"
    safe = artifacts.safe_model_id(model_id)

    artifacts.ensure_dirs(ROOT)
    stage = artifacts.stage_dir(ROOT / "data", "04", "asr")
    stem = f"{base}.asr.{safe}"
    existing = artifacts.latest_versioned_path(stage, stem + ".segments", ".json") if not args.new_version else None
    if existing and existing.exists():
        print(existing)
        return 0
    if model_id != "Systran/faster-whisper-large-v3":
        raise SystemExit(f"ASR model not implemented yet: {model_id}")

    version = artifacts.next_version(stage, stem + ".segments", ".json")
    rawp = artifacts.versioned_path(stage, stem + ".raw", ".json", version)
    segp = artifacts.versioned_path(stage, stem + ".segments", ".json", version)
    man = artifacts.versioned_path(stage, stem, ".manifest.json", version)
    raw, norm = transcribe_faster_whisper(audio, model_id)

    io_utils.write_json(
        rawp,
        {
            "artifact": str(rawp),
            "stage": "04_asr",
            "source_audio": str(audio),
            "created_at": io_utils.utc_now(),
            **raw,
        },
    )
    io_utils.write_json(
        segp,
        {
            "artifact": str(segp),
            "stage": "04_asr",
            "source_mp3": f"{base}.mp3",
            "source_audio": str(audio),
            "model": model_id,
            "language": "ru",
            "parameters": ASR_PARAMETERS,
            "segments": norm,
        },
    )
    inputs = [{"path": str(audio), "sha256": io_utils.sha256_file(audio)}]
    if args.smoke_report:
        smoke_report = Path(args.smoke_report)
        inputs.append({"path": str(smoke_report), "sha256": io_utils.sha256_file(smoke_report)})
    io_utils.write_json(
        man,
        {
            "stage": "04_asr",
            "script": "scripts/04_transcribe.py",
            "input_artifacts": inputs,
            "output_artifacts": [
                {"path": str(rawp), "sha256": io_utils.sha256_file(rawp)},
                {"path": str(segp), "sha256": io_utils.sha256_file(segp)},
            ],
            "model": model_id,
            "parameters": ASR_PARAMETERS,
            "created_at": io_utils.utc_now(),
        },
    )
    print(segp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
