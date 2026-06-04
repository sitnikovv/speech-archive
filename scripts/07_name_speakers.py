#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import termios
from speech_archive_lib import artifacts, io_utils, playback, voice_profiles


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


def ask_yes_no(prompt: str, *, default: bool) -> bool:
    suffix = ' [Y/n]: ' if default else ' [y/N]: '
    answer = read_prompt_utf8(prompt + suffix).strip().lower()
    if not answer:
        return default
    return answer in {'y', 'yes', 'д', 'да'}


def choose_spans(segments, label, max_count=5):
    spans=[s for s in segments if s.get('speaker_label')==label and not ({'MIXED','OVERLAP'} & set(s.get('uncertainty',[]))) and 1.0 <= float(s.get('end',0))-float(s.get('start',0)) <= 12.0]
    return spans[:max_count]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description='Step 07: assign file-local SPEAKER_XX labels to people.')
    ap.add_argument('merged')
    ap.add_argument('--audio', required=True)
    ap.add_argument('--source-mp3', help='Original/input mp3 for saving confirmed enrolled samples; auto-detected from data/artifacts/01_input when omitted.')
    ap.add_argument('--new-version', action='store_true')
    ap.add_argument('--ci-non-interactive', action='store_true', help='CI/tests only: never play audio and mark unresolved speakers UNKNOWN.')
    ap.add_argument('--player', default='auto', choices=['auto','ffplay','mpv'], help='Audio player for interactive unresolved speaker prompts.')
    ap.add_argument('--debug-no-play', action='store_true', help='Debug only: show spans and ask without playing audio.')
    ap.add_argument('--voice-profiles-dir', default=str(ROOT/'data'/'voice_profiles'))
    ap.add_argument('--confirm-existing-profiles', action='store_true', help='Ask before using a single unambiguous existing profile match. Default: use it automatically.')
    ap.add_argument('--max-samples-per-speaker', type=int, default=5, help='Maximum fragments to try for one speaker in this conversation.')
    return ap


def suggested_profile_name(entered_name: str, call_meta: dict) -> str:
    display = (call_meta.get('display_name') or '').strip()
    if display and entered_name.strip().casefold() in display.casefold():
        return display
    return entered_name.strip()


def select_or_create_profile(profiles_root: Path, profiles: list[dict], entered_name: str, call_meta: dict, confirm_existing: bool) -> tuple[dict | None, list[dict]]:
    updates: list[dict] = []
    matches = voice_profiles.find_profiles_by_name_or_alias(profiles, entered_name, call_meta.get('call_datetime'))
    if len(matches) == 1:
        profile = matches[0]
        if confirm_existing and not ask_yes_no(f'Использовать профиль {profile.get("full_name") or profile.get("person_id")}?', default=True):
            return None, updates
        alias = voice_profiles.add_alias(profile, entered_name)
        if alias:
            updates.append({'type': 'alias_added', 'alias': alias})
        return profile, updates
    if len(matches) > 1:
        print(f'Найдено несколько профилей для "{entered_name}":')
        for idx, profile in enumerate(matches, 1):
            print(f'  {idx}. {profile.get("full_name") or profile.get("person_id")} ({profile.get("person_id")})')
        while True:
            answer = read_prompt_utf8('Номер профиля / new / skip: ').strip().lower()
            if answer == 'skip':
                return None, updates
            if answer == 'new':
                break
            if answer.isdigit() and 1 <= int(answer) <= len(matches):
                profile = matches[int(answer) - 1]
                alias = voice_profiles.add_alias(profile, entered_name)
                if alias:
                    updates.append({'type': 'alias_added', 'alias': alias})
                return profile, updates
            print('Не понял ответ.')
    if not ask_yes_no(f'Профиль для "{entered_name}" не найден. Создать?', default=True):
        return None, updates
    default_name = suggested_profile_name(entered_name, call_meta)
    full_name = read_prompt_utf8(f'Имя/ФИО профиля [{default_name}]: ').strip() or default_name
    aliases = [] if full_name.strip().casefold() == entered_name.strip().casefold() else [entered_name]
    profile = voice_profiles.create_profile(profiles_root, full_name, aliases=aliases)
    profiles.append(profile)
    updates.append({'type': 'profile_created', 'profile_dir': profile.get('profile_dir'), 'aliases': aliases})
    print(f'Создан профиль: {profile["profile_dir"]}')
    return profile, updates


def maybe_add_phone(profile: dict, call_meta: dict) -> dict | None:
    phone = call_meta.get('phone_e164')
    if not phone or voice_profiles.phone_valid_for_profile(profile, phone, call_meta.get('call_datetime')):
        return None
    if not ask_yes_no(f'Добавить телефон {phone} к профилю {profile.get("full_name") or profile.get("person_id")} бессрочно?', default=False):
        return None
    return voice_profiles.add_phone_binding(profile, phone, observed_at=call_meta.get('call_datetime'))


def ask_speaker_name(label: str, spans: list[dict], audio: Path, player: str, debug_no_play: bool) -> tuple[str, dict | None]:
    if not spans:
        print(f'Нет подходящих фрагментов для {label}.')
        return 'UNKNOWN', None
    idx = 0
    while True:
        span = spans[idx]
        print(f'{label}: {span["start"]:.3f}-{span["end"]:.3f} {span.get("text","")[:120]}')
        if not debug_no_play:
            played=playback.play_segment(audio,float(span['start']),float(span['end']),player=player)
            if not played: print('Не найден ffplay/mpv: фрагмент не проигран, показан только таймкод.')
        ans=read_prompt_utf8('Имя / unknown / skip / bad / Enter=следующий фрагмент: ').strip()
        low = ans.lower()
        if low in {'unknown','непонятно','skip'}:
            return 'UNKNOWN', None
        if ans and low not in {'next','bad'}:
            return ans, span
        idx += 1
        if idx >= len(spans):
            print(f'Фрагменты для {label} закончились.')
            if ask_yes_no('Перейти к следующему speaker?', default=True):
                return 'UNKNOWN', None
            idx = 0


