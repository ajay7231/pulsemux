import asyncio
import json
import logging
from typing import AsyncGenerator, Callable, Optional

logger = logging.getLogger(__name__)


class STTStreamClient:
    """
    Streaming Speech-To-Text client for Deepgram Nova-3 / Faster-Whisper.
    Consumes raw 16kHz PCM chunks and yields transcript deltas.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        sample_rate: int = 16000,
        model: str = "nova-3",
    ):
        import os
        self.api_key = api_key or os.getenv("DEEPGRAM_API_KEY")
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        self.sample_rate = sample_rate
        self.model = model
        self.audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._is_running = False

    async def push_audio(self, pcm_chunk: bytes) -> None:
        """Pushes incoming 20ms PCM audio frame into the stream queue."""
        await self.audio_queue.put(pcm_chunk)

    def transcribe_pcm(self, pcm_bytes: bytes) -> str:
        """
        Synchronously transcribes raw 16kHz 16-bit PCM bytes using Groq Whisper.
        """
        if not self.groq_api_key or not pcm_bytes:
            return ""
        import io
        import wave
        import httpx

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm_bytes)
        wav_buffer.seek(0)

        headers = {"Authorization": f"Bearer {self.groq_api_key}"}
        files = {"file": ("audio.wav", wav_buffer, "audio/wav")}
        data = {"model": "whisper-large-v3-turbo"}

        try:
            r = httpx.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers=headers,
                files=files,
                data=data,
                timeout=10,
            )
            if r.status_code == 200:
                return r.json().get("text", "").strip()
            else:
                logger.error(f"Groq Whisper error: {r.status_code} {r.text}")
                return ""
        except Exception as e:
            logger.error(f"Groq Whisper transcription exception: {e}")
            return ""

    async def start_streaming(
        self,
        on_transcript: Callable[[str, bool], None],
    ) -> None:
        """
        Listens to the audio queue and streams to Deepgram Nova-3 WebSocket,
        Groq Whisper, or fallback mock engine.
        """
        self._is_running = True

        if self.api_key:
            logger.info(f"STT: Streaming to Deepgram Nova-3 WebSocket (sample_rate={self.sample_rate}Hz).")
            try:
                import websockets

                url = (
                    f"wss://api.deepgram.com/v1/listen?"
                    f"encoding=linear16&sample_rate={self.sample_rate}&channels=1&"
                    f"model={self.model}&interim_results=true&smart_format=true"
                )
                headers = {"Authorization": f"Token {self.api_key}"}

                async with websockets.connect(url, extra_headers=headers) as ws:
                    send_task = asyncio.create_task(self._send_audio_loop(ws))
                    recv_task = asyncio.create_task(self._recv_transcript_loop(ws, on_transcript))
                    done, pending = await asyncio.wait(
                        [send_task, recv_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                return
            except Exception as e:
                logger.error(f"Deepgram WebSocket error: {e}. Falling back to Groq / mock engine.")

        if self.groq_api_key:
            logger.info("STT: Using Groq Whisper API (whisper-large-v3-turbo).")
            await self._run_groq_stream(on_transcript)
            return

        logger.info("STT: No DEEPGRAM_API_KEY or GROQ_API_KEY detected. Running mock streaming ASR.")
        await self._run_mock_stream(on_transcript)

    async def _send_audio_loop(self, ws) -> None:
        while self._is_running:
            chunk = await self.audio_queue.get()
            await ws.send(chunk)

    async def _recv_transcript_loop(self, ws, on_transcript: Callable[[str, bool], None]) -> None:
        async for message in ws:
            try:
                data = json.loads(message)
                channel = data.get("channel", {})
                alternatives = channel.get("alternatives", [])
                if alternatives:
                    transcript = alternatives[0].get("transcript", "")
                    is_final = data.get("is_final", False)
                    if transcript:
                        on_transcript(transcript, is_final)
            except Exception as e:
                logger.error(f"Error parsing Deepgram message: {e}")

    async def _run_mock_stream(self, on_transcript: Callable[[str, bool], None]) -> None:
        """Simulates speech recognition deltas for local testing and pipeline verification."""
        frame_count = 0
        while self._is_running:
            try:
                _ = await asyncio.wait_for(self.audio_queue.get(), timeout=0.1)
                frame_count += 1
                if frame_count == 10:
                    on_transcript("I have had a mild chest pain", False)
                elif frame_count == 25:
                    on_transcript("I have had a mild chest pain since yesterday morning.", True)
                    frame_count = 0
            except asyncio.TimeoutError:
                continue

    async def _run_groq_stream(self, on_transcript: Callable[[str, bool], None]) -> None:
        """Accumulates PCM frames and transcribes speech turns via Groq Whisper."""
        buffer = bytearray()
        silence_ticks = 0

        while self._is_running:
            try:
                chunk = await asyncio.wait_for(self.audio_queue.get(), timeout=0.15)
                buffer.extend(chunk)
                silence_ticks = 0
            except asyncio.TimeoutError:
                if len(buffer) > 0:
                    silence_ticks += 1
                    # After ~300ms silence with at least 0.5s audio (16000 bytes)
                    if silence_ticks >= 2 and len(buffer) >= 16000:
                        audio_data = bytes(buffer)
                        buffer.clear()
                        silence_ticks = 0
                        
                        loop = asyncio.get_running_loop()
                        transcript = await loop.run_in_executor(None, self.transcribe_pcm, audio_data)
                        if transcript:
                            on_transcript(transcript, True)

    def stop(self) -> None:
        self._is_running = False
