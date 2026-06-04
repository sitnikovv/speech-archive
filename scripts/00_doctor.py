#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse, json, shutil
from speech_archive_lib import artifacts, io_utils, env

TEST_MP3 = Path('/mnt/shared/sound/Яна Ситникова(0079263717233)_20260509182759.mp3')
MODELS = ['Systran/faster-whisper-large-v3','Systran/faster-whisper-small','nvidia/canary-1b-v2','nvidia/parakeet-tdt-0.6b-v3','pyannote/speaker-diarization-3.1']

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument('--source-mp3', default=str(TEST_MP3)); ap.add_argument('--new-version', action='store_true'); ap.add_argument('--json', action='store_true')
    args = ap.parse_args(); source = Path(args.source_mp3); data = ROOT/'data'; artifacts.ensure_dirs(ROOT)
    stage = artifacts.stage_dir(data, '00', 'doctor'); stem = artifacts.base_name(source) + '.doctor'
    out = artifacts.latest_versioned_path(stage, stem, '.json') if not args.new_version else None
    if out and out.exists():
        report = io_utils.read_json(out)
        if args.json: print(json.dumps(report, ensure_ascii=False, indent=2))
        else: print(out)
        return 0 if report.get('status') == 'OK' else 2
    version = artifacts.next_version(stage, stem, '.json'); out = artifacts.versioned_path(stage, stem, '.json', version)
    found = {m: [str(p) for p in artifacts.model_cache_candidates(data, m) if p.exists()] for m in MODELS}
    libs = {name: env.module_available(name) for name in ['faster_whisper','torch','nemo','pyannote.audio']}
    cuda = None
    if libs.get('torch'):
        try:
            import torch
            cuda = {'available': bool(torch.cuda.is_available()), 'device': torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}
        except Exception as e: cuda = {'error': str(e)}
    blockers=[]
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'): blockers.append('ffmpeg/ffprobe missing')
    if not source.exists(): blockers.append(f'source mp3 missing: {source}')
    if not (ROOT/'token.txt').exists(): blockers.append('token.txt missing')
    report={'artifact': str(out), 'stage':'00_doctor','script':'scripts/00_doctor.py','source_mp3':str(source),'ffmpeg':shutil.which('ffmpeg'),'ffprobe':shutil.which('ffprobe'),'token_txt_exists':(ROOT/'token.txt').exists(),'token_printed':False,'models':found,'libraries':libs,'cuda':cuda,'blockers':blockers,'status':'OK' if not blockers else 'BLOCKED','created_at':io_utils.utc_now()}
    io_utils.write_json(out, report)
    man = artifacts.manifest_for(out); io_utils.write_json(man, {'stage':'00_doctor','output_artifacts':[{'path':str(out),'sha256':io_utils.sha256_file(out)}],'status':report['status'],'created_at':io_utils.utc_now()})
    if args.json: print(json.dumps(report, ensure_ascii=False, indent=2))
    else: print(out)
    return 0 if not blockers else 2
if __name__ == '__main__': raise SystemExit(main())
