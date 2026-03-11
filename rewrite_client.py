import sys

with open(r'E:\Projects\Work\application\asr\client.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    if line.strip().startswith('self._ws_lock = asyncio.Lock()'):
        continue
    
    if line.strip() == 'async def _send_audio(self) -> None:':
        skip = True
        new_lines.extend([
            '    async def _send_audio(self) -> None:\n',
            '        if not self._audio or not self._websocket:\n',
            '            return\n',
            '\n',
            '        async for chunk in self._audio.chunks():\n',
            '            if self._stopping:\n',
            '                return\n',
            '            audio_np = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0\n',
            '            f32_chunk = audio_np.tobytes()\n',
            '            try:\n',
            '                await self._websocket.send(f32_chunk)\n',
            '            except Exception as exc:\n',
            '                logger.bind(module="ASR", event="ASR audio stream stopped").warning(\n',
            '                    "ASR audio send failed: {}", exc\n',
            '                )\n',
            '                return\n',
            '\n'
        ])
        continue
        
    if line.strip() == 'async def _receive_segments(self) -> None:':
        skip = True
        new_lines.extend([
            '    async def _receive_segments(self) -> None:\n',
            '        if not self._websocket or not self._writer:\n',
            '            return\n',
            '\n',
            '        while not self._stopping:\n',
            '            try:\n',
            '                message = await self._websocket.recv()\n',
            '                data = json.loads(message)\n',
            '                text = self._maybe_fix_mojibake(data.get("text", ""))\n',
            '                is_final = data.get("is_final", False)\n',
            '\n',
            '                current_speaker = "Unknown"\n',
            '                if self._speaker_tracker:\n',
            '                    speaker_name = getattr(self._speaker_tracker, "current_speaker", None)\n',
            '                    if isinstance(speaker_name, str) and speaker_name.strip():\n',
            '                        current_speaker = speaker_name.strip()\n',
            '\n',
            '                start_ms = data.get("start", 0) * 1000\n',
            '                end_ms = data.get("end", 0) * 1000\n',
            '\n',
            '                full_text = text.strip()\n',
            '                if not full_text:\n',
            '                    continue\n',
            '\n',
            '                fingerprint = (\n',
            '                    full_text,\n',
            '                    int(start_ms),\n',
            '                    int(end_ms),\n',
            '                    bool(is_final),\n',
            '                    current_speaker,\n',
            '                )\n',
            '                if fingerprint == self._last_segment_fingerprint:\n',
            '                    continue\n',
            '\n',
            '                payload = {\n',
            '                    "session_id": self._session_id,\n',
            '                    "text": full_text,\n',
            '                    "start_ms": int(start_ms),\n',
            '                    "end_ms": int(end_ms),\n',
            '                    "is_final": is_final,\n',
            '                    "speaker": current_speaker,\n',
            '                }\n',
            '                if is_final or self._persist_partial_segments:\n',
            '                    await self._writer.write_segment(payload)\n',
            '                    self._last_segment_fingerprint = fingerprint\n',
            '\n',
            '                if self._redis:\n',
            '                    redis_payload = {\n',
            '                        "tenantId": self._paths.tenant_id,\n',
            '                        "meetingId": self._paths.meeting_id,\n',
            '                        "text": full_text,\n',
            '                        "speaker": current_speaker,\n',
            '                        "start_ms": int(start_ms),\n',
            '                        "end_ms": int(end_ms),\n',
            '                    }\n',
            '                    await self._redis.publish(redis_payload)\n',
            '\n',
            '            except Exception as exc:\n',
            '                if self._is_connection_closed_error(exc):\n',
            '                    logger.bind(module="ASR", event="ASR websocket closed").warning(\n',
            '                        "ASR websocket closed while receiving: {}", exc\n',
            '                    )\n',
            '                    return\n',
            '\n',
            '                logger.bind(module="ASR", event="ASR receive failed").error(\n',
            '                    "ASR receive failed: {}", exc\n',
            '                )\n',
            '                capture_exception(exc, component="ASR", stage="receive_segments")\n',
            '                await asyncio.sleep(0.2)\n',
            '\n'
        ])
        continue
        
    if line.strip() == 'def _build_session_id(self) -> str:':
        skip = False
        
    if line.strip() == 'async def _send_chunk_with_reconnect(self, chunk: bytes) -> bool:':
        skip = True
        
    if skip and 'def _is_connection_closed_error' in line:
        skip = False
        new_lines.append('    @staticmethod\n')
        
    if line.strip() == 'def _log_audio_send_failure(self, exc: Exception, *, chunk_len: int, attempt: int) -> None:':
        skip = True
        
    if skip and line.strip() == 'async def _cleanup_failed_start(self) -> None:':
        skip = False

    if not skip:
        if line.strip() == '@staticmethod' and ('def _is_connection_closed_error' in ''.join(lines[i:i+2])):
            pass # handled above
        else:
            new_lines.append(line)

with open(r'E:\Projects\Work\application\asr\client.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Rewrite applied!")
