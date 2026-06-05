# speech-archive

Локальный файловый конвейер для обработки архива русскоязычных MP3-записей.

Проект делает рабочую копию аудио, подготавливает вариант для моделей, выполняет распознавание речи, разделение говорящих, сопоставление голосов с профилями, материализацию speaker mapping, ручное назначение только оставшихся нерешённых имён, экспорт расшифровки и проверку обязательных результатов.

Главный принцип: исходное аудио и результаты моделей считаются доказательными данными. Они не перезаписываются. Повторный запуск создаёт новую версию артефакта (`vN`).

## Документы

Основные документы:

- [ТЗ: назначение и требования](docs/speech-archive-requirements.md)
- [Подробное описание шагов](docs/step_description.md)

Полезные разделы ТЗ:

- [Назначение проекта](docs/speech-archive-requirements.md#1-назначение)
- [Главный принцип](docs/speech-archive-requirements.md#2-главный-принцип)
- [Текущая архитектура](docs/speech-archive-requirements.md#3-текущая-архитектура)
- [Рабочая структура файлов](docs/speech-archive-requirements.md#5-рабочая-структура-файлов)
- [Доступные модели](docs/speech-archive-requirements.md#7-доступные-модели-и-backend-и)
- [Критерий готовности текущей версии](docs/speech-archive-requirements.md#15-критерий-готовности-текущей-версии)
- [Что происходит при изменении](docs/step_description.md#что-происходит-при-изменении)

## Текущие шаги

| Шаг | Скрипт | Что делает |
| --- | --- | --- |
| 00 | `scripts/00_doctor.py` | Проверяет окружение, зависимости и доступность моделей. |
| 01 | `scripts/01_prepare_input.py` | Создаёт рабочую копию входного MP3 и manifest. |
| 02 | `scripts/02_make_audio_variant.py` | Создаёт нормализованный WAV для моделей. |
| 03 | `scripts/03_asr_smoke_compare.py` | Выполняет smoke-сравнение ASR backend. |
| 04 | `scripts/04_transcribe.py` | Выполняет полное распознавание речи. |
| 05 | `scripts/05_diarize.py` | Разделяет запись по говорящим. |
| 06 | `scripts/06_merge_asr_diarization.py` | Совмещает ASR-сегменты и diarization. |
| 07 | `scripts/07_voice_identification.py` | Сопоставляет голоса с подтверждёнными voice profiles через pyannote. |
| 07_1 | `scripts/07_1_voice_identification_ecapa.py` | Необязательная diagnostic-ветка для сравнения сопоставления через SpeechBrain ECAPA. |
| 08 | `scripts/08_name_speakers.py` | Создаёт speaker mapping из stage 07; вручную спрашивает только unresolved speakers и сохраняет подтверждённые voice samples. |
| 09 | `scripts/09_export_transcript.py` | Экспортирует человекочитаемую расшифровку. |
| 10 | `scripts/10_role_consistency_review.py` | Ищет LLM-кандидаты на несогласованность ролей/говорящих без автоправок. |
| 11 | `scripts/11_build_voice_profile_embeddings.py` | Пересобирает или мигрирует embedding cache для voice profiles. |
| 99 | `scripts/99_check_pipeline_outputs.py` | Проверяет обязательные результаты всего конвейера. |

Подробности по каждому шагу см. в [docs/step_description.md](docs/step_description.md).

## Артефакты

Основные результаты пишутся в stage-директории:

```text
data/artifacts/<NN_stage_name>/
```

Примеры:

```text
data/artifacts/04_asr/
data/artifacts/05_diarization/
data/artifacts/06_merge/
data/artifacts/08_speakers/
data/artifacts/09_transcript/
data/artifacts/10_role_consistency_review/
data/artifacts/11_voice_profile_embeddings/
data/artifacts/99_check/
```

Профили голосов и подтверждённые образцы хранятся отдельно:

```text
data/voice_profiles/<person>/
```

Подробнее структура описана в разделах:

- [Рабочая структура файлов](docs/speech-archive-requirements.md#5-рабочая-структура-файлов)
- [Описание шагов](docs/step_description.md)

## Запуск

Проект использует `uv`.

Проверить окружение:

```bash
uv run python scripts/00_doctor.py
```

Запустить тесты:

```bash
uv run python -m unittest discover -s tests -v
```

Обычный запуск выполняется по шагам. Downstream-этапы читают уже созданные artifacts и создают новые версионированные результаты.

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

# 08: speaker mapping. Если stage 07 распознал всех speaker-ов как matched, проходит без вопросов.
# Если остались unresolved speakers, запускать вручную пользователем.
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

### Общий запуск до условного шага 08

Эта команда выполняет все неинтерактивные шаги до `08_name_speakers.py`: `00` → `07`.
`07_1` не входит в основной pipeline и запускается отдельно только для сравнения backend-ов.

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

Дальше создаётся speaker mapping. Если stage 07 уверенно распознал всех `SPEAKER_XX` со статусом `matched`, шаг 08 не задаёт вопросов и только материализует `08_speakers` artifact. Если остались unresolved speakers, это ручной gate:

```bash
uv run python scripts/08_name_speakers.py \
  "data/artifacts/06_merge/${BASE}.merge.Systran_faster-whisper-large-v3.pyannote_speaker-diarization-3.1.v1.json" \
  "data/artifacts/07_voice_identification/${BASE}.voice-id.pyannote-embedding.v1.json" \
  --audio "data/artifacts/02_audio/${BASE}.audio.normalized.v1.wav"
```

Интерактивную часть запускает только пользователь в своём терминале и аудио-окружении. Агент не должен скрыто назначать unresolved speakers за пользователя.

## Ручные этапы

Шаг `08_name_speakers.py` условно интерактивный: он требует прослушивания фрагментов и ввода имён только для speaker-ов, которых stage 07 не распознал уверенно.

Если stage 07 распознал всех speaker-ов как `matched`, шаг 08 можно запускать без ручного ввода: он создаст speakers artifact из voice-id assignments и не сохранит новые samples. Если есть unresolved speakers, интерактивную часть должен проходить пользователь. Для автоматических проверок допустим только явно помеченный CI/debug-режим, например `--ci-non-interactive`, но это не нормальный пользовательский workflow.

## Статус

Текущая версия — файловый конвейер без SQLite.

Фокус текущей реализации:

- воспроизводимые независимые шаги;
- неизменяемые артефакты;
- сохранение исходных и модельных evidence-данных;
- ручные gates только там, где нужно человеческое подтверждение;
- отдельные review/check stages для производных проверок.
