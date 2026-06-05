# step_description: immutable artifact pipeline

Документ описывает текущую file-first реализацию pipeline для абстрактного файла:

```text
sound.mp3
```

Главное правило:

```text
После успешного завершения шага его artifact не изменяется.
Следующий шаг только читает artifacts предыдущих шагов и создаёт новый artifact.
Если данные нужно изменить, создаётся новая версия artifact: v2, v3, ...
```

Artifacts хранятся в:

```text
data/artifacts/<номер>_<имя_шага>/
```

Номер шага совпадает с номером скрипта.

---

## Шаг 00. Doctor / проверка окружения

Скрипт:

```text
scripts/00_doctor.py
```

Что делает:

- проверяет `ffmpeg` и `ffprobe`;
- проверяет наличие исходного mp3;
- проверяет наличие `token.txt`, не печатая token;
- проверяет модели в `data/models-cache/`;
- проверяет доступность библиотек `faster_whisper`, `torch`, `nemo`, `pyannote.audio`;
- проверяет CUDA через torch, если torch доступен.

Входы:

```text
/mnt/shared/sound/sound.mp3
data/models-cache/
token.txt
Python/uv environment
ffmpeg/ffprobe
```

Outputs:

```text
data/artifacts/00_doctor/sound.doctor.v1.json
data/artifacts/00_doctor/sound.doctor.v1.manifest.json
```

---

## Шаг 01. Prepare input / рабочая копия mp3

Скрипт:

```text
scripts/01_prepare_input.py
```

Что делает:

- копирует исходный mp3 во внутреннее immutable-хранилище;
- проверяет sha256 исходника и копии;
- получает duration/format через `ffprobe`;
- создаёт manifest.

Вход:

```text
/mnt/shared/sound/sound.mp3
```

Outputs:

```text
data/artifacts/01_input/sound.input.v1.mp3
data/artifacts/01_input/sound.input.v1.manifest.json
```

---

## Шаг 02. Make audio variant / нормализованный WAV

Скрипт:

```text
scripts/02_make_audio_variant.py
```

Что делает:

- читает artifact шага 01;
- через `ffmpeg` создаёт WAV 16kHz mono для ASR и diarization;
- сохраняет manifest с входным hash, командой ffmpeg, duration и output hash.

Вход:

```text
data/artifacts/01_input/sound.input.v1.mp3
```

Outputs:

```text
data/artifacts/02_audio/sound.audio.normalized.v1.wav
data/artifacts/02_audio/sound.audio.normalized.v1.manifest.json
```

---

## Шаг 03. ASR smoke compare / выбор ASR backend

Скрипт:

```text
scripts/03_asr_smoke_compare.py
```

Что делает:

- проверяет ASR backend-ы на коротком временном фрагменте audio artifact;
- временный sample создаётся только во временной директории и не сохраняется как artifact;
- фиксирует найденные модели и выбирает рабочий ASR backend.

Текущая логика:

- `nvidia/parakeet-tdt-0.6b-v3` фиксируется как найденный, но `no_timestamps`, потому что timestamp API для NeMo ещё не реализован;
- `nvidia/canary-1b-v2` фиксируется как найденный, но `no_timestamps` по той же причине;
- `Systran/faster-whisper-large-v3` реально запускается и выбирается как рабочий ASR backend.

Вход:

```text
data/artifacts/02_audio/sound.audio.normalized.v1.wav
```

Outputs:

```text
data/artifacts/03_asr_smoke/sound.asr-smoke.v1.json
data/artifacts/03_asr_smoke/sound.asr-smoke.v1.manifest.json
```

---

## Шаг 04. Transcribe / полный ASR

Скрипт:

```text
scripts/04_transcribe.py
```

Что делает:

- читает audio artifact и smoke report;
- выбирает ASR model;
- распознаёт весь файл на русском языке;
- сохраняет raw output и normalized segments;
- не перефразирует и не улучшает текст.

Входы:

