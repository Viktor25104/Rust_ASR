use anyhow::Result;
use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        State,
    },
    routing::get,
    response::IntoResponse,
    Router,
};
use futures::{sink::SinkExt, stream::StreamExt};
use std::sync::Arc;
use tokio::sync::Mutex;
use std::path::{Path, PathBuf};
use tracing::{info, warn, error};

use audio::{Resampler, loader::to_mono};
use asr_core::{TranscribeOptions, ModelType};

// Ассистент-state для WebSocket: добавим чтение языка
struct AppState {
    engine: Arc<Mutex<asr_engine::AsrEngine>>,
    language: String,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();

    // Считываем конфигурацию из ENV
    let model_path = std::env::var("MODEL_PATH").unwrap_or_else(|_| "models/gigaam-v3-e2e-ctc".into());
    let model_type_str = std::env::var("MODEL_TYPE").unwrap_or_else(|_| "gigaam".into());
    let device_str = std::env::var("DEVICE").unwrap_or_else(|_| "cpu".into());
    let host = std::env::var("HOST").unwrap_or_else(|_| "0.0.0.0:8080".into());
    let language = std::env::var("LANGUAGE").unwrap_or_else(|_| String::new()); // По умолчанию язык не задан

    let model_type = match model_type_str.as_str() {
        "whisper" => ModelType::Whisper,
        "gigaam" => ModelType::GigaAm,
        "parakeet" => ModelType::Parakeet,
        "qwen3" => ModelType::Qwen3Asr,
        _ => panic!("Unknown MODEL_TYPE: {}", model_type_str),
    };

    info!("Starting RustASR WebSocket Server");
    info!("Device: {}", device_str);
    info!("Model path: {}", model_path);
    if !language.is_empty() {
        info!("Language forced to: {}", language);
    }

    // Загрузка модели 1 раз при старте
    let device = create_device(&device_str)?;
    let engine = asr_engine::AsrEngine::load(model_type, Path::new(&model_path), &device)?;
    info!("Model loaded successfully: {}", engine.name());

    let state = Arc::new(AppState {
        engine: Arc::new(Mutex::new(engine)),
        language,
    });

    let app = Router::new()
        .route("/transcribe", get(ws_handler))
        .with_state(state);

    let listener = tokio::net::TcpListener::bind(&host).await?;
    info!("Server is listening on ws://{}/transcribe", host);

    axum::serve(listener, app).await?;

    Ok(())
}

async fn ws_handler(ws: WebSocketUpgrade, State(state): State<Arc<AppState>>) -> impl IntoResponse {
    ws.on_upgrade(|socket| handle_socket(socket, state))
}

async fn handle_socket(mut socket: WebSocket, state: Arc<AppState>) {
    info!("Client connected");

    let mut audio_buffer: Vec<u8> = Vec::new();
    let mut last_transcribe_len = 0; // Для отслеживания прогресса стриминга

    while let Some(msg) = socket.next().await {
        if let Ok(msg) = msg {
            match msg {
                Message::Binary(data) => {
                    audio_buffer.extend_from_slice(&data);

                    // Если накопили 2 секунды нового аудио (16000Hz * 4 bytes = 64000 bytes/sec)
                    if audio_buffer.len() - last_transcribe_len >= 128_000 {
                        last_transcribe_len = audio_buffer.len();

                        // Конвертация сырых байт в f32le
                        let mut samples = Vec::with_capacity(audio_buffer.len() / 4);
                        for chunk in audio_buffer.chunks_exact(4) {
                            let val = f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
                            samples.push(val);
                        }

                        // Промежуточная транскрипция (Streaming)
                        let mut engine = state.engine.lock().await;
                        let mut opts = TranscribeOptions::default();
                        if !state.language.is_empty() {
                            opts = opts.with_language(&state.language);
                        }

                        if let Ok(result) = engine.transcribe(&samples, &opts) {
                            if let Ok(json_str) = serde_json::to_string(&result) {
                                // Инжектим is_final: false чтобы клиент понял, что это еще не конец строки
                                let inject_is_final = json_str.replace("{", "{\"is_final\": false, ");
                                let _ = socket.send(Message::Text(inject_is_final.into())).await;
                            }
                        }
                    }
                }
                Message::Text(t) => {
                    // Клиент присылает {"action": "finish"} для триггера финальной транскрибации фразы
                    if t.contains("finish") {
                        if audio_buffer.is_empty() {
                            let _ = socket.send(Message::Text("{\"is_final\": true}".into())).await;
                            continue;
                        }

                        // Декодируем искомый PCM f32
                        let mut samples = Vec::with_capacity(audio_buffer.len() / 4);
                        for chunk in audio_buffer.chunks_exact(4) {
                            let val = f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
                            samples.push(val);
                        }

                        let mut engine = state.engine.lock().await;
                        let mut opts = TranscribeOptions::default();
                        if !state.language.is_empty() {
                            opts = opts.with_language(&state.language);
                        }

                        match engine.transcribe(&samples, &opts) {
                            Ok(result) => {
                                if let Ok(json_str) = serde_json::to_string(&result) {
                                    // Инжектим is_final: true
                                    let inject_is_final = json_str.replace("{", "{\"is_final\": true, ");
                                    let _ = socket.send(Message::Text(inject_is_final.into())).await;
                                }
                            }
                            Err(e) => {
                                error!("Transcription error: {}", e);
                            }
                        }
                        
                        // Clear buffer
                        audio_buffer.clear();
                        last_transcribe_len = 0;
                    }
                }
                Message::Close(_) => {
                    info!("Client disconnected normally");
                    break;
                }
                _ => {}
            }
        } else {
            warn!("Client disconnected abruptly");
            break;
        }
    }
}

// Утилита для создания устройства
fn create_device(device_str: &str) -> Result<candle_core::Device> {
    match device_str {
        "cpu" => Ok(candle_core::Device::Cpu),
        "cuda" => candle_core::Device::new_cuda(0).map_err(Into::into),
        "metal" => candle_core::Device::new_metal(0).map_err(Into::into),
        _ => anyhow::bail!("Unsupported device: {}", device_str),
    }
}
