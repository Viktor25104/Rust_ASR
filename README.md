# RustASR

**Мульти-модельный WebSocket-микросервис распознавания речи (ASR) на чистом Rust.**

Сервис поднимает WebSocket-эндпоинт, один раз загружает выбранную ASR-модель в
память (CPU/CUDA/Metal) и транскрибирует потоковое аудио в реальном времени.
Все модели работают через [Candle](https://github.com/huggingface/candle) — без
C++/Python-зависимостей в runtime.

---

## Содержание

- [Поддерживаемые модели](#поддерживаемые-модели)
- [Архитектура](#архитектура)
- [WebSocket API](#websocket-api)
- [Запуск через Docker](#запуск-через-docker)
- [Локальная сборка и запуск](#локальная-сборка-и-запуск)
- [Подготовка весов моделей](#подготовка-весов-моделей)
- [Пример клиента](#пример-клиента)
- [Разработка](#разработка)
- [Лицензия](#лицензия)

---

## Поддерживаемые модели

| `MODEL_TYPE` | Модель | Архитектура | Языки | Параметры |
|--------------|--------|-------------|-------|-----------|
| `gigaam`   | [GigaAM v3 E2E CTC](https://huggingface.co/ai-sage/GigaAM-v3) | Conformer + CTC | Русский | ~220M |
| `whisper`  | [Whisper Large v3 Turbo](https://huggingface.co/openai/whisper-large-v3-turbo) | Encoder-Decoder | Мультиязычная | ~809M |
| `parakeet` | [Parakeet TDT v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | FastConformer + TDT | 25 языков | ~627M |
| `qwen3`    | [Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR) | AuT Encoder + Qwen3 LLM | Мультиязычная | 0.6B / 1.7B |

Все модели реализуют единый трейт `AsrModel` (`asr-core`) и доступны через фасад
`AsrEngine` (`asr-engine`). Бэкенды: CPU, CUDA (Linux/Windows), Metal (macOS).

---

## Архитектура

Рабочий бинарь — `asr-server` (исполняемый файл `rustasr`). Он принимает аудио по
WebSocket, прогоняет его через `AsrEngine` и возвращает JSON-результат.

```
crates/
├── asr-core/        # Базовые типы, ошибки, трейт AsrModel, утилиты устройства
├── audio/           # WAV-загрузка, ресемплинг, mel-спектрограмма
├── aut-encoder/     # AuT аудио-энкодер (Qwen3-ASR)
├── qwen3-decoder/   # Qwen3 LLM-декодер (Qwen3-ASR)
├── asr-pipeline/    # End-to-end пайплайн Qwen3-ASR
├── model-qwen3/     # Обёртка Qwen3-ASR  -> AsrModel
├── model-whisper/   # Whisper Large v3 Turbo -> AsrModel
├── model-gigaam/    # GigaAM v3 CTC -> AsrModel
├── model-parakeet/  # Parakeet TDT v3 -> AsrModel
├── asr-engine/      # Единый фасад AsrEngine (диспетчеризация по ModelType)
└── asr-server/      # WebSocket-сервис (бинарь rustasr) — ТОЧКА ВХОДА
```

Модели подключаются к `asr-engine` через feature-gates (по умолчанию включены все
четыре):

```toml
[features]
default = ["whisper", "gigaam", "parakeet", "qwen3"]
```

---

## WebSocket API

### Подключение

- **URL:** `ws://<HOST>:<PORT>/transcribe` (или `wss://` за TLS-прокси)
- Сервер конфигурируется через переменные окружения:

| ENV | По умолчанию | Описание |
|-----|--------------|----------|
| `MODEL_TYPE` | `gigaam` | `gigaam` \| `whisper` \| `parakeet` \| `qwen3` |
| `MODEL_PATH` | `models/gigaam-v3-e2e-ctc` | Путь к директории с весами модели |
| `DEVICE`     | `cpu` | `cpu` \| `cuda` \| `metal` |
| `HOST`       | `0.0.0.0:8080` | Адрес и порт прослушивания |
| `LANGUAGE`   | (пусто) | Принудительный язык (ISO 639-1). Пусто = автоопределение |
| `RUST_LOG`   | — | Уровень логов (`info`, `debug`, …) |

### Клиент → Сервер

1. **Binary** — сырое аудио `PCM 32-bit float (little-endian)`, **16000 Hz**, **mono**.
   Накапливается во внутреннем буфере. Каждые ~2 секунды нового аудио сервер
   выдаёт промежуточную транскрипцию.
2. **Text** — управляющая команда. Если строка содержит `finish` (например
   `{"action": "finish"}`), сервер прогоняет весь буфер, отправляет финальный
   результат и корректно закрывает соединение.

### Сервер → Клиент

JSON-сообщения (`Text`). Промежуточные содержат `"is_final": false`, финальное —
`"is_final": true`.

```json
{
  "is_final": true,
  "text": "привет мир это проверка распознавания",
  "rtf": 0.05,
  "model_name": "GigaAM v3 CTC",
  "segments": [
    { "start": 0.0, "end": 2.5, "text": "привет мир", "confidence": 0.98 }
  ],
  "language": "ru"
}
```

| Поле | Тип | Описание |
|------|-----|----------|
| `is_final`   | bool   | `false` — промежуточный результат, `true` — финальный |
| `text`       | string | Полный распознанный текст |
| `rtf`        | number | Real-Time Factor (время инференса / длительность аудио) |
| `model_name` | string | Имя использованной модели |
| `segments`   | array  | Сегменты с таймкодами (`start`, `end`, `text`, `confidence`) |
| `language`   | string | Детектированный или заданный язык |

---

## Запуск через Docker

Образы собираются под NVIDIA GPU (CUDA 12). В `infra/` есть отдельный Dockerfile
под каждую модель — он собирает бинарь и «запекает» в образ конвертированные веса:

| Файл | Модель |
|------|--------|
| `infra/Dockerfile.gigaam`         | GigaAM v3 CTC (русский) |
| `infra/Dockerfile.whisper`        | Whisper Large v3 Turbo |
| `infra/Dockerfile.parakeet`       | Parakeet TDT 1.1b |
| `infra/Dockerfile.parakeet-multi` | Parakeet TDT 0.6b v3 (мультиязычный) |

```bash
# Сборка (пример: GigaAM)
docker build -f infra/Dockerfile.gigaam -t rust-asr:gigaam .

# Запуск на NVIDIA A40 (требует NVIDIA Container Toolkit)
docker run -d \
  --name rustasr_gigaam \
  --restart unless-stopped \
  --gpus '"device=all"' \
  -p 8080:8080 \
  -e DEVICE="cuda" \
  -e MODEL_TYPE="gigaam" \
  -e MODEL_PATH="/app/models/gigaam-v3-e2e-ctc" \
  -e LANGUAGE="ru" \
  -e RUST_LOG="info" \
  rust-asr:gigaam
```

### Cloudflare Tunnel (опционально, для RunPod и частных хостов)

`infra/runpod-entrypoint.sh` запускает сервер и, если задан `CLOUDFLARED_TOKEN`
(или `TUNNEL_TOKEN`), поднимает рядом в том же контейнере `cloudflared`, который
прокидывает публичный hostname Cloudflare на локальный `http://localhost:8080` —
удобно для публикации сервиса без проброса портов. Без токена контейнер запускает
только `rustasr`.

Настройка в Cloudflare Zero Trust:

1. Откройте Zero Trust → Networks → Tunnels, создайте/откройте tunnel.
2. Добавьте Public Hostname: `Service = http://localhost:8080`, hostname на ваш домен.
3. Скопируйте token туннеля и передайте его контейнеру как `CLOUDFLARED_TOKEN`.

> ⚠️ Токен — это секрет. Не храните его в Dockerfile, git или документации. Если
> токен попал в чат/логи — перевыпустите его.

```bash
docker run -d --gpus all \
  -e CLOUDFLARED_TOKEN="<token>" \
  -e DEVICE="cuda" -e MODEL_TYPE="gigaam" \
  rust-asr:gigaam
```

Итоговая схема:

```text
https://<ваш-домен>  ->  Cloudflare Tunnel  ->  cloudflared (в контейнере)
                     ->  http://localhost:8080  ->  RustASR WebSocket /transcribe
```

---

## Локальная сборка и запуск

> Зависимости Candle в workspace собираются с feature `cuda`, поэтому для локальной
> сборки нужен установленный CUDA toolkit. Без GPU удобнее использовать Docker.

```bash
# Сборка релизного бинаря
cargo build --release -p asr-server

# Запуск
MODEL_TYPE=gigaam \
MODEL_PATH=models/gigaam-v3-e2e-ctc \
DEVICE=cuda \
HOST=0.0.0.0:8080 \
RUST_LOG=info \
./target/release/rustasr
```

---

## Подготовка весов моделей

Веса не хранятся в git (`models/` в `.gitignore`). Docker-сборка скачивает и
конвертирует их автоматически. Вручную (нужен Python с `torch`, `safetensors`,
`huggingface_hub`; для Parakeet ещё `omegaconf`, `sentencepiece`):

```bash
# Whisper — скачивается напрямую с HuggingFace
python scripts/download_model.py --model openai/whisper-large-v3-turbo --output models/whisper

# GigaAM v3 CTC — скачивание + конвертация PyTorch -> safetensors
python scripts/convert_gigaam.py --hf ai-sage/GigaAM-v3 --hf-revision e2e_ctc --output models/gigaam-v3-e2e-ctc

# Parakeet TDT — скачивание + конвертация NeMo -> safetensors
python scripts/convert_parakeet.py --model nvidia/parakeet-tdt-0.6b-v3 --output models/parakeet
```

---

## Пример клиента

`examples/ws_client.py` стримит WAV-файл на сервер и печатает ответы:

```bash
pip install websockets numpy
python examples/ws_client.py recording.wav ws://localhost:8080/transcribe
```

---

## Разработка

```bash
# Форматирование
cargo fmt --all

# Линт
cargo clippy --workspace --all-targets -- -D warnings

# Тесты (интеграционные тесты с моделями пропускаются, если веса не скачаны)
cargo test --workspace
```

**Соглашения** (см. также CLAUDE.md владельца): код, коммиты и комментарии — на
английском; типизированные ошибки через `thiserror` (`asr_core::AsrError`);
логирование через `tracing`; аудио и mel — `f32`.

---

## Лицензия

MIT OR Apache-2.0
