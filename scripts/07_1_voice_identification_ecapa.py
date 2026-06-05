#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from speech_archive_lib import artifacts, io_utils, voice_identity, voice_profiles


BACKEND_NAME = "speechbrain_ecapa"
DEFAULT_MODEL = "speechbrain/spkrec-ecapa-voxceleb"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Step 07_1: experimental SpeechBrain ECAPA voice identification.")
    ap.add_argument("merged")
    ap.add_argument("--audio", required=True, help="Audio artifact used for probe speaker spans, usually step 02 normalized WAV.")
    ap.add_argument("--voice-profiles-dir", default=str(ROOT / "data" / "voice_profiles"))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--auto-threshold", type=float, default=0.65)
    ap.add_argument("--confirm-threshold", type=float, default=0.45)
    ap.add_argument("--margin-threshold", type=float, default=0.08)
    ap.add_argument("--max-spans-per-speaker", type=int, default=5)
    ap.add_argument("--min-span-duration", type=float, default=2.0)
    ap.add_argument("--max-span-duration", type=float, default=12.0)
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--new-version", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    merged_p = Path(args.merged)
    audio = Path(args.audio)
    merged = io_utils.read_json(merged_p)
    source_mp3 = merged.get("source_mp3") or audio.name
    base = artifacts.base_name(Path(source_mp3))

    artifacts.ensure_dirs(ROOT)
    stage = artifacts.stage_dir(ROOT / "data", "07_1", "voice_identification_ecapa")
    stage.mkdir(parents=True, exist_ok=True)
    stem = f"{base}.voice-id.speechbrain-ecapa"
    existing = artifacts.latest_versioned_path(stage, stem, ".json") if not args.new_version else None
    if existing and existing.exists():
        print(existing)
        return 0

    profiles_root = Path(args.voice_profiles_dir)
    profiles_root.mkdir(parents=True, exist_ok=True)
    call_meta = voice_profiles.parse_call_filename(source_mp3)
    profiles = voice_profiles.load_profiles(profiles_root)
    phone_resolution = voice_profiles.resolve_phone_profiles(profiles, call_meta.get("phone_e164"), call_meta.get("call_datetime"))
    labels = sorted({s.get("speaker_label") for s in merged.get("segments", []) if str(s.get("speaker_label", "")).startswith("SPEAKER_")})

    backend_status = "ok"
    backend_error = None
    embedder = None
    try:
        embedder = voice_identity.SpeechBrainEcapaBackend(
            args.model,
            device=args.device,
            savedir=ROOT / "data" / "models-cache" / "speechbrain" / artifacts.safe_model_id(args.model),
        )
    except Exception as exc:
        backend_status = "unavailable"
        backend_error = str(exc)

    speaker_matches = []
    if embedder is not None:
        for label in labels:
            spans = voice_identity.clean_representative_spans(
                merged.get("segments", []),
                label,
                args.max_spans_per_speaker,
                min_duration=args.min_span_duration,
                max_duration=args.max_span_duration,
            )
            try:
                speaker_matches.append(voice_identity.match_speaker_aggregated(
                    embedder=embedder,
                    backend_name=BACKEND_NAME,
                    audio_path=audio,
                    speaker_label=label,
                    spans=spans,
                    profiles_root=profiles_root,
                    profiles=profiles,
                    auto_threshold=args.auto_threshold,
                    confirm_threshold=args.confirm_threshold,
                    margin_threshold=args.margin_threshold,
                    top_k=args.top_k,
                ))
            except Exception as exc:
                speaker_matches.append({"speaker_label": label, "status": "error", "error": str(exc), "candidates": [], "best": None})
    else:
        for label in labels:
            speaker_matches.append({
                "speaker_label": label,
                "status": "backend_unavailable",
                "error": backend_error,
                "enrolled_samples_seen": len(voice_profiles.enrolled_samples(profiles_root)),
                "candidates": [],
                "best": None,
            })

    v = artifacts.next_version(stage, stem, ".json")
    out = artifacts.versioned_path(stage, stem, ".json", v)
    man = artifacts.manifest_for(out)
    data = {
        "artifact": str(out),
        "stage": "07_1_voice_identification_ecapa",
        "source_mp3": source_mp3,
        "scope": "file-local",
        "created_at": io_utils.utc_now(),
        "source_metadata": call_meta,
        "voice_profiles_dir": str(profiles_root),
        "profile_backend_storage": "<profile>/voice_embeddings/<backend>/<model>/<sample>.json",
        "phone_resolution": phone_resolution,
        "backend": {"name": BACKEND_NAME, "model": args.model, "status": backend_status, "error": backend_error},
        "thresholds": {"auto": args.auto_threshold, "confirm": args.confirm_threshold, "margin": args.margin_threshold},
        "aggregation": {"probe_spans_per_speaker": args.max_spans_per_speaker, "top_k": args.top_k},
        "speaker_matches": speaker_matches,
    }
    io_utils.write_json(out, data)
    io_utils.write_json(man, {
        "stage": "07_1_voice_identification_ecapa",
        "script": "scripts/07_1_voice_identification_ecapa.py",
        "input_artifacts": [
            {"path": str(merged_p), "sha256": io_utils.sha256_file(merged_p)},
            {"path": str(audio), "sha256": io_utils.sha256_file(audio)},
        ],
        "output_artifacts": [{"path": str(out), "sha256": io_utils.sha256_file(out)}],
        "backend": {"name": BACKEND_NAME, "model": args.model, "status": backend_status},
        "created_at": io_utils.utc_now(),
    })
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
