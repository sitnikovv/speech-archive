from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from . import artifacts, io_utils


def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D+", "", raw)
    if not digits:
        return None
    if digits.startswith("00") and len(digits) > 2:
        return "+" + digits[2:]
    if len(digits) == 11 and digits.startswith("8"):
        return "+7" + digits[1:]
    if len(digits) == 11 and digits.startswith("7"):
        return "+" + digits
    return "+" + digits


def parse_call_filename(path_or_name: str | Path) -> dict[str, Any]:
    name = Path(path_or_name).name
    stem = name
    for suffix in (".mp3", ".wav", ".m4a", ".flac", ".ogg"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    stem = re.sub(r"\.(input|audio|asr|diarization|merge|speakers|transcript).*$", "", stem)
    m = re.search(r"\((?P<phone>[^)]+)\)_(?P<dt>\d{14})", stem)
    if not m:
        return {"filename": name, "phone_e164": None, "call_datetime": None, "display_name": None}
    dt = datetime.strptime(m.group("dt"), "%Y%m%d%H%M%S")
    return {
        "filename": name,
        "display_name": stem[: m.start()].strip() or None,
        "phone_e164": normalize_phone(m.group("phone")),
        "call_datetime": dt.isoformat(timespec="seconds"),
    }


def safe_component(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-zА-Яа-яЁё._-]+", "_", text).strip("_")
    return value or "value"


def person_id_from_name(name: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", name).strip(" ._")
    value = re.sub(r"\s+", " ", value)
    return value or "value"


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value[:19])


def period_contains(item: dict[str, Any], at_iso: str | None) -> bool:
    if not at_iso:
        return True
    at = _parse_date(at_iso)
    start = _parse_date(item.get("valid_from"))
    end = _parse_date(item.get("valid_to"))
    if start and at and at < start:
        return False
    if end and at and at > end:
        return False
    return True


def load_profiles(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    profiles: list[dict[str, Any]] = []
    for p in sorted(root.glob("*/profile.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        data.setdefault("person_id", p.parent.name)
        data["profile_dir"] = str(p.parent)
        profiles.append(data)
    return profiles


def profile_json(profile: dict[str, Any]) -> Path:
    return Path(profile["profile_dir"]) / "profile.json"


def _write_profile(profile: dict[str, Any]) -> None:
    data = {k: v for k, v in profile.items() if k != "profile_dir"}
    io_utils.write_json(profile_json(profile), data)


def create_profile(root: Path, full_name: str, aliases: list[str] | None = None) -> dict[str, Any]:
    base = person_id_from_name(full_name)
    person_id = base
    n = 2
    while (root / person_id / "profile.json").exists():
        person_id = f"{base}_{n}"
        n += 1
    profile_dir = root / person_id
    profile = {
        "person_id": person_id,
        "full_name": full_name,
        "aliases": [{"name": a, "valid_from": None, "valid_to": None} for a in (aliases or [])],
        "phones": [],
        "created_at": io_utils.utc_now(),
        "profile_dir": str(profile_dir),
    }
    profile_dir.mkdir(parents=True, exist_ok=True)
    _write_profile(profile)
    return profile


def alias_exists(profile: dict[str, Any], alias: str, at_iso: str | None = None) -> bool:
    needle = alias.strip().casefold()
    if str(profile.get("full_name", "")).strip().casefold() == needle:
        return True
    for item in profile.get("aliases", []):
        if str(item.get("name", "")).strip().casefold() == needle and period_contains(item, at_iso):
            return True
    return False


def add_alias(profile: dict[str, Any], alias: str) -> dict[str, Any] | None:
    if alias_exists(profile, alias):
        return None
    item = {"name": alias, "valid_from": None, "valid_to": None, "source": "manual_speaker_name"}
    profile.setdefault("aliases", []).append(item)
    _write_profile(profile)
    return item


def find_profiles_by_name_or_alias(profiles: list[dict[str, Any]], name: str, at_iso: str | None = None) -> list[dict[str, Any]]:
    return [p for p in profiles if alias_exists(p, name, at_iso)]


def phone_valid_for_profile(profile: dict[str, Any], phone_e164: str | None, at_iso: str | None) -> bool:
    if not phone_e164:
        return False
    for phone in profile.get("phones", []):
        if normalize_phone(phone.get("e164")) == phone_e164 and period_contains(phone, at_iso):
            return True
    return False


def add_phone_binding(profile: dict[str, Any], phone_e164: str, observed_at: str | None, source: str = "manual") -> dict[str, Any] | None:
    normalized = normalize_phone(phone_e164)
    if not normalized:
        return None
    if phone_valid_for_profile(profile, normalized, observed_at):
        return None
    item = {
        "e164": normalized,
        "valid_from": None,
        "valid_to": None,
        "confirmed": True,
    }
    profile.setdefault("phones", []).append(item)
    _write_profile(profile)
    return item


def resolve_phone_profiles(profiles: list[dict[str, Any]], phone_e164: str | None, call_datetime: str | None) -> dict[str, Any]:
    if not phone_e164:
        return {"status": "no_phone", "phone_e164": None, "priority_profiles": [], "phone_profiles": []}
    phone_profiles: list[dict[str, Any]] = []
    priority: list[dict[str, Any]] = []
    for profile in profiles:
        for phone in profile.get("phones", []):
            if normalize_phone(phone.get("e164")) != phone_e164:
                continue
            entry = {
                "person_id": profile.get("person_id"),
                "full_name": profile.get("full_name"),
                "profile_dir": profile.get("profile_dir"),
                "phone": phone,
            }
            phone_profiles.append(entry)
            if period_contains(phone, call_datetime):
                priority.append(entry)
    if priority:
        return {"status": "matched", "phone_e164": phone_e164, "priority_profiles": priority, "phone_profiles": phone_profiles}
    if phone_profiles:
        return {"status": "conflict", "phone_e164": phone_e164, "priority_profiles": [], "phone_profiles": phone_profiles}
    return {"status": "no_match", "phone_e164": phone_e164, "priority_profiles": [], "phone_profiles": []}


def find_source_mp3(root: Path, source_mp3: str, override: str | None = None) -> Path | None:
    if override:
        p = Path(override)
        return p if p.exists() else None
    p = Path(source_mp3)
    if p.exists():
        return p
    base = artifacts.base_name(Path(source_mp3))
    stage = root / "data" / "artifacts" / "01_input"
    latest = artifacts.latest_versioned_path(stage, f"{base}.input", ".mp3")
    if latest and latest.exists():
        return latest
    matches = sorted(stage.glob(f"{base}.input.v*.mp3")) if stage.exists() else []
    return matches[-1] if matches else None


def enrolled_samples(profiles_root: Path, priority_person_ids: set[str] | None = None) -> list[Path]:
    roots: list[Path] = []
    if priority_person_ids:
        for pid in sorted(priority_person_ids):
            roots.append(profiles_root / pid / "samples" / "enrolled")
    roots.extend(p for p in sorted(profiles_root.glob("*/samples/enrolled")) if p.parent.name not in (priority_person_ids or set()))
    samples: list[Path] = []
    for root in roots:
        if root.exists():
            samples.extend(sorted(root.glob("*.mp3")))
    return samples


def auto_match_placeholder(profiles_root: Path, phone_resolution: dict[str, Any]) -> dict[str, Any]:
    priority_ids = {str(p.get("person_id")) for p in phone_resolution.get("priority_profiles", []) if p.get("person_id")}
    count = len(enrolled_samples(profiles_root, priority_ids))
    return {
        "status": "not_available",
        "reason": "speaker embedding backend is not implemented yet",
        "enrolled_samples_seen": count,
    }


def sample_id(source_mp3: str, speaker_label: str, start: float, end: float, person_id: str) -> str:
    key = f"{source_mp3}|{speaker_label}|{start:.3f}|{end:.3f}|{person_id}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return f"{safe_component(person_id)}.sample.{digest}"


def portable_project_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def save_enrolled_mp3_sample(
    *,
    profile: dict[str, Any],
    source_mp3_path: Path,
    source_mp3: str,
    speaker_label: str,
    span: dict[str, Any],
    call_meta: dict[str, Any],
) -> dict[str, Any]:
    start = float(span["start"])
    end = float(span["end"])
    duration = max(0.1, end - start)
    sid = sample_id(source_mp3, speaker_label, start, end, str(profile["person_id"]))
    out_dir = Path(profile["profile_dir"]) / "samples" / "enrolled"
    out_dir.mkdir(parents=True, exist_ok=True)
    mp3 = out_dir / f"{sid}.mp3"
    meta = out_dir / f"{sid}.json"
    if not mp3.exists():
        cmd = ["ffmpeg", "-n", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(source_mp3_path), "-c", "copy", str(mp3)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    data = {
        "sample_id": sid,
        "status": "enrolled_manual_voice_confirmation",
        "audio_file": mp3.name,
        "person_id": profile.get("person_id"),
        "duration": duration,
        "created_at": io_utils.utc_now(),
    }
    if not meta.exists():
        io_utils.write_json(meta, data, overwrite=False)
    return {"sample_id": sid, "sample": portable_project_path(mp3), "metadata": portable_project_path(meta)}
