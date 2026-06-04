#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from speech_archive_lib import artifacts, io_utils, voice_identity, voice_profiles


def read_token(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8").strip() or None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Step 07: auto-identify file-local speakers by voice profile embeddings.")
    ap.add_argument("merged")
    ap.add_argument("--audio", required=True, help="Audio artifact used for probe speaker spans, usually step 02 normalized WAV or step 01 input MP3.")
    ap.add_argument("--voice-profiles-dir", default=str(ROOT / "data" / "voice_profiles"))
    ap.add_argument("--model", default="pyannote/embedding")
    ap.add_argument("--token-file", default=str(ROOT / "token.txt"))
    ap.add_argument("--device", default=None, help="Optional torch device for pyannote embedding, e.g. cuda or cpu.")
    ap.add_argument("--auto-threshold", type=float, default=0.78)
    ap.add_argument("--confirm-threshold", type=float, default=0.65)
    ap.add_argument("--max-spans-per-speaker", type=int, default=3)
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
    stage = artifacts.stage_dir(ROOT / "data", "07", "voice_identification")
    stem = f"{base}.voice-id.pyannote-embedding"
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
        embedder = voice_identity.PyannoteEmbeddingBackend(args.model, token=read_token(args.token_file), device=args.device)
    except Exception as exc:
        backend_status = "unavailable"
        backend_error = str(exc)

    speaker_matches = []
    if embedder is not None:
        for label in labels:
            spans = voice_identity.representative_spans(merged.get("segments", []), label, args.max_spans_per_speaker)
            try:
                speaker_matches.append(voice_identity.match_speaker(
                    embedder=embedder,
                    audio_path=audio,
                    speaker_label=label,
                    spans=spans,
                    profiles_root=profiles_root,
                    profiles=profiles,
                    auto_threshold=args.auto_threshold,
                    confirm_threshold=args.confirm_threshold,
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
        "stage": "07_voice_identification",
        "source_mp3": source_mp3,
        "scope": "file-local",
        "created_at": io_utils.utc_now(),
        "source_metadata": call_meta,
        "voice_profiles_dir": str(profiles_root),
        "phone_resolution": phone_resolution,
        "backend": {"name": "pyannote.embedding", "model": args.model, "status": backend_status, "error": backend_error},
        "thresholds": {"auto": args.auto_threshold, "confirm": args.confirm_threshold},
        "speaker_matches": speaker_matches,
    }
    io_utils.write_json(out, data)
    io_utils.write_json(man, {
        "stage": "07_voice_identification",
        "script": "scripts/07_voice_identification.py",
        "input_artifacts": [
            {"path": str(merged_p), "sha256": io_utils.sha256_file(merged_p)},
            {"path": str(audio), "sha256": io_utils.sha256_file(audio)},
        ],
        "output_artifacts": [{"path": str(out), "sha256": io_utils.sha256_file(out)}],
        "backend": {"name": "pyannote.embedding", "model": args.model, "status": backend_status},
        "created_at": io_utils.utc_now(),
    })
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
