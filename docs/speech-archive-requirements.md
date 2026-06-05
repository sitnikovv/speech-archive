# ТЗ: speech-archive

## 1. Назначение

Создать локальный файловый конвейер обработки архива русскоязычных телефонных MP3-записей.

Система должна позволять:

- сохранять исходное аудио неизменным;
- создавать рабочие audio-варианты для моделей;
- распознавать речь дословно с таймкодами;
- выполнять diarization: определять локальные `SPEAKER_XX` по времени;
- сопоставлять локальные голоса с подтверждёнными voice profiles;
- вручную назначать оставшиеся имена говорящих;
- сохранять подтверждённые voice samples только после ручного подтверждения;
- экспортировать transcript по ролям;
- выполнять LLM-review согласованности ролей/говорящих без автоправок;
- пересобирать voice-profile embedding cache;
- проверять наличие и валидность обязательных artifacts.

Текущая реализация — file-first pipeline без SQLite, без web UI и без единого большого приложения.

## 2. Главный принцип

Исходный MP3 и первичные результаты моделей являются evidence-данными.

Запрещено заменять исходное аудио или raw outputs моделей исправленными, объединёнными, очищенными, “улучшенными” или литературными версиями.

Все исправления, объединения, назначения говорящих, transcript-файлы, review-кандидаты и checks являются отдельными производными artifacts.

Успешный artifact не перезаписывается. Повторный запуск создаёт новую версию `vN`, если передан `--new-version`, или пропускает уже готовый результат.

## 3. Текущая архитектура

Проект строится как набор независимых CLI-скриптов:

| Шаг | Скрипт | Назначение |
| --- | --- | --- |
| 00 | `scripts/00_doctor.py` | Проверка окружения, моделей, token и CUDA. |
| 01 | `scripts/01_prepare_input.py` | Рабочая immutable-копия входного MP3. |
| 02 | `scripts/02_make_audio_variant.py` | Нормализованный WAV для моделей. |
| 03 | `scripts/03_asr_smoke_compare.py` | Smoke-сравнение ASR backend. |
| 04 | `scripts/04_transcribe.py` | Полный ASR. |
| 05 | `scripts/05_diarize.py` | Diarization. |
| 06 | `scripts/06_merge_asr_diarization.py` | Merge ASR + diarization. |
| 07 | `scripts/07_voice_identification.py` | Основной pyannote voice identification. |
| 07_1 | `scripts/07_1_voice_identification_ecapa.py` | Экспериментальный ECAPA diagnostic backend. |
| 08 | `scripts/08_name_speakers.py` | Ручное назначение оставшихся имён и enrollment. |
| 09 | `scripts/09_export_transcript.py` | Transcript with names. |
| 10 | `scripts/10_role_consistency_review.py` | LLM role-consistency review, без автоправок. |
| 11 | `scripts/11_build_voice_profile_embeddings.py` | Пересборка/migration voice-profile embedding cache. |
| 99 | `scripts/99_check_pipeline_outputs.py` | Итоговая проверка обязательных outputs. |

Общая схема:

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

## 4. Примеры запуска

В примерах ниже `BASE` — имя MP3 без расширения.

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

## 5. Рабочая структура файлов

Основная рабочая папка проекта:

```text
/home/sve/hermesLab/speech-archive
```

В проекте сохраняются:

```text
docs/speech-archive-requirements.md
docs/step_description.md
README.md
token.txt                         # Hugging Face / pyannote token, не печатать
scripts/                          # отдельные stage scripts
speech_archive_lib/               # общий код, если нужен нескольким scripts
data/models-cache/                # локальные model caches
data/artifacts/<NN_stage_name>/   # immutable artifacts по стадиям
data/voice_profiles/<person_id>/  # profiles, enrolled samples, embedding cache
```

Stage directories:

```text
data/artifacts/00_doctor/
data/artifacts/01_input/
data/artifacts/02_audio/
data/artifacts/03_asr_smoke/
data/artifacts/04_asr/
data/artifacts/05_diarization/
data/artifacts/06_merge/
data/artifacts/07_voice_identification/
data/artifacts/07_1_voice_identification_ecapa/
data/artifacts/08_speakers/
data/artifacts/09_transcript/
data/artifacts/10_role_consistency_review/
data/artifacts/11_voice_profile_embeddings/
data/artifacts/99_check/
```

