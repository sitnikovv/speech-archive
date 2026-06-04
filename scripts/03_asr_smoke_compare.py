#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse, subprocess, tempfile
from speech_archive_lib import artifacts, io_utils

def clean_base(path: Path) -> str:
    b=artifacts.base_name(path)
    if '.audio.normalized.v' in b: return b.split('.audio.normalized.v')[0]
    if '.input.v' in b: return b.split('.input.v')[0]
    return b

def try_faster_whisper(audio: Path, model_dir: Path) -> dict:
    try:
        from faster_whisper import WhisperModel
        last_error=None
        for device, compute_type in [('cuda','float16'),('cpu','int8')]:
            try:
                model=WhisperModel(str(model_dir), device=device, compute_type=compute_type, local_files_only=True)
                segments, info = model.transcribe(str(audio), language='ru', vad_filter=True, beam_size=5)
                out=[{'start':s.start,'end':s.end,'text':s.text} for _,s in zip(range(5),segments)]
                return {'status':'ok' if out else 'bad_output','device':device,'compute_type':compute_type,'sample_segments':out,'language':getattr(info,'language',None)}
            except Exception as e: last_error=type(e).__name__+': '+str(e)
        return {'status':'failed','error':last_error}
    except Exception as e: return {'status':'failed','error':type(e).__name__+': '+str(e)}

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('audio_or_mp3'); ap.add_argument('--seconds',type=int,default=45); ap.add_argument('--new-version',action='store_true')
    args=ap.parse_args(); src=Path(args.audio_or_mp3); base=clean_base(src); artifacts.ensure_dirs(ROOT); stage=artifacts.stage_dir(ROOT/'data','03','asr_smoke'); stem=f'{base}.asr-smoke'
    existing=artifacts.latest_versioned_path(stage, stem, '.json') if not args.new_version else None
    if existing and existing.exists(): print(existing); return 0
    v=artifacts.next_version(stage,stem,'.json'); outp=artifacts.versioned_path(stage,stem,'.json',v)
    with tempfile.TemporaryDirectory() as d:
        sample=Path(d)/'sample.wav'
        subprocess.run(['ffmpeg','-y','-i',str(src),'-t',str(args.seconds),'-ac','1','-ar','16000',str(sample)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        results={}
        for m in ['nvidia/parakeet-tdt-0.6b-v3','nvidia/canary-1b-v2']:
            candidates=artifacts.model_cache_candidates(ROOT/'data',m)
            results[m]={'status':'no_timestamps','reason':'NeMo timestamp extraction not implemented in first smoke; requires verified API','model_path_exists':any(p.exists() for p in candidates),'model_paths':[str(p) for p in candidates if p.exists()]}
        fw_dir=ROOT/'data'/'models-cache'/'huggingface'/'Systran__faster-whisper-large-v3'
        results['Systran/faster-whisper-large-v3']=try_faster_whisper(sample,fw_dir) if fw_dir.exists() else {'status':'failed','error':'model dir missing'}
    selected='Systran/faster-whisper-large-v3' if results['Systran/faster-whisper-large-v3']['status']=='ok' else None
    report={'artifact':str(outp),'stage':'03_asr_smoke','script':'scripts/03_asr_smoke_compare.py','input_artifacts':[{'path':str(src),'sha256':io_utils.sha256_file(src)}],'created_at':io_utils.utc_now(),'results':results,'selected_asr_model':selected,'reason':'selected first model with usable segment timestamps'}
    io_utils.write_json(outp,report); man=artifacts.manifest_for(outp); io_utils.write_json(man,{'stage':'03_asr_smoke','input_artifacts':report['input_artifacts'],'output_artifacts':[{'path':str(outp),'sha256':io_utils.sha256_file(outp)}],'status':'OK' if selected else 'BLOCKED','created_at':io_utils.utc_now()})
    print(outp); return 0 if selected else 2
if __name__=='__main__': raise SystemExit(main())
