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
        sample_rate: int = 16000,
        model: str = "nova-3",
    ):
        self.api_key = api_key
        self.sample_rate = sample_rate
        self.model = model
        self.audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._is_running = False

    async def push_audio(self, pcm_chunk: bytes) -> None:
        """Pushes incoming 20ms PCM audio frame into the stream queue."""
        await self.audio_queue.put(pcm_chunk)

    async def start_streaming(
        self,
        on_transcript: Callable[[str, bool], None],
    ) -> None:
        """
        Listens to the audio queue and streams to Deepgram WebSocket or fallback mock engine.
        """
        self._is_running = True

        if not self.api_key:
            logger.info("STT: No DEEPGRAM_API_KEY detected. Running mock streaming ASR.")
            await self._run_mock_stream(on_transcript)
            return

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
        except Exception as e:
            logger.error(f"Deepgram WebSocket error: {e}. Falling back to mock engine.")
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

    def stop(self) -> None:
        self._is_running = False