## 6. Имена файлов

Все производные файлы называются от имени оригинального MP3 без расширения.

Пример исходного файла:

```text
Яна Ситникова(0079263717233)_20260509182759.mp3
```

Примеры текущих artifact names:

```text
data/artifacts/01_input/<base>.input.v1.mp3
data/artifacts/01_input/<base>.input.v1.manifest.json
data/artifacts/02_audio/<base>.audio.normalized.v1.wav
data/artifacts/02_audio/<base>.audio.normalized.v1.manifest.json
data/artifacts/03_asr_smoke/<base>.asr-smoke.v1.json
data/artifacts/04_asr/<base>.asr.<model>.raw.v1.json
data/artifacts/04_asr/<base>.asr.<model>.segments.v1.json
data/artifacts/04_asr/<base>.asr.<model>.v1.manifest.json
data/artifacts/05_diarization/<base>.diarization.<model>.raw.v1.json
data/artifacts/05_diarization/<base>.diarization.<model>.segments.v1.json
data/artifacts/05_diarization/<base>.diarization.<model>.v1.manifest.json
data/artifacts/06_merge/<base>.merge.<asr-model>.<diarization-model>.v1.json
data/artifacts/06_merge/<base>.merge.<asr-model>.<diarization-model>.v1.manifest.json
data/artifacts/07_voice_identification/<base>.voice-id.pyannote-embedding.v1.json
data/artifacts/07_voice_identification/<base>.voice-id.pyannote-embedding.v1.manifest.json
data/artifacts/07_1_voice_identification_ecapa/<base>.voice-id.ecapa.v1.json
data/artifacts/08_speakers/<base>.speakers.manual.v1.json
data/artifacts/08_speakers/<base>.speakers.manual.v1.manifest.json
data/artifacts/09_transcript/<base>.transcript.with-names.v1.txt
data/artifacts/09_transcript/<base>.transcript.with-names.v1.manifest.json
data/artifacts/10_role_consistency_review/<base>.role-consistency-review.hermes.v1.json
data/artifacts/10_role_consistency_review/<base>.role-consistency-review.hermes.v1.raw.txt
data/artifacts/10_role_consistency_review/<base>.role-consistency-review.hermes.v1.manifest.json
data/artifacts/11_voice_profile_embeddings/voice-profile-embeddings.v1.json
data/artifacts/99_check/<base>.pipeline-check.v1.json
```

Model id в имени файла должен быть безопасным для файловой системы: `/`, пробелы и специальные символы заменяются на `_` или `-`.

## 7. Доступные модели и backend-и

ASR:

- основной текущий backend: `Systran/faster-whisper-large-v3`;
- `nvidia/parakeet-tdt-0.6b-v3` и `nvidia/canary-1b-v2` могут фиксироваться smoke-report как найденные, но без usable timestamp API для текущей реализации;
- `faster-whisper-small` допустим только как быстрый fallback/smoke, не как основной качественный результат.

Diarization:

- `pyannote/speaker-diarization-3.1`;
- token читается из `token.txt` и не печатается.

Voice identification:

- основной stage `07`: `pyannote/embedding`;
- diagnostic stage `07_1`: SpeechBrain ECAPA;
- телефон/дата из имени файла могут сохраняться как metadata, но не должны выбирать best match вместо voice score.

## 8. Требования по шагам

### Шаг 00. Doctor

`scripts/00_doctor.py` должен проверять:

- `ffmpeg`/`ffprobe`;
- наличие source MP3, если передан `--source-mp3`;
- наличие `token.txt`, не печатая token;
- model cache directories;
- импорты нужных библиотек;
- CUDA через torch, если torch доступен.

Outputs:

```text
data/artifacts/00_doctor/<base>.doctor.v1.json
data/artifacts/00_doctor/<base>.doctor.v1.manifest.json
```

### Шаг 01. Prepare input

`scripts/01_prepare_input.py` должен:

- принять путь к MP3;
- проверить, что это MP3;
- создать рабочую immutable-копию в `data/artifacts/01_input/`;
- посчитать sha256 исходника и копии;
- сохранить manifest.

Outputs:

```text
data/artifacts/01_input/<base>.input.v1.mp3
data/artifacts/01_input/<base>.input.v1.manifest.json
```

