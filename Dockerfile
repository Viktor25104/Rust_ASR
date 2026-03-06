# --- Stage 1: Builder (CUDA 12 + Rust) ---
FROM nvidia/cuda:12.2.2-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH

# Установка зависимостей и Rust
RUN apt-get update && apt-get install -y \
    curl \
    pkg-config \
    libssl-dev \
    build-essential \
    python3 python3-pip \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain 1.85.0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

# Задаем Compute Capability явно, чтобы убрать зависимость от nvidia-smi при сборке
# 89=L40/Ada, 86=A40/RTX3000, 80=A100. Пусть будет 86 (совместимо с A40 и RTX 4070Ti)
ENV CUDA_COMPUTE_CAP=86

# Собираем релиз с фичей CUDA (уже включена в Cargo.toml)
RUN cargo build --release -p asr-cli

# --- Stage 2: Runner ---
FROM nvidia/cuda:12.2.2-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    ca-certificates \
    python3 \
    python3-pip \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

# Требуется для скрипта загрузки моделей RustASR
RUN pip3 install huggingface_hub torch safetensors sentencepiece numpy

WORKDIR /app

# Копируем бинарник с шага сборки
COPY --from=builder /app/target/release/rustasr /app/rustasr
COPY --from=builder /app/scripts /app/scripts

# Скачиваем и конвертируем русскую модель GigaAM v3 CTC прямо в образ (через HuggingFace)
RUN mkdir -p /app/models \
    && python3 scripts/convert_gigaam.py --hf ai-sage/GigaAM-v3 --hf-revision e2e_ctc --output /app/models/gigaam-v3-e2e-ctc

# Переменные окружения для старта сервера
ENV HOST="0.0.0.0:8080"
ENV RUST_LOG="info"
ENV DEVICE="cuda"
ENV MODEL_TYPE="gigaam"
ENV MODEL_PATH="/app/models/gigaam-v3-e2e-ctc"

EXPOSE 8080

CMD ["/app/rustasr"]
