#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
from speech_archive_lib import artifacts, io_utils, audit

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('merged'); ap.add_argument('speakers'); ap.add_argument('--transcript'); ap.add_argument('--new-version',action='store_true')
    args=ap.parse_args(); merged_p=Path(args.merged); speakers_p=Path(args.speakers); merged=io_utils.read_json(merged_p); speakers=io_utils.read_json(speakers_p); base=artifacts.base_name(Path(merged.get('source_mp3','input.mp3')))
    artifacts.ensure_dirs(ROOT); stage=artifacts.stage_dir(ROOT/'data','10','audit'); stem=f'{base}.audit.dialogue'
    existing=artifacts.latest_versioned_path(stage,stem,'.json') if not args.new_version else None
    if existing and existing.exists(): print(existing); return 0
    v=artifacts.next_version(stage,stem,'.json'); out=artifacts.versioned_path(stage,stem,'.json',v); man=artifacts.manifest_for(out)
    data={'artifact':str(out),'stage':'10_audit','source_mp3':merged.get('source_mp3'),'merged_file':str(merged_p),'speakers_file':str(speakers_p),'transcript_file':args.transcript,'created_at':io_utils.utc_now(),**audit.audit_candidates(merged,speakers)}
    io_utils.write_json(out,data)
    inputs=[{'path':str(merged_p),'sha256':io_utils.sha256_file(merged_p)},{'path':str(speakers_p),'sha256':io_utils.sha256_file(speakers_p)}]
    if args.transcript: inputs.append({'path':args.transcript,'sha256':io_utils.sha256_file(Path(args.transcript))})
    io_utils.write_json(man,{'stage':'10_audit','script':'scripts/10_audit_dialogue_anomalies.py','input_artifacts':inputs,'output_artifacts':[{'path':str(out),'sha256':io_utils.sha256_file(out)}],'created_at':io_utils.utc_now()})
    print(out); return 0
if __name__=='__main__': raise SystemExit(main())