### Шаг 02. Make audio variant

`scripts/02_make_audio_variant.py` должен:

- читать artifact шага 01;
- создать WAV 16 kHz mono для ASR/diarization/voice-id;
- сохранить lineage, ffmpeg command, duration и hash.

Outputs:

```text
data/artifacts/02_audio/<base>.audio.normalized.v1.wav
data/artifacts/02_audio/<base>.audio.normalized.v1.manifest.json
```

### Шаг 03. ASR smoke compare

`scripts/03_asr_smoke_compare.py` должен:

- запустить доступные ASR backend-и на коротком фрагменте;
- не сохранять временный фрагмент как evidence artifact;
- выбрать usable ASR backend;
- записать причину выбора.

Outputs:

```text
data/artifacts/03_asr_smoke/<base>.asr-smoke.v1.json
data/artifacts/03_asr_smoke/<base>.asr-smoke.v1.manifest.json
```

### Шаг 04. Transcribe

`scripts/04_transcribe.py` должен:

- читать audio artifact и smoke report или явно заданный `--model`;
- распознавать весь файл на русском языке;
- сохранять raw output и normalized segments;
- не перефразировать и не улучшать текст.

Outputs:

```text
data/artifacts/04_asr/<base>.asr.Systran_faster-whisper-large-v3.raw.v1.json
data/artifacts/04_asr/<base>.asr.Systran_faster-whisper-large-v3.segments.v1.json
data/artifacts/04_asr/<base>.asr.Systran_faster-whisper-large-v3.v1.manifest.json
```

### Шаг 05. Diarize

`scripts/05_diarize.py` должен:

- читать audio artifact;
- использовать `pyannote/speaker-diarization-3.1`;
- читать token из `token.txt`, не печатая token;
- сохранять raw diarization и normalized speaker segments.

Outputs:

```text
data/artifacts/05_diarization/<base>.diarization.pyannote_speaker-diarization-3.1.raw.v1.json
data/artifacts/05_diarization/<base>.diarization.pyannote_speaker-diarization-3.1.segments.v1.json
data/artifacts/05_diarization/<base>.diarization.pyannote_speaker-diarization-3.1.v1.manifest.json
```

### Шаг 06. Merge ASR + diarization

`scripts/06_merge_asr_diarization.py` должен:

- читать ASR segments и diarization segments;
- назначать speaker label по временному overlap;
- сохранять uncertainty markers `NO_SPEAKER`, `MIXED`, `OVERLAP`, `UNCERTAIN` при неоднозначности;
- не менять ASR/diarization artifacts.

Outputs:

```text
data/artifacts/06_merge/<base>.merge.Systran_faster-whisper-large-v3.pyannote_speaker-diarization-3.1.v1.json
data/artifacts/06_merge/<base>.merge.Systran_faster-whisper-large-v3.pyannote_speaker-diarization-3.1.v1.manifest.json
```

### Шаг 07. Voice identification

`scripts/07_voice_identification.py` должен:

- читать merge artifact;
- читать audio artifact для probe spans;
- загружать confirmed enrolled samples из `data/voice_profiles/`;
- вычислять embeddings через `pyannote/embedding`;
- сохранять candidates, score matrix, best match, thresholds и status;
- не спрашивать пользователя;
- не изменять voice profiles.

Возможные статусы:

```text
matched
needs_confirmation
no_match
no_samples
no_candidate_span
backend_unavailable
error
```

Outputs:

```text
data/artifacts/07_voice_identification/<base>.voice-id.pyannote-embedding.v1.json
data/artifacts/07_voice_identification/<base>.voice-id.pyannote-embedding.v1.manifest.json
```

### Шаг 07_1. Voice identification ECAPA diagnostic

`scripts/07_1_voice_identification_ecapa.py` должен:

- читать те же входы, что stage 07;
- использовать SpeechBrain ECAPA backend;
- писать отдельный diagnostic artifact;
- не заменять основной stage 07;
- не делать auto-match обязательным до калибровки.

Outputs:

```text
data/artifacts/07_1_voice_identification_ecapa/<base>.voice-id.ecapa.v1.json
data/artifacts/07_1_voice_identification_ecapa/<base>.voice-id.ecapa.v1.manifest.json
```

