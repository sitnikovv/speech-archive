#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse, subprocess
from speech_archive_lib import artifacts, io_utils

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('input_mp3'); ap.add_argument('--new-version', action='store_true')
    args=ap.parse_args(); src=Path(args.input_mp3); base=artifacts.base_name(src)
    if base.endswith('.input.v1') or '.input.v' in base: base=base.split('.input.v')[0]
    artifacts.ensure_dirs(ROOT); stage=artifacts.stage_dir(ROOT/'data','02','audio'); stem=f'{base}.audio.normalized'
    existing=artifacts.latest_versioned_path(stage, stem, '.wav') if not args.new_version else None
    if existing and existing.exists(): print(existing); return 0
    v=artifacts.next_version(stage, stem, '.wav'); out=artifacts.versioned_path(stage, stem, '.wav', v); out.parent.mkdir(parents=True, exist_ok=True)
    cmd=['ffmpeg','-y','-i',str(src),'-ac','1','-ar','16000','-vn',str(out)]
    p=subprocess.run(cmd,text=True,capture_output=True)
    if p.returncode!=0: raise SystemExit(p.stderr)
    mp3_dur=float(io_utils.ffprobe(src)['format'].get('duration',0.0)); wav_dur=float(io_utils.ffprobe(out)['format'].get('duration',0.0))
    man=artifacts.versioned_path(stage, stem, '.manifest.json', v)
    out_hash=io_utils.sha256_file(out)
    m={'artifact':str(out),'stage':'02_audio','script':'scripts/02_make_audio_variant.py','input_artifacts':[{'path':str(src),'sha256':io_utils.sha256_file(src)}],'output_artifacts':[{'path':str(out),'sha256':out_hash}],'command':cmd,'variant':'normalized','duration':wav_dur,'source_duration':mp3_dur,'sha256':out_hash,'created_at':io_utils.utc_now()}
    io_utils.write_json(man,m); print(out); return 0
if __name__=='__main__': raise SystemExit(main())
