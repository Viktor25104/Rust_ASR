import asyncio
import argparse
import time
import wave
import sys
import struct
import json
try:
    import websockets
except ImportError:
    print("Ошибка: установите библиотеку websockets -> pip install websockets")
    sys.exit(1)

async def stream_audio(ws_url: str, wav_path: str, chunk_duration_ms: int = 500):
    try:
        wf = wave.open(wav_path, "rb")
    except Exception as e:
        print(f"Не удалось открыть WAV файл: {e}")
        return

    # Проверка формата
    channels = wf.getnchannels()
    sample_rate = wf.getframerate()
    sampwidth = wf.getsampwidth()
    
    if sample_rate != 16000 or channels != 1 or sampwidth != 2:
        print(f"ВНИМАНИЕ: Ожидается 16kHz, Mono, 16-bit PCM. Ваш файл: {sample_rate}Hz, {channels}ch, {sampwidth*8}-bit.")
        print("Сервер RustASR настроен на 16kHz Mono f32le/s16le. Пожалуйста, конвертируйте аудио, иначе распознавание может сломаться.")

    frames_per_chunk = int(sample_rate * (chunk_duration_ms / 1000.0))
    bytes_per_chunk = frames_per_chunk * sampwidth * channels
    
    # Читаем сразу весь файл для конвертации (сервер ждет f32)
    raw_data = wf.readframes(wf.getnframes())
    total_samples = len(raw_data) // 2
    
    # Конвертируем s16le в f32le, как просил RustASR
    print("\n[🛠️] Конвертация s16le -> f32le перед отправкой...")
    samples_s16 = struct.unpack(f"<{total_samples}h", raw_data)
    samples_f32 = [s / 32768.0 for s in samples_s16]
    f32_data = struct.pack(f"<{total_samples}f", *samples_f32)
    
    print(f"[🔌] Подключение к {ws_url}...")
    try:
        async with websockets.connect(ws_url) as websocket:
            print("[✅] Успешно подключено к серверу!")
            
            # Задача для прослушивания ответов от сервера в фоне
            async def receive_responses():
                try:
                    while True:
                        response = await websocket.recv()
                        data = json.loads(response)
                        
                        text = data.get("text", "")
                        rtf = data.get("rtf", 0.0)
                        is_final = data.get("is_final", True)
                        
                        if text:
                            if is_final:
                                sys.stdout.write(f"{text}\n")
                                sys.stdout.flush()
                            else:
                                sys.stdout.write(f"{text} ")
                                sys.stdout.flush()
                        else:
                           pass # Не печатаем точки, чтобы не засорять стрим слов
                           
                except websockets.exceptions.ConnectionClosed:
                    print("\n[🔌] Соединение закрыто сервером.")
                except Exception as e:
                    print(f"\n[❌] Ошибка при чтении ответа: {e}")

            # Запускаем таск на прием ответов
            receive_task = asyncio.create_task(receive_responses())
            
            # Эмулируем стриминг: отправляем кусками с задержками
            print(f"[🎙️] Начинаю трансляцию ({chunk_duration_ms}ms чанки), имитация микрофона...")
            bytes_per_chunk_float = frames_per_chunk * 4 # f32 это 4 байта на семпл
            
            offset = 0
            while offset < len(f32_data):
                chunk = f32_data[offset:offset + bytes_per_chunk_float]
                
                # Отправляем бинарник
                await websocket.send(chunk)
                
                # Задержка, чтобы эмулировать реальное время (Real-time stream)
                await asyncio.sleep(chunk_duration_ms / 1000.0)
                offset += bytes_per_chunk_float
                
                print("🎤", end="", flush=True)

            print("\n[🏁] Файл дочитан до конца, отправка сигнала finish...")
            
            # Команда на завершение обработки
            await websocket.send({"text": "finish"})
            
            # Ждем 20 секунд для получения финального ответа (особенно на длинных файлах)
            await asyncio.sleep(20)
            receive_task.cancel()
            
    except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError) as e:
        print(f"\n[❌] Ошибка соединения: {e}")
    except Exception as e:
         print(f"\n[❌] Ошибка: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test RustASR WebSocket Streaming Client")
    parser.add_argument("--url", default="ws://localhost:8080/transcribe", help="URL сервера (default: ws://localhost:8080/transcribe)")
    parser.add_argument("--audio", required=True, help="Путь к тестовому аудиофайлу (.wav)")
    parser.add_argument("--chunk-ms", type=int, default=500, help="Размер отправляемых кусочков в миллисекундах (default: 500)")
    
    args = parser.parse_args()
    
    print(f"Тестирование Streaming ASR...")
    print(f"URL: {args.url}")
    print(f"Аудио: {args.audio}")
    print(f"Чанк: {args.chunk_ms}мс")
    
    asyncio.run(stream_audio(args.url, args.audio, args.chunk_ms))
