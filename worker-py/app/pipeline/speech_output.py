"""Incremental Deepgram audio output; credentials and audio stay call-scoped."""
import asyncio
import time

import httpx


class SpeechStreamError(Exception):
    """Audio already started; replaying the clause as fallback would duplicate speech."""


class DeepgramSpeechOutput:
    def __init__(self):
        self.client = None

    async def close(self):
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    async def chunks(self, text, key, voice, *, phone=False):
        # A call owns its pool; it is never shared between hospital credentials.
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5),
                                            limits=httpx.Limits(max_connections=1, keepalive_expiry=60))
        rate, encoding = (8000, "mulaw") if phone else (24000, "linear16")
        frame_bytes = 160 if phone else 960  # 20ms mono audio
        async with asyncio.timeout(45):
            async with self.client.stream(
                "POST", "https://api.deepgram.com/v1/speak",
                params={"model": voice, "encoding": encoding,
                        "container": "none", "sample_rate": rate},
                headers={"Authorization": f"Token {key}"}, json={"text": text},
            ) as response:
                response.raise_for_status()
                count = 0
                async for chunk in response.aiter_bytes(chunk_size=frame_bytes):
                    if not chunk:
                        continue
                    if not phone and len(chunk) % 2:
                        raise ValueError("Incomplete PCM sample")
                    count += len(chunk)
                    if count > rate * (1 if phone else 2) * 45:
                        raise ValueError("Speech output exceeded duration limit")
                    yield chunk, encoding, rate
                if not count:
                    raise ValueError("Empty speech response")


class AudioPacer:
    """Bound browser playback lead to 500ms without delaying the first frame."""
    def __init__(self):
        self.deadline = time.monotonic()

    async def wait(self, size, encoding, rate):
        now = time.monotonic()
        self.deadline = max(self.deadline, now) + size / rate / (2 if encoding == "linear16" else 1)
        await asyncio.sleep(max(0, self.deadline - now - 0.5))
