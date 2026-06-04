#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
from speech_archive_lib import artifacts, io_utils, export

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('merged'); ap.add_argument('speakers'); ap.add_argument('--new-version',action='store_true')
    args=ap.parse_args(); merged_p=Path(args.merged); speakers_p=Path(args.speakers); merged=io_utils.read_json(merged_p); speakers=io_utils.read_json(speakers_p); speakers['mapping_file']=str(speakers_p); base=artifacts.base_name(Path(merged.get('source_mp3','input.mp3')))
    artifacts.ensure_dirs(ROOT); stage=artifacts.stage_dir(ROOT/'data','09','transcript'); stem=f'{base}.transcript.with-names'
    existing=artifacts.latest_versioned_path(stage,stem,'.txt') if not args.new_version else None
    if existing and existing.exists(): print(existing); return 0
    v=artifacts.next_version(stage,stem,'.txt'); out=artifacts.versioned_path(stage,stem,'.txt',v); man=artifacts.manifest_for(out)
    io_utils.write_text(out,export.render_transcript(merged,speakers)); io_utils.write_json(man,{'stage':'09_transcript','script':'scripts/09_export_transcript.py','input_artifacts':[{'path':str(merged_p),'sha256':io_utils.sha256_file(merged_p)},{'path':str(speakers_p),'sha256':io_utils.sha256_file(speakers_p)}],'output_artifacts':[{'path':str(out),'sha256':io_utils.sha256_file(out)}],'created_at':io_utils.utc_now()})
    print(out); return 0
if __name__=='__main__': raise SystemExit(main())
