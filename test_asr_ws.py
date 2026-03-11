import asyncio
import websockets
import wave
import numpy as np
import json
import ssl
import sys
import urllib.request
import os

def download_sample():
    filename = "sample.wav"
    if not os.path.exists(filename):
        print("Downloading sample.wav...")
        # Mozilla DeepSpeech sample: 16kHz, mono, 16-bit
        url = "https://raw.githubusercontent.com/mozilla/DeepSpeech/master/audio/2830-3980-0043.wav"
        urllib.request.urlretrieve(url, filename)
    return filename

async def read_and_send(uri, filename, scale=1.0):
    print(f"Connecting to {uri} with scale={scale}...")
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    try:
        async with websockets.connect(uri, ssl=ssl_context) as websocket:
            print("Connected!")
            
            with wave.open(filename, 'rb') as wf:
                framerate = wf.getframerate()
                nchannels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                print(f"File specs: {framerate}Hz, {nchannels} channels, {sampwidth} width")
                
                audio_bytes = wf.readframes(wf.getnframes())
                
                # int16 -> float32 [-1, 1]
                audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                
                # Apply scaling for testing (x1 or x32768)
                audio_np = audio_np * scale
                
                chunk_size = 8192
                for i in range(0, len(audio_np), chunk_size):
                    chunk = audio_np[i:i+chunk_size].tobytes()
                    await websocket.send(chunk)
                    # small delay
                    await asyncio.sleep(0.05)
                    
                print("Finished sending audio. Sending finish command...")
                await websocket.send('{"action": "finish"}')
                
                print("Waiting for response...")
                while True:
                    try:
                        resp = await websocket.recv()
                        data = json.loads(resp)
                        print("Received:", data)
                        if data.get("is_final"):
                            print("Got final result!")
                            break
                    except Exception as e:
                        print("Connection or parsing error:", e)
                        break
    except Exception as e:
        print("Failed to connect:", e)

if __name__ == "__main__":
    fn = "sample.wav"
    uri = f"wss://0gx655c35ui1zr-8080.proxy.runpod.net/transcribe"
    
    print("=== TEST 1: Normalized [-1.0, 1.0] (As client.py does) ===")
    asyncio.run(read_and_send(uri, fn, scale=1.0))
    
    print("\n=== TEST 2: Integer scale [-32768.0, 32768.0] (Standard NeMo) ===")
    asyncio.run(read_and_send(uri, fn, scale=32768.0))
