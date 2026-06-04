#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
from speech_archive_lib import artifacts, io_utils, merge

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('asr_segments'); ap.add_argument('diarization_segments'); ap.add_argument('--new-version',action='store_true')
    args=ap.parse_args(); asr_p=Path(args.asr_segments); dia_p=Path(args.diarization_segments); asr=io_utils.read_json(asr_p); dia=io_utils.read_json(dia_p)
    base=artifacts.base_name(Path(asr.get('source_mp3','input.mp3'))); asr_safe=artifacts.safe_model_id(asr.get('model','asr')); dia_safe=artifacts.safe_model_id(dia.get('model','diarization'))
    artifacts.ensure_dirs(ROOT); stage=artifacts.stage_dir(ROOT/'data','06','merge'); stem=f'{base}.merge.{asr_safe}.{dia_safe}'
    existing=artifacts.latest_versioned_path(stage,stem,'.json') if not args.new_version else None
    if existing and existing.exists(): print(existing); return 0
    v=artifacts.next_version(stage,stem,'.json'); out=artifacts.versioned_path(stage,stem,'.json',v); man=artifacts.manifest_for(out)
    merged_segments=merge.merge_segments(asr.get('segments',[]),dia.get('segments',[]))
    data={'artifact':str(out),'stage':'06_merge','source_mp3':asr.get('source_mp3'),'asr_model':asr.get('model'),'diarization_model':dia.get('model'),'asr_segments_file':str(asr_p),'diarization_segments_file':str(dia_p),'created_at':io_utils.utc_now(),'segments':merged_segments}
    io_utils.write_json(out,data); io_utils.write_json(man,{'stage':'06_merge','script':'scripts/06_merge_asr_diarization.py','input_artifacts':[{'path':str(asr_p),'sha256':io_utils.sha256_file(asr_p)},{'path':str(dia_p),'sha256':io_utils.sha256_file(dia_p)}],'output_artifacts':[{'path':str(out),'sha256':io_utils.sha256_file(out)}],'created_at':io_utils.utc_now()})
    print(out); return 0
if __name__=='__main__': raise SystemExit(main())