```text
data/artifacts/02_audio/sound.audio.normalized.v1.wav
data/artifacts/03_asr_smoke/sound.asr-smoke.v1.json
```

Outputs:

```text
data/artifacts/04_asr/sound.asr.Systran_faster-whisper-large-v3.raw.v1.json
data/artifacts/04_asr/sound.asr.Systran_faster-whisper-large-v3.segments.v1.json
data/artifacts/04_asr/sound.asr.Systran_faster-whisper-large-v3.v1.manifest.json
```

---

## Шаг 05. Diarize / разделение говорящих

Скрипт:

```text
scripts/05_diarize.py
```

Что делает:

- читает audio artifact;
- берёт token из `token.txt`, не печатая token;
- запускает `pyannote/speaker-diarization-3.1`;
- сохраняет raw diarization и normalized speaker segments.

Diarization не читает ASR и не зависит от текста.

Входы:

```text
data/artifacts/02_audio/sound.audio.normalized.v1.wav
token.txt
```

Outputs:

```text
data/artifacts/05_diarization/sound.diarization.pyannote_speaker-diarization-3.1.raw.v1.json
data/artifacts/05_diarization/sound.diarization.pyannote_speaker-diarization-3.1.segments.v1.json
data/artifacts/05_diarization/sound.diarization.pyannote_speaker-diarization-3.1.v1.manifest.json
```

---

## Шаг 06. Merge ASR + diarization

Скрипт:

```text
scripts/06_merge_asr_diarization.py
```

Что делает:

- читает ASR segments и diarization segments;
- считает пересечения по времени;
- назначает speaker label по максимальному overlap;
- добавляет uncertainty markers при неоднозначности.

Возможные markers:

```text
NO_SPEAKER
MIXED
OVERLAP
UNCERTAIN
```

ASR и diarization artifacts не изменяются.

Входы:

```text
data/artifacts/04_asr/sound.asr.Systran_faster-whisper-large-v3.segments.v1.json
data/artifacts/05_diarization/sound.diarization.pyannote_speaker-diarization-3.1.segments.v1.json
```

Outputs:

```text
data/artifacts/06_merge/sound.merge.Systran_faster-whisper-large-v3.pyannote_speaker-diarization-3.1.v1.json
data/artifacts/06_merge/sound.merge.Systran_faster-whisper-large-v3.pyannote_speaker-diarization-3.1.v1.manifest.json
```

---

## Шаг 07. Voice identification / автоматическое сопоставление голосов

Скрипт:

```text
scripts/07_voice_identification.py
```

Что делает:

- читает merge artifact;
- находит локальные `SPEAKER_XX`;
- извлекает телефон и дату звонка из имени исходного файла, если они есть;
- загружает voice profiles из `data/voice_profiles/`;
- сначала сравнивает голосовые фрагменты каждого `SPEAKER_XX` с confirmed enrolled samples;
- использует `pyannote/embedding` как backend speaker embeddings;
- не использует телефон/дату для выбора результата: best match выбирается только по voice score;
- сохраняет candidates, best match, score, threshold decision и backend status;
- не спрашивает пользователя и не изменяет profiles.

Возможные статусы speaker match:

```text
matched
needs_confirmation
no_match
no_samples
no_candidate_span
backend_unavailable
error
```

Входы:

```text
data/artifacts/06_merge/sound.merge...v1.json
data/artifacts/02_audio/sound.audio.normalized.v1.wav или input mp3
data/voice_profiles/<person_id>/samples/enrolled/*.mp3
token.txt для pyannote/HF, если нужен
```

Outputs:

```text
data/artifacts/07_voice_identification/sound.voice-id.pyannote-embedding.v1.json
data/artifacts/07_voice_identification/sound.voice-id.pyannote-embedding.v1.manifest.json
```

---

## Шаг 08. Name speakers / ручное назначение оставшихся имён

Скрипт:

```text
scripts/08_name_speakers.py
```

Что делает:

