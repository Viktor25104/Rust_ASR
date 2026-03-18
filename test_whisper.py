import asyncio
import websockets
import wave
import numpy as np
import json
import ssl
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

async def read_and_send(uri, filename, scale=1.0):
    print(f"Connecting to {uri}...")
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    try:
        kwargs = {"ssl": ssl_context} if uri.startswith("wss") else {}
        async with websockets.connect(uri, **kwargs) as websocket:
            print("Connected!")
            
            with wave.open(filename, 'rb') as wf:
                framerate = wf.getframerate()
                nchannels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                print(f"File specs: {framerate}Hz, {nchannels} channels, {sampwidth} width")
                
                audio_bytes = wf.readframes(wf.getnframes())
                
                # NeMo Parakeet требует оригинальную амплитуду [-32768, 32767], так как
                # log_zero_guard=1e-5 при малых амплитудах просто обнулит спектрограмму.
                audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
                
                # Apply scaling for testing
                audio_np = audio_np * scale
                
                # 8000 samples at 16000Hz = exactly 0.5 seconds
                chunk_size = 8000
                total_duration = len(audio_np) / framerate
                print(f"Starting real-time stream for {total_duration:.1f} seconds...")
                
                async def recv_loop():
                    while True:
                        try:
                            resp = await websocket.recv()
                            data = json.loads(resp)
                            if data.get('text', '') != '' or data.get('is_final', False):
                                print("<- Received:", data)
                                with open('result.json', 'w', encoding='utf-8') as f:
                                    json.dump(data, f, ensure_ascii=False)
                        except Exception as e:
                            print("Socket closed or error:", e)
                            break
                            
                asyncio.create_task(recv_loop())

                for i in range(0, len(audio_np), chunk_size):
                    chunk = audio_np[i:i+chunk_size].tobytes()
                    await websocket.send(chunk)
                    # Real-time simulation
                    await asyncio.sleep(0.5)
                    
                print("Finished sending audio. Sending finish command...")
                await websocket.send('{"text": "finish"}')
                
                print("Waiting for final response (5s)...")
                await asyncio.sleep(5)
    except Exception as e:
        print("Failed to connect:", e)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_whisper.py <wav_file> <ws_uri>")
        sys.exit(1)
        
    fn = sys.argv[1]
    uri = sys.argv[2]
    
    asyncio.run(read_and_send(uri, fn, scale=1.0))
