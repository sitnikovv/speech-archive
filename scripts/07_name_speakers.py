#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import termios
from speech_archive_lib import artifacts, io_utils, playback


def enable_utf8_erase(stdin=sys.stdin) -> bool:
    """Ask the terminal line discipline to erase full UTF-8 chars on Backspace."""
    iutf8 = getattr(termios, 'IUTF8', 0)
    if not iutf8 or not hasattr(stdin, 'isatty') or not stdin.isatty():
        return False
    try:
        fd = stdin.fileno()
        attrs = termios.tcgetattr(fd)
        if attrs[0] & iutf8:
            return False
        attrs[0] |= iutf8
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        return True
    except (OSError, termios.error):
        return False


def read_prompt_utf8(prompt: str) -> str:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    buffer = getattr(sys.stdin, 'buffer', None)
    if buffer is None:
        return sys.stdin.readline().strip()
    raw = buffer.readline()
    try:
        return raw.decode('utf-8').strip()
    except UnicodeDecodeError as exc:
        cleaned = raw.decode('utf-8', errors='ignore').strip()
        print(
            f'Предупреждение: во вводе были не-UTF-8 байты, они отброшены: {raw.hex()} ({exc})',
            file=sys.stderr,
        )
        return cleaned


def choose_spans(segments, label, max_count=5):
    spans=[s for s in segments if s.get('speaker_label')==label and not ({'MIXED','OVERLAP'} & set(s.get('uncertainty',[]))) and 1.0 <= float(s.get('end',0))-float(s.get('start',0)) <= 12.0]
    return spans[:max_count]

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('merged'); ap.add_argument('--audio',required=True); ap.add_argument('--new-version',action='store_true'); ap.add_argument('--non-interactive',action='store_true'); ap.add_argument('--player',default='auto',choices=['auto','ffplay','mpv','none']); ap.add_argument('--no-play',action='store_true')
    args=ap.parse_args(); merged_p=Path(args.merged); audio=Path(args.audio); merged=io_utils.read_json(merged_p); base=artifacts.base_name(Path(merged.get('source_mp3','input.mp3')))
    artifacts.ensure_dirs(ROOT); stage=artifacts.stage_dir(ROOT/'data','07','speakers'); stem=f'{base}.speakers.manual'
    existing=artifacts.latest_versioned_path(stage,stem,'.json') if not args.new_version else None
    if existing and existing.exists(): print(existing); return 0
    if not args.non_interactive:
        enable_utf8_erase()
    labels=sorted({s.get('speaker_label') for s in merged.get('segments',[]) if str(s.get('speaker_label','')).startswith('SPEAKER_')})
    assignments={}
    for label in labels:
        name='UNKNOWN'; evidence=None; method='manual_uncertain'; spans=choose_spans(merged.get('segments',[]),label)
        if not args.non_interactive:
            for span in spans:
                print(f'{label}: {span["start"]:.3f}-{span["end"]:.3f} {span.get("text","")[:120]}')
                if not args.no_play:
                    played=playback.play_segment(audio,float(span['start']),float(span['end']),player=args.player)
                    if not played: print('Не найден ffplay/mpv: фрагмент не проигран, показан только таймкод.')
                ans=read_prompt_utf8('Имя / unknown / next / bad / skip: ').strip()
                if ans.lower() in {'next','bad','skip',''}: continue
                if ans.lower() in {'unknown','непонятно'}: name='UNKNOWN'; break
                name=ans; evidence={'source_audio':str(audio),'start':span['start'],'end':span['end'],'note':'пользователь подтвердил по прослушиванию'}; method='manual_voice_confirmation'; break
        assignments[label]={'name':name,'method':method,'evidence':evidence}
    v=artifacts.next_version(stage,stem,'.json'); out=artifacts.versioned_path(stage,stem,'.json',v); man=artifacts.manifest_for(out)
    data={'artifact':str(out),'stage':'07_speakers','source_mp3':merged.get('source_mp3'),'scope':'file-local','created_at':io_utils.utc_now(),'assignments':assignments}
    io_utils.write_json(out,data); io_utils.write_json(man,{'stage':'07_speakers','script':'scripts/07_name_speakers.py','input_artifacts':[{'path':str(merged_p),'sha256':io_utils.sha256_file(merged_p)},{'path':str(audio),'sha256':io_utils.sha256_file(audio)}],'output_artifacts':[{'path':str(out),'sha256':io_utils.sha256_file(out)}],'created_at':io_utils.utc_now()})
    print(out); return 0
if __name__=='__main__': raise SystemExit(main())
