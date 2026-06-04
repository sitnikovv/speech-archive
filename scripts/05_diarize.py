#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
from speech_archive_lib import artifacts, io_utils

def clean_base(path: Path) -> str:
    b=artifacts.base_name(path)
    if '.audio.normalized.v' in b: return b.split('.audio.normalized.v')[0]
    return b

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('audio'); ap.add_argument('--new-version',action='store_true'); ap.add_argument('--device',default='cpu')
    args=ap.parse_args(); audio=Path(args.audio); base=clean_base(audio); model_id='pyannote/speaker-diarization-3.1'; safe=artifacts.safe_model_id(model_id)
    artifacts.ensure_dirs(ROOT); stage=artifacts.stage_dir(ROOT/'data','05','diarization'); stem=f'{base}.diarization.{safe}'
    existing=artifacts.latest_versioned_path(stage, stem+'.segments','.json') if not args.new_version else None
    if existing and existing.exists(): print(existing); return 0
    token_path=ROOT/'token.txt'
    if not token_path.exists(): raise SystemExit('token.txt missing')
    token=token_path.read_text(encoding='utf-8').strip()
    from pyannote.audio import Pipeline
    try: pipe=Pipeline.from_pretrained(model_id, token=token)
    except TypeError: pipe=Pipeline.from_pretrained(model_id, use_auth_token=token)
    if args.device=='cuda':
        try:
            import torch; pipe.to(torch.device('cuda'))
        except Exception: pass
    result=pipe(str(audio)); annotation=getattr(result,'speaker_diarization',result)
    turns=[]
    for i,(turn,_,speaker) in enumerate(annotation.itertracks(yield_label=True),1):
        turns.append({'id':i,'start':float(turn.start),'end':float(turn.end),'speaker':str(speaker),'confidence':None,'raw_ref':i})
    v=artifacts.next_version(stage, stem+'.segments','.json'); rawp=artifacts.versioned_path(stage,stem+'.raw','.json',v); segp=artifacts.versioned_path(stage,stem+'.segments','.json',v); man=artifacts.versioned_path(stage,stem,'.manifest.json',v)
    io_utils.write_json(rawp,{'artifact':str(rawp),'stage':'05_diarization','source_audio':str(audio),'model':model_id,'created_at':io_utils.utc_now(),'segments':turns})
    io_utils.write_json(segp,{'artifact':str(segp),'stage':'05_diarization','source_mp3':f'{base}.mp3','source_audio':str(audio),'model':model_id,'segments':turns})
    io_utils.write_json(man,{'stage':'05_diarization','script':'scripts/05_diarize.py','input_artifacts':[{'path':str(audio),'sha256':io_utils.sha256_file(audio)}],'output_artifacts':[{'path':str(rawp),'sha256':io_utils.sha256_file(rawp)},{'path':str(segp),'sha256':io_utils.sha256_file(segp)}],'model':model_id,'token_printed':False,'created_at':io_utils.utc_now()})
    print(segp); return 0
if __name__=='__main__': raise SystemExit(main())