- читает merge artifact и voice identification artifact;
- автоматически переносит только `matched` из шага 07 в file-local mapping;
- для `needs_confirmation`, `no_match`, `no_samples`, `backend_unavailable` и других нерешённых статусов проигрывает фрагменты текущего speaker по одному;
- Enter / `next` / `bad` означает следующий фрагмент этого же speaker;
- когда фрагменты текущего speaker закончились, спрашивает, переходить ли к следующему; если ответ `нет`, начинает список фрагментов этого speaker заново;
- если пользователь ввёл имя, ищет профиль по имени/alias;
- если найден ровно один профиль, использует его автоматически; флаг `--confirm-existing-profiles` включает ручное подтверждение;
- если профиль выбран, а введённого alias там нет, добавляет alias автоматически;
- если профиля нет, предлагает создать профиль;
- если из filename извлечён телефон, спрашивает, добавлять ли его к профилю; при согласии даты начала/окончания остаются пустыми, то есть связь бессрочная;
- если пользователь вручную распознал speaker, сохраняет физический enrolled sample в mp3 из original/input mp3 artifact;
- если speaker auto-распознался на шаге 07, sample не сохраняется;
- если пользователь ответил `unknown`/`skip`, ничего не сохраняется в voice profiles.

Voice profile storage:

```text
data/voice_profiles/
  <person_id>/
    profile.json
    samples/
      enrolled/
        <sample_id>.mp3
        <sample_id>.json
```

Имена сохраняются в file-local mapping. Merge и voice-id artifacts не изменяются.

Интерактивный ввод:

- плеер не наследует stdin prompt-а;
- перед вводом включается `IUTF8`, если доступно, чтобы Backspace корректно стирал UTF-8 символы;
- malformed UTF-8 во вводе не валит процесс: битые байты отбрасываются с warning и raw hex.

`--ci-non-interactive` — только для CI/end-to-end проверки: не проигрывает audio и оставляет unresolved speakers `UNKNOWN`.

Входы:

```text
data/artifacts/06_merge/sound.merge...v1.json
data/artifacts/07_voice_identification/sound.voice-id.pyannote-embedding.v1.json
data/artifacts/02_audio/sound.audio.normalized.v1.wav
ответы пользователя
```

Outputs:

```text
data/artifacts/08_speakers/sound.speakers.manual.v1.json
data/artifacts/08_speakers/sound.speakers.manual.v1.manifest.json
data/voice_profiles/<person_id>/profile.json
data/voice_profiles/<person_id>/samples/enrolled/<sample_id>.mp3
data/voice_profiles/<person_id>/samples/enrolled/<sample_id>.json
```

---

## Шаг 09. Export transcript / человекочитаемый transcript

Скрипт:

```text
scripts/09_export_transcript.py
```

Что делает:

- читает merge artifact и speakers artifact;
- подставляет подтверждённые имена вместо `SPEAKER_XX`;
- сохраняет `UNKNOWN`, `NO_SPEAKER`, `MIXED`, `OVERLAP` там, где имя не подтверждено;
- создаёт человекочитаемый transcript.

Формат строки:

```text
HH:MM:SS.mmm | speaker | text
```

Merge и speakers artifacts не изменяются.

Входы:

```text
data/artifacts/06_merge/sound.merge...v1.json
data/artifacts/08_speakers/sound.speakers.manual.v1.json
```

Outputs:

```text
data/artifacts/09_transcript/sound.transcript.with-names.v1.txt
data/artifacts/09_transcript/sound.transcript.with-names.v1.manifest.json
```

---

## Шаг 10. Role consistency review / LLM-проверка согласованности ролей

Скрипт:

```text
scripts/10_role_consistency_review.py
```

Что делает:

- читает merge, speakers и transcript;
- вызывает реальный LLM через Hermes CLI;
- просит LLM найти кандидаты, где текущий говорящий плохо согласуется с соседним контекстом диалога;
- не использует заранее заданные доменные правила, списки фраз, шаблоны или хардкод;
- считает имена/labels непрозрачными идентификаторами;
- не исправляет данные автоматически;
- сохраняет structured JSON review;
- сохраняет raw LLM response рядом с artifact.

