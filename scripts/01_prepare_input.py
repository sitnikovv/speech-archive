#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse, shutil
from speech_archive_lib import artifacts, io_utils

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('mp3'); ap.add_argument('--new-version', action='store_true')
    args=ap.parse_args(); src=Path(args.mp3)
    if not src.exists() or src.suffix.lower()!='.mp3': raise SystemExit(f'not mp3: {src}')
    artifacts.ensure_dirs(ROOT); base=artifacts.base_name(src); stage=artifacts.stage_dir(ROOT/'data','01','input')
    mp3_stem=f'{base}.input'; man_stem=f'{base}.input'
    existing=artifacts.latest_versioned_path(stage, mp3_stem, '.mp3') if not args.new_version else None
    if existing and existing.exists(): print(existing); return 0
    v=artifacts.next_version(stage, mp3_stem, '.mp3'); out=artifacts.versioned_path(stage, mp3_stem, '.mp3', v); out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src,out); src_hash=io_utils.sha256_file(src); out_hash=io_utils.sha256_file(out)
    if src_hash!=out_hash: raise SystemExit('sha256 mismatch after copy')
    meta=io_utils.ffprobe(out).get('format',{})
    manifest=artifacts.versioned_path(stage, man_stem, '.manifest.json', v)
    data={'artifact':str(out),'stage':'01_input','script':'scripts/01_prepare_input.py','source_path':str(src),'size':out.stat().st_size,'duration':float(meta.get('duration',0.0)),'format_name':meta.get('format_name'),'bit_rate':meta.get('bit_rate'),'sha256':out_hash,'created_at':io_utils.utc_now()}
    io_utils.write_json(manifest,data); print(out); return 0
if __name__=='__main__': raise SystemExit(main())
