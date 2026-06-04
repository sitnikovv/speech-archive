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

## Шаг 07. Name speakers / ручное назначение имён

Скрипт:

```text
scripts/07_name_speakers.py
```

Что делает:

- читает merge artifact;
- находит локальные `SPEAKER_XX`;
- выбирает короткие неперекрывающиеся фрагменты;
- показывает label/time/text;
- проигрывает фрагмент из audio artifact через `ffplay` или `mpv`;
- просит пользователя ввести имя или команду `unknown`, `next`, `bad`, `skip`.

Постоянные sample-файлы не создаются.

Имена сохраняются только в file-local mapping. Merge artifact не изменяется.

Интерактивный ввод:

- плеер не наследует stdin prompt-а;
- перед вводом включается `IUTF8`, если доступно, чтобы Backspace корректно стирал UTF-8 символы;
- malformed UTF-8 во вводе не валит процесс: битые байты отбрасываются с warning и raw hex.

В non-interactive режиме все speaker labels получают `UNKNOWN`. Это используется только для end-to-end проверки.

Входы:

```text
data/artifacts/06_merge/sound.merge...v1.json
data/artifacts/02_audio/sound.audio.normalized.v1.wav
ответы пользователя
```

Outputs:

```text
data/artifacts/07_speakers/sound.speakers.manual.v1.json
data/artifacts/07_speakers/sound.speakers.manual.v1.manifest.json
```

---

## Шаг 08. Export transcript / человекочитаемый transcript

Скрипт:

```text
scripts/08_export_transcript.py
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
data/artifacts/07_speakers/sound.speakers.manual.v1.json
```

Outputs:

```text
data/artifacts/08_transcript/sound.transcript.with-names.v1.txt
data/artifacts/08_transcript/sound.transcript.with-names.v1.manifest.json
```

---

## Шаг 09. Audit dialogue anomalies / эвристический audit

Скрипт:

```text
scripts/09_audit_dialogue_anomalies.py
```

Что делает:

- читает merge, speakers и transcript;
- не меняет предыдущие artifacts;
- создаёт candidates JSON.

Текущая реализация — heuristic placeholder. Она отмечает:

- сегменты с `MIXED`, `OVERLAP`, `UNCERTAIN`;
- некоторые короткие continuation-like реплики после смены говорящего.

Входы:

```text
data/artifacts/06_merge/sound.merge...v1.json
data/artifacts/07_speakers/sound.speakers.manual.v1.json
data/artifacts/08_transcript/sound.transcript.with-names.v1.txt
```

Outputs:

```text
data/artifacts/09_audit/sound.audit.dialogue.v1.json
data/artifacts/09_audit/sound.audit.dialogue.v1.manifest.json
```

---

## Шаг 10. Check pipeline outputs / проверка обязательных outputs

Скрипт:

```text
scripts/10_check_pipeline_outputs.py
```

Что делает:

- проверяет, что обязательные artifacts шагов 01–09 существуют и валидны;
- проверяет JSON на валидность;
- проверяет, что transcript txt не пустой;
- создаёт check artifact.

Шаг 10 не является смысловым анализом. Это технический integrity-check базового pipeline.

Входы:

```text
latest artifacts шагов 01–09
```

Output:

```text
data/artifacts/10_check/sound.pipeline-check.v1.json
```

---

## Шаг 11. Role consistency review / LLM-проверка согласованности ролей

Скрипт:

```text
scripts/11_role_consistency_review.py
```

Что делает:

- читает merge, speakers и transcript;
- вызывает реальный LLM через Hermes CLI;
- просит LLM найти кандидаты, где текущий говорящий плохо согласуется с соседним контекстом диалога;
- не использует заранее заданные доменные правила, списки фраз, шаблоны или хардкод;
- считает имена/labels непрозрачными идентификаторами: LLM не должен делать выводы из смысла названия label/name;
- не исправляет данные автоматически;
- сохраняет structured JSON review;
- сохраняет raw LLM response рядом с artifact.

Текущий runner:

```text
hermes -z <prompt> --cli
```

Модель и provider берутся из текущей Hermes config, если явно не добавлены параметры выбора модели/provider в будущей версии скрипта.

Входы:

```text
data/artifacts/06_merge/sound.merge...v1.json
data/artifacts/07_speakers/sound.speakers.manual.vN.json
data/artifacts/08_transcript/sound.transcript.with-names.vN.txt
```

Outputs:

```text
data/artifacts/11_role_consistency_review/sound.role-consistency-review.hermes.v1.json
data/artifacts/11_role_consistency_review/sound.role-consistency-review.hermes.v1.raw.txt
data/artifacts/11_role_consistency_review/sound.role-consistency-review.hermes.v1.manifest.json
```

Что внутри review JSON:

```json
{
  "stage": "11_role_consistency_review",
  "llm_runner": "hermes-cli",
  "review": {
    "status": "ok",
    "method": "llm_role_consistency_review",
    "candidates": [
      {
        "time": "HH:MM:SS.mmm",
        "current_speaker": "speaker из transcript",
        "suggested_speaker": "существующий speaker/name или UNKNOWN",
        "confidence": 0.0,
        "reason": "краткое объяснение через соседний контекст",
        "evidence_lines": ["короткие цитаты из соседних строк"]
      }
    ]
  }
}
```

Шаг 11 является derived review layer. Он не входит в обязательный check шага 10 и не меняет speaker mapping. Применение кандидатов должно быть отдельным ручным шагом.

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
                             ▼
                         07_speakers
                             │
                             ▼
                         08_transcript
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
          09_audit              11_role_consistency_review
              │
              ▼
          10_check
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

07_speakers читает:
- 06 merge
- 02 audio artifact для проигрывания фрагментов

08_transcript читает:
- 06 merge
- 07 speakers

09_audit читает:
- 06 merge
- 07 speakers
- 08 transcript

10_check читает:
- latest artifacts обязательных шагов 01–09

11_role_consistency_review читает:
- 06 merge
- 07 speakers
- 08 transcript
- текущую Hermes model/provider config для реального LLM-вызова
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
data/artifacts/07_speakers/sound.speakers.manual.v1.json
```

Новый:

```text
data/artifacts/07_speakers/sound.speakers.manual.v2.json
```

Потом создаётся новый transcript:

```text
data/artifacts/08_transcript/sound.transcript.with-names.v2.txt
```

### Если LLM-review нашёл кандидаты

Старые artifacts не меняются.

Review сохраняется как отдельный derived artifact:

```text
data/artifacts/11_role_consistency_review/sound.role-consistency-review.hermes.vN.json
```

Применение кандидатов — отдельное ручное решение и отдельный будущий шаг.