Входы:

```text
data/artifacts/06_merge/sound.merge...v1.json
data/artifacts/08_speakers/sound.speakers.manual.v1.json
data/artifacts/09_transcript/sound.transcript.with-names.v1.txt
```

Outputs:

```text
data/artifacts/10_role_consistency_review/sound.role-consistency-review.hermes.v1.json
data/artifacts/10_role_consistency_review/sound.role-consistency-review.hermes.v1.raw.txt
data/artifacts/10_role_consistency_review/sound.role-consistency-review.hermes.v1.manifest.json
```

Шаг 10 является derived review layer. Он не меняет speaker mapping. Применение кандидатов должно быть отдельным ручным шагом.

---

## Шаг 11. Build voice profile embeddings / cache для voice profiles

Скрипт:

```text
scripts/11_build_voice_profile_embeddings.py
```

Что делает:

- читает confirmed enrolled samples из `data/voice_profiles/<person_id>/samples/enrolled/`;
- строит или обновляет unified embedding cache;
- поддерживает backend-и `pyannote`, `ecapa` или `all`;
- может мигрировать legacy cache;
- не назначает speaker labels и не спрашивает пользователя.

Входы:

```text
data/voice_profiles/<person_id>/samples/enrolled/*.mp3
token.txt для pyannote/HF, если нужен
```

Outputs:

```text
data/voice_profiles/<person_id>/voice_embeddings/<backend>/<model>/<sample>.json
data/artifacts/11_voice_profile_embeddings/voice-profile-embeddings.v1.json
data/artifacts/11_voice_profile_embeddings/voice-profile-embeddings.v1.manifest.json
```

---

## Шаг 99. Check pipeline outputs / проверка обязательных outputs

Скрипт:

```text
scripts/99_check_pipeline_outputs.py
```

Что делает:

- проверяет, что обязательные artifacts шагов `01`–`11` существуют и валидны;
- проверяет JSON на валидность;
- проверяет, что transcript txt не пустой;
- создаёт check artifact.

Входы:

```text
latest artifacts шагов 01–11
```

Output:

```text
data/artifacts/99_check/sound.pipeline-check.v1.json
```

---

## Примеры запуска

В примерах ниже `BASE` — имя mp3 без расширения.

```bash
MP3='/mnt/shared/sound/Яна Ситникова(0079263717233)_20260509182759.mp3'
BASE="$(basename "$MP3" .mp3)"
```

Отдельные команды по скриптам:

