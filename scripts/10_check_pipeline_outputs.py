#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse, json
from speech_archive_lib import artifacts, io_utils

def latest_required(base: str):
    data=ROOT/'data'; fw='Systran_faster-whisper-large-v3'; dia='pyannote_speaker-diarization-3.1'
    specs=[('01','input',f'{base}.input','.mp3'),('01','input',f'{base}.input','.manifest.json'),('02','audio',f'{base}.audio.normalized','.wav'),('02','audio',f'{base}.audio.normalized','.manifest.json'),('03','asr_smoke',f'{base}.asr-smoke','.json'),('04','asr',f'{base}.asr.{fw}.raw','.json'),('04','asr',f'{base}.asr.{fw}.segments','.json'),('05','diarization',f'{base}.diarization.{dia}.raw','.json'),('05','diarization',f'{base}.diarization.{dia}.segments','.json'),('06','merge',f'{base}.merge.{fw}.{dia}','.json'),('07','speakers',f'{base}.speakers.manual','.json'),('08','transcript',f'{base}.transcript.with-names','.txt'),('09','audit',f'{base}.audit.dialogue','.json')]
    return [artifacts.latest_versioned_path(artifacts.stage_dir(data,n,name),stem,suf) for n,name,stem,suf in specs]

def valid_json(path: Path):
    try: json.loads(path.read_text(encoding='utf-8')); return True,''
    except Exception as e: return False,str(e)

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('base_or_mp3'); ap.add_argument('--new-version',action='store_true')
    args=ap.parse_args(); base=artifacts.base_name(Path(args.base_or_mp3)); artifacts.ensure_dirs(ROOT); errors=[]; checked=[]
    for p in latest_required(base):
        if p is None: errors.append('MISSING latest artifact'); continue
        if not p.exists(): errors.append(f'MISSING {p}'); continue
        item={'path':str(p),'sha256':io_utils.sha256_file(p),'status':'OK'}
        if p.suffix=='.json':
            ok,err=valid_json(p)
            if not ok: item['status']='INVALID_JSON'; item['error']=err; errors.append(f'INVALID_JSON {p}: {err}')
        elif p.suffix=='.txt' and not p.read_text(encoding='utf-8').strip(): item['status']='EMPTY'; errors.append(f'EMPTY {p}')
        checked.append(item)
    stage=artifacts.stage_dir(ROOT/'data','10','check'); stem=f'{base}.pipeline-check'; v=artifacts.next_version(stage,stem,'.json') if args.new_version or not artifacts.latest_versioned_path(stage,stem,'.json') else artifacts.next_version(stage,stem,'.json')
    out=artifacts.versioned_path(stage,stem,'.json',v); data={'artifact':str(out),'stage':'10_check','script':'scripts/10_check_pipeline_outputs.py','status':'OK' if not errors else 'FAILED','checked_artifacts':checked,'errors':errors,'created_at':io_utils.utc_now()}
    io_utils.write_json(out,data)
    print('OK' if not errors else '\n'.join(errors)); print(out)
    return 0 if not errors else 2
if __name__=='__main__': raise SystemExit(main())
