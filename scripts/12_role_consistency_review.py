#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from speech_archive_lib import artifacts, io_utils


JSON_BEGIN = "@@ROLE_REVIEW_JSON_BEGIN@@"
JSON_END = "@@ROLE_REVIEW_JSON_END@@"


def build_prompt(transcript_text: str, merged: dict[str, Any], speakers: dict[str, Any]) -> str:
    assignments = speakers.get("assignments", {})
    source_mp3 = merged.get("source_mp3")
    return f"""Ты выполняешь смысловую проверку согласованности ролей в расшифровке разговора.

Строгие правила:
- Используй только текст расшифровки, текущие labels говорящих и соседний контекст реплик.
- Имена/labels говорящих считай непрозрачными идентификаторами: не делай выводы из значения, названия или семантики имени/label.
- Не используй заранее заданные доменные правила, списки фраз, шаблоны или хардкод.
- Не исправляй данные автоматически.
- Верни только кандидаты, где текущий говорящий плохо согласуется с контекстом диалога.
- Если кандидатов нет, верни пустой массив candidates.
- Не пересказывай разговор.
- Ответ должен быть валидным JSON строго между маркерами {JSON_BEGIN} и {JSON_END}.

Формат JSON:
{{
  "status": "ok",
  "method": "llm_role_consistency_review",
  "source_mp3": {json.dumps(source_mp3, ensure_ascii=False)},
  "candidates": [
    {{
      "time": "HH:MM:SS.mmm",
      "current_speaker": "как указано в строке расшифровки",
      "suggested_speaker": "имя/label из существующих говорящих или UNKNOWN",
      "confidence": 0.0,
      "reason": "краткое объяснение только через соседний контекст",
      "evidence_lines": ["короткие цитаты из соседних строк"]
    }}
  ]
}}

Текущие assignments, только как справочник существующих labels/names:
{json.dumps(assignments, ensure_ascii=False, indent=2)}

Расшифровка:
```text
{transcript_text}
```
"""


def extract_marked_json(text: str) -> dict[str, Any]:
    match = re.search(re.escape(JSON_BEGIN) + r"\s*(\{.*?\})\s*" + re.escape(JSON_END), text, re.S)
    if not match:
        raise ValueError("LLM response does not contain marked JSON")
    return json.loads(match.group(1))


def run_hermes_llm(prompt: str, timeout: int) -> tuple[dict[str, Any], str]:
    cmd = ["hermes", "-z", prompt, "--cli"]
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, cwd=str(ROOT))
    raw = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0:
        raise RuntimeError(raw.strip() or f"hermes exited with {proc.returncode}")
    return extract_marked_json(raw), raw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("merged")
    ap.add_argument("speakers")
    ap.add_argument("transcript")
    ap.add_argument("--new-version", action="store_true")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    merged_p = Path(args.merged)
    speakers_p = Path(args.speakers)
    transcript_p = Path(args.transcript)
    merged = io_utils.read_json(merged_p)
    speakers = io_utils.read_json(speakers_p)
    transcript_text = transcript_p.read_text(encoding="utf-8")

    base = artifacts.base_name(Path(merged.get("source_mp3", "input.mp3")))
    artifacts.ensure_dirs(ROOT)
    stage = artifacts.stage_dir(ROOT / "data", "12", "role_consistency_review")
    stage.mkdir(parents=True, exist_ok=True)
    stem = f"{base}.role-consistency-review.hermes"
    existing = artifacts.latest_versioned_path(stage, stem, ".json") if not args.new_version else None
    if existing and existing.exists():
        print(existing)
        return 0

    prompt = build_prompt(transcript_text, merged, speakers)
    review, raw_response = run_hermes_llm(prompt, args.timeout)
    candidates = review.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("LLM JSON must contain candidates list")

    v = artifacts.next_version(stage, stem, ".json")
    out = artifacts.versioned_path(stage, stem, ".json", v)
    man = artifacts.manifest_for(out)
    data = {
        "artifact": str(out),
        "stage": "12_role_consistency_review",
        "source_mp3": merged.get("source_mp3"),
        "merged_file": str(merged_p),
        "speakers_file": str(speakers_p),
        "transcript_file": str(transcript_p),
        "created_at": io_utils.utc_now(),
        "llm_runner": "hermes-cli",
        "review": review,
    }
    io_utils.write_json(out, data)
    raw_out = out.with_suffix(".raw.txt")
    io_utils.write_text(raw_out, raw_response)
    io_utils.write_json(man, {
        "stage": "12_role_consistency_review",
        "script": "scripts/12_role_consistency_review.py",
        "input_artifacts": [
            {"path": str(merged_p), "sha256": io_utils.sha256_file(merged_p)},
            {"path": str(speakers_p), "sha256": io_utils.sha256_file(speakers_p)},
            {"path": str(transcript_p), "sha256": io_utils.sha256_file(transcript_p)},
        ],
        "output_artifacts": [
            {"path": str(out), "sha256": io_utils.sha256_file(out)},
            {"path": str(raw_out), "sha256": io_utils.sha256_file(raw_out)},
        ],
        "llm_runner": "hermes-cli",
        "created_at": io_utils.utc_now(),
    })
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