```bash
# 00: проверка окружения
uv run python scripts/00_doctor.py --source-mp3 "$MP3"

# 01: рабочая immutable-копия mp3
uv run python scripts/01_prepare_input.py "$MP3"

# 02: нормализованный WAV
uv run python scripts/02_make_audio_variant.py "data/artifacts/01_input/${BASE}.input.v1.mp3"

# 03: ASR smoke compare
uv run python scripts/03_asr_smoke_compare.py "data/artifacts/02_audio/${BASE}.audio.normalized.v1.wav"

# 04: полный ASR
uv run python scripts/04_transcribe.py \
  "data/artifacts/02_audio/${BASE}.audio.normalized.v1.wav" \
  --smoke-report "data/artifacts/03_asr_smoke/${BASE}.asr-smoke.v1.json"

# 05: diarization
uv run python scripts/05_diarize.py "data/artifacts/02_audio/${BASE}.audio.normalized.v1.wav"

# 06: merge ASR + diarization
uv run python scripts/06_merge_asr_diarization.py \
  "data/artifacts/04_asr/${BASE}.asr.Systran_faster-whisper-large-v3.segments.v1.json" \
  "data/artifacts/05_diarization/${BASE}.diarization.pyannote_speaker-diarization-3.1.segments.v1.json"

# 07: основной voice-id backend pyannote/embedding
uv run python scripts/07_voice_identification.py \
  "data/artifacts/06_merge/${BASE}.merge.Systran_faster-whisper-large-v3.pyannote_speaker-diarization-3.1.v1.json" \
  --audio "data/artifacts/02_audio/${BASE}.audio.normalized.v1.wav"

# 07_1: экспериментальный diagnostic backend SpeechBrain ECAPA
uv run python scripts/07_1_voice_identification_ecapa.py \
  "data/artifacts/06_merge/${BASE}.merge.Systran_faster-whisper-large-v3.pyannote_speaker-diarization-3.1.v1.json" \
  --audio "data/artifacts/02_audio/${BASE}.audio.normalized.v1.wav"

# 08: ручное назначение имён. Запускать только вручную пользователем.
uv run python scripts/08_name_speakers.py \
  "data/artifacts/06_merge/${BASE}.merge.Systran_faster-whisper-large-v3.pyannote_speaker-diarization-3.1.v1.json" \
  "data/artifacts/07_voice_identification/${BASE}.voice-id.pyannote-embedding.v1.json" \
  --audio "data/artifacts/02_audio/${BASE}.audio.normalized.v1.wav"

# 09: экспорт transcript
uv run python scripts/09_export_transcript.py \
  "data/artifacts/06_merge/${BASE}.merge.Systran_faster-whisper-large-v3.pyannote_speaker-diarization-3.1.v1.json" \
  "data/artifacts/08_speakers/${BASE}.speakers.manual.v1.json"

# 10: LLM role-consistency review, без автоправок
uv run python scripts/10_role_consistency_review.py \
  "data/artifacts/06_merge/${BASE}.merge.Systran_faster-whisper-large-v3.pyannote_speaker-diarization-3.1.v1.json" \
  "data/artifacts/08_speakers/${BASE}.speakers.manual.v1.json" \
  "data/artifacts/09_transcript/${BASE}.transcript.with-names.v1.txt"

# 11: пересборка embedding cache для voice profiles
uv run python scripts/11_build_voice_profile_embeddings.py --backend all

# 99: итоговая проверка обязательных artifacts
uv run python scripts/99_check_pipeline_outputs.py "$MP3"
```

### Общий запуск до ручного шага 08

Эта команда выполняет все неинтерактивные шаги до `08_name_speakers.py`: `00` → `07`.
Она не запускает `08`, потому что там нужно слушать фрагменты и вводить имена.

```bash
set -euo pipefail
MP3='/mnt/shared/sound/Яна Ситникова(0079263717233)_20260509182759.mp3'
BASE="$(basename "$MP3" .mp3)"

uv run python scripts/00_doctor.py --source-mp3 "$MP3"
uv run python scripts/01_prepare_input.py "$MP3"
uv run python scripts/02_make_audio_variant.py "data/artifacts/01_input/${BASE}.input.v1.mp3"
uv run python scripts/03_asr_smoke_compare.py "data/artifacts/02_audio/${BASE}.audio.normalized.v1.wav"
uv run python scripts/04_transcribe.py \
  "data/artifacts/02_audio/${BASE}.audio.normalized.v1.wav" \
  --smoke-report "data/artifacts/03_asr_smoke/${BASE}.asr-smoke.v1.json"
uv run python scripts/05_diarize.py "data/artifacts/02_audio/${BASE}.audio.normalized.v1.wav"
uv run python scripts/06_merge_asr_diarization.py \
  "data/artifacts/04_asr/${BASE}.asr.Systran_faster-whisper-large-v3.segments.v1.json" \
  "data/artifacts/05_diarization/${BASE}.diarization.pyannote_speaker-diarization-3.1.segments.v1.json"
uv run python scripts/07_voice_identification.py \
  "data/artifacts/06_merge/${BASE}.merge.Systran_faster-whisper-large-v3.pyannote_speaker-diarization-3.1.v1.json" \
  --audio "data/artifacts/02_audio/${BASE}.audio.normalized.v1.wav"
```

Дальше остановка на ручном gate:

