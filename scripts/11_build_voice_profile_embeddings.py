#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from speech_archive_lib import artifacts, io_utils, voice_identity, voice_profiles

PYANNOTE_MODEL = "pyannote/embedding"
ECAPA_BACKEND = "speechbrain_ecapa"
ECAPA_MODEL = "speechbrain/spkrec-ecapa-voxceleb"


def read_token(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8").strip() or None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Step 11: build/migrate voice profile embedding caches.")
    ap.add_argument("--voice-profiles-dir", default=str(ROOT / "data" / "voice_profiles"))
    ap.add_argument("--backend", choices=["all", "pyannote", "ecapa"], default="all")
    ap.add_argument("--pyannote-model", default=PYANNOTE_MODEL)
    ap.add_argument("--ecapa-model", default=ECAPA_MODEL)
    ap.add_argument("--token-file", default=str(ROOT / "token.txt"))
    ap.add_argument("--pyannote-device", default=None)
    ap.add_argument("--ecapa-device", default="cpu")
    ap.add_argument("--keep-legacy", action="store_true", help="Copy legacy caches instead of moving/removing them.")
    ap.add_argument("--new-version", action="store_true")
    return ap


def valid_cache(path: Path, sample: Path, model_id: str) -> bool:
    if not path.exists():
        return False
    try:
        data = io_utils.read_json(path)
    except Exception:
        return False
    return (
        data.get("model") == model_id
        and data.get("sample_file") == sample.name
        and data.get("sample_sha256") == io_utils.sha256_file(sample)
        and isinstance(data.get("embedding"), list)
    )


def migrate_cache(sample: Path, *, backend_name: str, model_id: str, legacy: Path, keep_legacy: bool) -> dict[str, Any]:
    target = voice_identity.voice_embedding_cache_path(sample, backend_name, model_id)
    result = {
        "sample": str(sample),
        "backend": backend_name,
        "model": model_id,
        "target": str(target),
        "legacy": str(legacy),
        "action": "none",
    }
    target_valid = valid_cache(target, sample, model_id)
    legacy_valid = valid_cache(legacy, sample, model_id)
    if target_valid:
        if legacy.exists() and legacy_valid and not keep_legacy:
            legacy.unlink()
            result["action"] = "removed_legacy_duplicate"
        else:
            result["action"] = "already_current"
        return result
    if legacy_valid:
        target.parent.mkdir(parents=True, exist_ok=True)
        if keep_legacy:
            shutil.copy2(legacy, target)
            result["action"] = "copied_legacy_to_current"
        else:
            shutil.move(str(legacy), str(target))
            result["action"] = "moved_legacy_to_current"
        return result
    result["action"] = "missing"
    return result


def prune_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for p in sorted([x for x in root.rglob("*") if x.is_dir()], key=lambda x: len(x.parts), reverse=True):
        try:
            p.rmdir()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass


def main() -> int:
    args = build_parser().parse_args()
    artifacts.ensure_dirs(ROOT)
    profiles_root = Path(args.voice_profiles_dir)
    samples = voice_profiles.enrolled_samples(profiles_root)

    stage = artifacts.stage_dir(ROOT / "data", "11", "voice_profile_embeddings")
    stem = "voice-profile-embeddings"
    existing = artifacts.latest_versioned_path(stage, stem, ".json") if not args.new_version else None
    if existing and existing.exists():
        print(existing)
        return 0

    backends: list[tuple[str, str, str, Path | None]] = []
    if args.backend in {"all", "pyannote"}:
        backends.append(("pyannote", voice_identity.PYANNOTE_BACKEND_NAME, args.pyannote_model, None))
    if args.backend in {"all", "ecapa"}:
        backends.append(("ecapa", ECAPA_BACKEND, args.ecapa_model, None))

    migrations: list[dict[str, Any]] = []
    built: list[dict[str, Any]] = []
    existing_current: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    embedders: dict[str, Any] = {}
    for kind, backend_name, model_id, _ in backends:
        for sample in samples:
            legacy = (
                voice_identity.legacy_embedding_cache_path(sample, model_id)
                if kind == "pyannote"
                else voice_identity.legacy_backend_embedding_cache_path(sample, backend_name, model_id)
            )
            mig = migrate_cache(sample, backend_name=backend_name, model_id=model_id, legacy=legacy, keep_legacy=args.keep_legacy)
            migrations.append(mig)
            target = Path(mig["target"])
            if valid_cache(target, sample, model_id):
                existing_current.append({"sample": str(sample), "backend": backend_name, "model": model_id, "cache": str(target)})
                continue
            try:
                if kind not in embedders:
                    if kind == "pyannote":
                        embedders[kind] = voice_identity.PyannoteEmbeddingBackend(
                            model_id,
                            token=read_token(args.token_file),
                            device=args.pyannote_device,
                        )
                    else:
                        embedders[kind] = voice_identity.SpeechBrainEcapaBackend(
                            model_id,
                            device=args.ecapa_device,
                            savedir=ROOT / "data" / "models-cache" / "speechbrain" / artifacts.safe_model_id(model_id),
                        )
                embedding = voice_identity.cached_sample_embedding_at(target, embedders[kind], sample)
                built.append({"sample": str(sample), "backend": backend_name, "model": model_id, "cache": str(target), "dimension": len(embedding)})
            except Exception as exc:
                errors.append({"sample": str(sample), "backend": backend_name, "model": model_id, "error": type(exc).__name__ + ": " + str(exc)})

    if not args.keep_legacy:
        for profile_dir in [p for p in profiles_root.iterdir() if p.is_dir()] if profiles_root.exists() else []:
            prune_empty_dirs(profile_dir / "embeddings")
            prune_empty_dirs(profile_dir / "voice_identification")

    v = artifacts.next_version(stage, stem, ".json")
    out = artifacts.versioned_path(stage, stem, ".json", v)
    data = {
        "artifact": str(out),
        "stage": "11_voice_profile_embeddings",
        "script": "scripts/11_build_voice_profile_embeddings.py",
        "voice_profiles_dir": str(profiles_root),
        "storage": "<profile>/voice_embeddings/<backend>/<model>/<sample>.json",
        "backend_filter": args.backend,
        "sample_count": len(samples),
        "migrations": migrations,
        "existing_current": existing_current,
        "built": built,
        "errors": errors,
        "created_at": io_utils.utc_now(),
    }
    io_utils.write_json(out, data)
    io_utils.write_json(artifacts.manifest_for(out), {
        "stage": "11_voice_profile_embeddings",
        "script": "scripts/11_build_voice_profile_embeddings.py",
        "input_artifacts": [{"path": str(p), "sha256": io_utils.sha256_file(p)} for p in samples],
        "output_artifacts": [{"path": str(out), "sha256": io_utils.sha256_file(out)}],
        "created_at": io_utils.utc_now(),
        "status": "FAILED" if errors else "OK",
    })
    print(out)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