def main() -> int:
    args=build_parser().parse_args(); merged_p=Path(args.merged); audio=Path(args.audio); merged=io_utils.read_json(merged_p); source_mp3=merged.get('source_mp3') or audio.name; base=artifacts.base_name(Path(source_mp3))
    artifacts.ensure_dirs(ROOT); stage=artifacts.stage_dir(ROOT/'data','07','speakers'); stem=f'{base}.speakers.manual'
    existing=artifacts.latest_versioned_path(stage,stem,'.json') if not args.new_version else None
    if existing and existing.exists(): print(existing); return 0
    if not args.ci_non_interactive:
        enable_utf8_erase()
    profiles_root=Path(args.voice_profiles_dir)
    profiles_root.mkdir(parents=True, exist_ok=True)
    call_meta=voice_profiles.parse_call_filename(source_mp3)
    profiles=voice_profiles.load_profiles(profiles_root)
    phone_resolution=voice_profiles.resolve_phone_profiles(profiles,call_meta.get('phone_e164'),call_meta.get('call_datetime'))
    original_mp3=voice_profiles.find_source_mp3(ROOT, source_mp3, args.source_mp3)
    labels=sorted({s.get('speaker_label') for s in merged.get('segments',[]) if str(s.get('speaker_label','')).startswith('SPEAKER_')})
    assignments={}; enrolled_samples=[]; profile_updates=[]; auto_match_reports=[]
    for label in labels:
        spans=choose_spans(merged.get('segments',[]),label,args.max_samples_per_speaker)
        auto_report=voice_profiles.auto_match_placeholder(profiles_root, phone_resolution)
        auto_match_reports.append({'speaker_label': label, **auto_report})
        name='UNKNOWN'; evidence=None; method='manual_uncertain'
        selected_span=None
        if not args.ci_non_interactive:
            name, selected_span = ask_speaker_name(label, spans, audio, args.player, args.debug_no_play)
        if name != 'UNKNOWN' and selected_span is not None:
            profile, updates = select_or_create_profile(profiles_root, profiles, name, call_meta, args.confirm_existing_profiles)
            if profile:
                phone_added = maybe_add_phone(profile, call_meta)
                if phone_added:
                    updates.append({'type': 'phone_added', 'phone': phone_added})
                saved = None
                if original_mp3:
                    saved = voice_profiles.save_enrolled_mp3_sample(profile=profile,source_mp3_path=original_mp3,source_mp3=source_mp3,speaker_label=label,span=selected_span,call_meta=call_meta)
                    enrolled_samples.append({**saved,'speaker_label':label,'person_id':profile.get('person_id')})
                else:
                    print('Предупреждение: original mp3 не найден, enrolled sample не сохранён.', file=sys.stderr)
                evidence={'source_audio':str(audio),'source_mp3_sample_source':str(original_mp3) if original_mp3 else None,'start':selected_span['start'],'end':selected_span['end'],'note':'пользователь подтвердил по прослушиванию','person_id':profile.get('person_id'),'enrolled_sample':saved}
                method='manual_voice_confirmation'
                if updates:
                    profile_updates.append({'person_id': profile.get('person_id'), 'profile_dir': profile.get('profile_dir'), 'updates': updates})
            else:
                evidence={'source_audio':str(audio),'start':selected_span['start'],'end':selected_span['end'],'note':'пользователь подтвердил имя, но профиль не выбран'}
                method='manual_voice_confirmation_without_profile'
        assignments[label]={'name':name,'method':method,'evidence':evidence}
    v=artifacts.next_version(stage,stem,'.json'); out=artifacts.versioned_path(stage,stem,'.json',v); man=artifacts.manifest_for(out)
    data={'artifact':str(out),'stage':'07_speakers','source_mp3':source_mp3,'scope':'file-local','created_at':io_utils.utc_now(),'source_metadata':call_meta,'voice_profiles_dir':str(profiles_root),'phone_resolution':phone_resolution,'auto_match_reports':auto_match_reports,'profile_updates':profile_updates,'enrolled_samples':enrolled_samples,'assignments':assignments}
    io_utils.write_json(out,data); outputs=[{'path':str(out),'sha256':io_utils.sha256_file(out)}]
    for sample in enrolled_samples:
        outputs.append({'path':sample['sample'],'sha256':io_utils.sha256_file(Path(sample['sample']))})
        outputs.append({'path':sample['metadata'],'sha256':io_utils.sha256_file(Path(sample['metadata']))})
    for update in profile_updates:
        p = Path(update['profile_dir'])/'profile.json'
        outputs.append({'path':str(p),'sha256':io_utils.sha256_file(p)})
    io_utils.write_json(man,{'stage':'07_speakers','script':'scripts/07_name_speakers.py','input_artifacts':[{'path':str(merged_p),'sha256':io_utils.sha256_file(merged_p)},{'path':str(audio),'sha256':io_utils.sha256_file(audio)}],'output_artifacts':outputs,'created_at':io_utils.utc_now()})
    print(out); return 0
if __name__=='__main__': raise SystemExit(main())