```bash
uv run python scripts/08_name_speakers.py \
  "data/artifacts/06_merge/${BASE}.merge.Systran_faster-whisper-large-v3.pyannote_speaker-diarization-3.1.v1.json" \
  "data/artifacts/07_voice_identification/${BASE}.voice-id.pyannote-embedding.v1.json" \
  --audio "data/artifacts/02_audio/${BASE}.audio.normalized.v1.wav"
```

Интерактивные/ручные шаги запускает только пользователь в своём терминале и аудио-окружении. Агент не должен скрыто проходить `08_name_speakers.py` за пользователя.

---

## Общая связь шагов

```text
00_doctor
   │
   ▼
01_prepare_input
   │
   ▼
02_make_audio_variant
   │
   ├───────────────┬────────────────────┐
   ▼               ▼                    ▼
03_asr_smoke   04_transcribe        05_diarize
                   │                    │
                   └─────────┬──────────┘
                             ▼
                         06_merge
                             │
             ┌───────────────┴────────────────┐
             ▼                                ▼
   07_voice_identification          07_1_voice_identification_ecapa
             │                       diagnostic optional branch
             ▼
      08_name_speakers
      ручной интерактивный gate
             │
             ▼
        09_transcript
             │
             ▼
  10_role_consistency_review

11_build_voice_profile_embeddings читает data/voice_profiles и может запускаться отдельно после enrollment.
99_check проверяет обязательные artifacts 01–11.
```

Точнее:

```text
04_transcribe читает:
- 02 audio artifact
- 03 smoke report, если модель не передана явно

05_diarize читает:
- 02 audio artifact

06_merge читает:
- 04 ASR segments
- 05 diarization segments

07_voice_identification читает:
- 06 merge
- 02 audio/input artifact для embedding фрагментов
- data/voice_profiles confirmed enrolled samples

08_speakers читает:
- 06 merge
- 07 voice_identification
- 02 audio artifact для проигрывания нерешённых фрагментов

09_transcript читает:
- 06 merge
- 08 speakers

10_role_consistency_review читает:
- 06 merge
- 08 speakers
- 09 transcript

07_1_voice_identification_ecapa читает:
- 06 merge
- 02 audio artifact для embedding фрагментов
- data/voice_profiles confirmed enrolled samples

99_check читает:
- latest artifacts обязательных шагов 01–11
- 10 role_consistency_review
- 11 voice_profile_embeddings

10_role_consistency_review читает:
- 06 merge
- 08 speakers
- 09 transcript
- текущую Hermes model/provider config для реального LLM-вызова

11_build_voice_profile_embeddings читает:
- data/voice_profiles confirmed enrolled samples
```

---

## Что происходит при изменении

### Если нужно заново выполнить шаг с другими параметрами

Старый artifact не меняется.

Создаётся новая версия:

```text
sound.<stage>.<details>.v2.json
sound.<stage>.<details>.v2.manifest.json
```

### Если поменяли ASR-модель

Старый ASR artifact остаётся:

```text
data/artifacts/04_asr/sound.asr.Systran_faster-whisper-large-v3.segments.v1.json
```

Новый ASR создаётся отдельно:

```text
data/artifacts/04_asr/sound.asr.nvidia_parakeet-tdt-0.6b-v3.segments.v1.json
```

Потом создаются новые downstream artifacts.

### Если поменяли имя говорящего

Старый speakers artifact остаётся:

```text
data/artifacts/08_speakers/sound.speakers.manual.v1.json
```

Новый:

```text
data/artifacts/08_speakers/sound.speakers.manual.v2.json
```

Потом создаётся новый transcript:

```text
data/artifacts/09_transcript/sound.transcript.with-names.v2.txt
```

### Если LLM-review нашёл кандидаты

Старые artifacts не меняются.

Review сохраняется как отдельный derived artifact:

```text
data/artifacts/10_role_consistency_review/sound.role-consistency-review.hermes.vN.json
```

Применение кандидатов — отдельное ручное решение и отдельный будущий шаг.