### Шаг 08. Name speakers

`scripts/08_name_speakers.py` — ручной интерактивный gate.

Он должен:

- читать merge artifact и voice-id artifact;
- автоматически принять только уверенные `matched` из stage 07;
- для unresolved speakers проигрывать фрагменты и спрашивать пользователя;
- сохранять file-local speaker mapping;
- при ручном подтверждении человека сохранять enrolled sample из source/input MP3;
- не сохранять samples для `unknown`/`skip`;
- не менять merge и voice-id artifacts.

Этот шаг должен запускать пользователь вручную в своём терминале и аудио-окружении.

Outputs:

```text
data/artifacts/08_speakers/<base>.speakers.manual.v1.json
data/artifacts/08_speakers/<base>.speakers.manual.v1.manifest.json
data/voice_profiles/<person_id>/profile.json
data/voice_profiles/<person_id>/samples/enrolled/<sample_id>.mp3
data/voice_profiles/<person_id>/samples/enrolled/<sample_id>.json
```

### Шаг 09. Export transcript

`scripts/09_export_transcript.py` должен:

- читать merge artifact и speakers artifact;
- подставлять подтверждённые имена вместо `SPEAKER_XX`;
- сохранять явные `UNKNOWN`, `NO_SPEAKER`, `MIXED`, `OVERLAP` там, где имя не подтверждено;
- создавать человекочитаемый transcript.

Формат строки:

```text
HH:MM:SS.mmm | speaker | text
```

Outputs:

```text
data/artifacts/09_transcript/<base>.transcript.with-names.v1.txt
data/artifacts/09_transcript/<base>.transcript.with-names.v1.manifest.json
```

### Шаг 10. Role consistency review

`scripts/10_role_consistency_review.py` должен:

- читать merge, speakers и transcript;
- вызвать реальный LLM через Hermes CLI;
- найти candidates, где текущий говорящий плохо согласуется с соседним контекстом;
- не использовать заранее заданные доменные правила, participant facts, phrase lists или хардкод;
- считать names/labels непрозрачными идентификаторами;
- не исправлять данные автоматически;
- сохранять structured JSON review и raw LLM response.

Outputs:

```text
data/artifacts/10_role_consistency_review/<base>.role-consistency-review.hermes.v1.json
data/artifacts/10_role_consistency_review/<base>.role-consistency-review.hermes.v1.raw.txt
data/artifacts/10_role_consistency_review/<base>.role-consistency-review.hermes.v1.manifest.json
```

### Шаг 11. Build voice profile embeddings

`scripts/11_build_voice_profile_embeddings.py` должен:

- читать confirmed enrolled samples из `data/voice_profiles/<person_id>/samples/enrolled/`;
- строить unified embedding cache;
- поддерживать backend-и `pyannote`, `ecapa`, `all`;
- сохранять per-profile embedding files;
- сохранять общий report artifact;
- не спрашивать пользователя.

Outputs:

```text
data/voice_profiles/<person_id>/voice_embeddings/<backend>/<model>/<sample>.json
data/artifacts/11_voice_profile_embeddings/voice-profile-embeddings.v1.json
data/artifacts/11_voice_profile_embeddings/voice-profile-embeddings.v1.manifest.json
```

### Шаг 99. Check pipeline outputs

`scripts/99_check_pipeline_outputs.py` должен проверить latest artifacts обязательных stage outputs:

- 01 input MP3 + manifest;
- 02 audio WAV + manifest;
- 03 ASR smoke JSON;
- 04 ASR raw + segments;
- 05 diarization raw + segments;
- 06 merge;
- 07 voice-id;
- 08 speakers;
- 09 transcript;
- 10 role-consistency review;
- 11 voice-profile embeddings report.

Output:

```text
data/artifacts/99_check/<base>.pipeline-check.v1.json
```

Checker должен печатать `OK` только если обязательные файлы существуют и проходят базовую валидацию. При ошибке он должен указывать конкретный missing/invalid файл и причину.

## 9. Ручные и интерактивные этапы

Интерактивные/ручные этапы нельзя запускать скрыто агентом.

Сейчас ручной gate:

```text
scripts/08_name_speakers.py
```

Причина:

- пользователь должен слышать фрагменты;
- пользователь вводит имена;
- пользователь подтверждает создание/использование voice profile;
- результат влияет на enrollment samples и дальнейшее voice-id качество.

