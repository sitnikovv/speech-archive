#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from speech_archive_lib import artifacts, io_utils


def required_specs(base: str) -> list[dict]:
    data = ROOT / "data"
    fw = "Systran_faster-whisper-large-v3"
    dia = "pyannote_speaker-diarization-3.1"
    raw_specs = [
        ("01_input_mp3", "01", "input", f"{base}.input", ".mp3"),
        ("01_input_manifest", "01", "input", f"{base}.input", ".manifest.json"),
        ("02_audio_wav", "02", "audio", f"{base}.audio.normalized", ".wav"),
        ("02_audio_manifest", "02", "audio", f"{base}.audio.normalized", ".manifest.json"),
        ("03_asr_smoke", "03", "asr_smoke", f"{base}.asr-smoke", ".json"),
        ("04_asr_raw", "04", "asr", f"{base}.asr.{fw}.raw", ".json"),
        ("04_asr_segments", "04", "asr", f"{base}.asr.{fw}.segments", ".json"),
        ("05_diarization_raw", "05", "diarization", f"{base}.diarization.{dia}.raw", ".json"),
        ("05_diarization_segments", "05", "diarization", f"{base}.diarization.{dia}.segments", ".json"),
        ("06_merge", "06", "merge", f"{base}.merge.{fw}.{dia}", ".json"),
        ("07_voice_identification", "07", "voice_identification", f"{base}.voice-id.pyannote-embedding", ".json"),
        ("08_speakers", "08", "speakers", f"{base}.speakers.manual", ".json"),
        ("09_transcript", "09", "transcript", f"{base}.transcript.with-names", ".txt"),
        ("10_role_consistency_review", "10", "role_consistency_review", f"{base}.role-consistency-review.hermes", ".json"),
        ("11_voice_profile_embeddings", "11", "voice_profile_embeddings", "voice-profile-embeddings", ".json"),
    ]
    specs = []
    for label, number, name, stem, suffix in raw_specs:
        stage = artifacts.stage_dir(data, number, name)
        specs.append({
            "label": label,
            "stage_dir": stage,
            "stem": stem,
            "suffix": suffix,
            "path": artifacts.latest_versioned_path(stage, stem, suffix),
            "expected": str(stage / f"{stem}.v*{suffix}"),
        })
    return specs


def valid_json(path: Path) -> tuple[bool, str]:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True, ""
    except Exception as e:
        return False, str(e)


def validate_json_shape(label: str, data: dict) -> list[str]:
    errors: list[str] = []
    if label.endswith("_manifest"):
        if not data.get("stage"):
            errors.append("manifest has no stage")
        if not data.get("output_artifacts") and not data.get("artifact"):
            errors.append("manifest has no output_artifacts/artifact reference")
        return errors
    if label in {"03_asr_smoke"} and "selected_asr_model" not in data:
        errors.append("ASR smoke report has no selected_asr_model")
    if label in {"04_asr_raw", "04_asr_segments", "05_diarization_segments", "06_merge"} and not isinstance(data.get("segments"), list):
        errors.append("artifact has no segments list")
    if label == "05_diarization_raw" and not (isinstance(data.get("tracks"), list) or data.get("rttm")):
        errors.append("raw diarization has no tracks/rttm")
    if label == "07_voice_identification" and not isinstance(data.get("speaker_matches"), list):
        errors.append("voice-id artifact has no speaker_matches list")
    if label == "08_speakers" and not isinstance(data.get("assignments"), dict):
        errors.append("speakers artifact has no assignments object")
    if label == "10_role_consistency_review":
        review = data.get("review")
        if not isinstance(review, dict) or not isinstance(review.get("candidates"), list):
            errors.append("role review has no review.candidates list")
    if label == "11_voice_profile_embeddings" and data.get("stage") != "11_voice_profile_embeddings":
        errors.append("voice profile embeddings report has wrong/missing stage")
    return errors


def validate_artifact(label: str, path: Path) -> tuple[str, str | None]:
    if path.suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return "INVALID_JSON", str(exc)
        if isinstance(data, dict):
            shape_errors = validate_json_shape(label, data)
            if shape_errors:
                return "INVALID_SCHEMA", "; ".join(shape_errors)
        return "OK", None
    if path.suffix == ".txt":
        if not path.read_text(encoding="utf-8").strip():
            return "EMPTY", None
        return "OK", None
    if path.stat().st_size <= 0:
        return "EMPTY", None
    return "OK", None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base_or_mp3")
    ap.add_argument("--new-version", action="store_true")
    args = ap.parse_args()

    base = artifacts.base_name(Path(args.base_or_mp3))
    artifacts.ensure_dirs(ROOT)
    errors: list[str] = []
    checked: list[dict] = []
    for spec in required_specs(base):
        p = spec["path"]
        if p is None:
            errors.append(f"MISSING {spec['label']}: expected {spec['expected']}")
            continue
        if not p.exists():
            errors.append(f"MISSING {spec['label']}: {p}")
            continue
        status, err = validate_artifact(spec["label"], p)
        item = {"label": spec["label"], "path": str(p), "sha256": io_utils.sha256_file(p), "status": status}
        if err:
            item["error"] = err
        if status != "OK":
            errors.append(f"{status} {spec['label']}: {p}" + (f" ({err})" if err else ""))
        checked.append(item)

    stage = artifacts.stage_dir(ROOT / "data", "99", "check")
    stem = f"{base}.pipeline-check"
    existing = artifacts.latest_versioned_path(stage, stem, ".json")
    if existing and existing.exists() and not args.new_version:
        try:
            previous = io_utils.read_json(existing)
            if previous.get("checked_artifacts") == checked and previous.get("errors") == errors:
                print("OK" if not errors else "\n".join(errors))
                print(existing)
                return 0 if not errors else 2
        except Exception:
            pass
    v = artifacts.next_version(stage, stem, ".json")
    out = artifacts.versioned_path(stage, stem, ".json", v)
    data = {
        "artifact": str(out),
        "stage": "99_check",
        "script": "scripts/99_check_pipeline_outputs.py",
        "status": "OK" if not errors else "FAILED",
        "checked_artifacts": checked,
        "errors": errors,
        "created_at": io_utils.utc_now(),
    }
    io_utils.write_json(out, data)
    print("OK" if not errors else "\n".join(errors))
    print(out)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
