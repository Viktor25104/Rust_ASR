"""Минимальный WebSocket-клиент для RustASR-сервера.

Стримит WAV-файл (16 кГц, mono, 16-bit PCM) на эндпоинт /transcribe
чанками по 0.5 секунды, затем отправляет команду finish и печатает
промежуточные и финальный ответы сервера.

Запуск:
    python examples/ws_client.py recording.wav ws://localhost:8080/transcribe
    python examples/ws_client.py recording.wav wss://<host>/transcribe
"""

import asyncio
import json
import ssl
import sys
import wave

import numpy as np
import websockets


async def stream(uri: str, filename: str) -> None:
    print(f"Connecting to {uri} ...")

    connect_kwargs = {}
    if uri.startswith("wss"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        connect_kwargs["ssl"] = ctx

    async with websockets.connect(uri, **connect_kwargs) as ws:
        print("Connected.")

        with wave.open(filename, "rb") as wf:
            framerate = wf.getframerate()
            print(
                f"File specs: {framerate} Hz, "
                f"{wf.getnchannels()} ch, {wf.getsampwidth()} bytes/sample"
            )
            audio_bytes = wf.readframes(wf.getnframes())

        # int16 PCM -> float32 в диапазоне [-1.0, 1.0]
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        async def receiver() -> None:
            while True:
                try:
                    data = json.loads(await ws.recv())
                except Exception as exc:  # сокет закрыт или некорректный JSON
                    print("Receiver stopped:", exc)
                    break
                print("<-", data)
                if data.get("is_final"):
                    break

        recv_task = asyncio.create_task(receiver())

        # 8000 сэмплов @ 16 кГц = 0.5 секунды (имитация реального времени)
        chunk = 8000
        for i in range(0, len(audio), chunk):
            await ws.send(audio[i:i + chunk].tobytes())
            await asyncio.sleep(0.5)

        print("Audio sent, requesting final transcription ...")
        await ws.send('{"action": "finish"}')
        await recv_task


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python examples/ws_client.py <file.wav> <ws_uri>")
        sys.exit(1)
    asyncio.run(stream(sys.argv[2], sys.argv[1]))