Нормальный запуск:

```bash
uv run python scripts/08_name_speakers.py \
  "data/artifacts/06_merge/${BASE}.merge.Systran_faster-whisper-large-v3.pyannote_speaker-diarization-3.1.v1.json" \
  "data/artifacts/07_voice_identification/${BASE}.voice-id.pyannote-embedding.v1.json" \
  --audio "data/artifacts/02_audio/${BASE}.audio.normalized.v1.wav"
```

`--ci-non-interactive` и `--debug-no-play` допустимы только для CI/debug и должны быть явно помечены как не нормальный пользовательский workflow.

## 10. Voice profiles

Voice profile storage:

```text
data/voice_profiles/
  <person_id>/
    profile.json
    samples/
      enrolled/
        <sample_id>.mp3
        <sample_id>.json
    voice_embeddings/
      <backend>/
        <model>/
          <sample_id>.json
```

Правила:

- `SPEAKER_XX` — file-local label, не глобальный человек;
- profile identity хранится отдельно от file-local assignments;
- confirmed enrolled sample сохраняется только после ручного голосового подтверждения;
- `unknown`/`skip` не создают physical sample;
- phone/date metadata из filename — metadata/prior, но не evidence для выбора voice match;
- embedding cache пересобирается отдельным stage 11.

## 11. Transcript и review

Transcript stage 09 — человекочитаемый текстовый файл, но не замена raw ASR.

Role consistency stage 10 — derived review layer. Он создаёт candidates, но не применяет исправления.

Если review нашёл кандидаты, применение должно быть отдельным ручным решением и отдельным будущим correction artifact. Stage 10 не имеет права менять:

- исходный MP3;
- raw ASR output;
- raw diarization output;
- merge artifact;
- speakers mapping;
- transcript.

## 12. Неопределённость

Система должна явно показывать неопределённость.

Возможные состояния:

- known speaker;
- unknown speaker;
- low confidence;
- `MIXED`;
- `OVERLAP`;
- `NO_SPEAKER`;
- `UNCERTAIN`;
- непригодный фрагмент;
- требуется ручная проверка.

Нельзя выдавать предположение за факт.

## 13. Массовая обработка и повторные запуски

Система должна быть пригодна для пакетной обработки архива MP3.

Скрипты не должны:

- дублировать результаты без необходимости;
- перезаписывать successful artifacts без явного `--new-version`;
- удалять пользовательские данные;
- удалять raw outputs моделей.

Каждый скрипт должен печатать понятный статус:

- что обработано;
- что пропущено, потому что уже готово;
- где ошибка;
- какой output создан.

## 14. Локальность и безопасность

Система должна работать локально.

Запрещено:

- изменять оригиналы;
- удалять пользовательские данные без разрешения;
- скрыто отправлять аудио наружу;
- печатать или сохранять token из `token.txt` в открытом виде;
- принимать внешние лицензии от имени пользователя;
- использовать старый архивированный код проекта как источник логики без отдельного разрешения.

Разрешено:

- использовать уже скачанные локальные модели;
- использовать `token.txt` для доступа к pyannote/Hugging Face;
- создавать производные рабочие файлы внутри проекта.

## 15. Критерий готовности текущей версии

Текущая версия считается готовой для тестового MP3, когда созданы и проходят `99_check_pipeline_outputs.py`:

1. input MP3 artifact и manifest;
2. normalized audio artifact и manifest;
3. ASR smoke report;
4. ASR raw output;
5. ASR normalized segments JSON;
6. diarization raw output;
7. diarization normalized segments JSON;
8. merged ASR + diarization JSON;
9. voice-id JSON;
10. speakers manual JSON;
11. transcript with names TXT;
12. role-consistency review JSON;
13. voice-profile embeddings report JSON;
14. pipeline check JSON.

Качество результата определяется не красотой пересказа, а проверяемостью:

- все исходные и raw данные сохранены;
- transcript можно сверить с исходным MP3 по таймкодам;
- speaker names назначены до semantic review;
- неизвестные/спорные говорящие явно помечены;
- каждый downstream step читает artifacts предыдущих или профильных шагов;
- если шаг не может быть выполнен, причина явно записана в stdout/stderr или artifact/report.
