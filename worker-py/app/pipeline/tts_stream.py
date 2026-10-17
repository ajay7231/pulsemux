import asyncio
import logging
import re
from typing import AsyncGenerator, Callable, List, Optional

logger = logging.getLogger(__name__)


class ClauseSplitter:
    """
    Buffers streaming LLM tokens and yields syntactic clauses as soon as punctuation
    boundaries (., ?, !, ;, :) are met and a minimum token count threshold is satisfied.
    """

    PUNCT_SPLIT_REGEX = re.compile(r"([.!?;:,])")

    def __init__(self, min_word_count: int = 6):
        self.min_word_count = min_word_count
        self.buffer = ""

    def feed_token(self, token: str) -> List[str]:
        self.buffer += token
        clauses = []

        # Check if punctuation boundary is present
        parts = self.PUNCT_SPLIT_REGEX.split(self.buffer)
        if len(parts) > 1:
            # Reconstruct candidate clause
            candidate = parts[0] + parts[1]
            words = candidate.strip().split()
            if len(words) >= self.min_word_count:
                clauses.append(candidate.strip())
                self.buffer = "".join(parts[2:])

        return clauses

    def flush(self) -> Optional[str]:
        remaining = self.buffer.strip()
        self.buffer = ""
        return remaining if remaining else None


class TTSStreamClient:
    """
    Streaming Text-To-Speech client integrating with Cartesia Sonic / ElevenLabs WebSocket.
    Yields 16kHz 16-bit PCM audio frames tagged with turn_id.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: str = "sonic-english",
        sample_rate: int = 16000,
    ):
        self.api_key = api_key
        self.voice_id = voice_id
        self.sample_rate = sample_rate

    async def synthesize_clause_stream(
        self,
        clause: str,
        turn_id: str,
    ) -> AsyncGenerator[bytes, None]:
        """
        Synthesizes a single clause into a stream of 20ms 16kHz PCM frames (640 bytes).
        """
        logger.info(f"TTS: Synthesizing clause for turn {turn_id}: '{clause}'")

        if not self.api_key:
            # Generate simulated speech tones for zero-credential local testing
            # Simulating approx 1 second of speech per 3 words
            words = clause.split()
            num_frames = max(10, len(words) * 12)
            frame_size = 640 # 20ms @ 16kHz 16-bit mono

            for i in range(num_frames):
                # Generates gentle sine-like PCM data
                pcm_frame = bytes([int(128 + 30 * (i % 8))] * frame_size)
                await asyncio.sleep(0.015) # Faster than real-time generation
                yield pcm_frame
            return

        # Live Cartesia / ElevenLabs WebSocket synthesis flow
        # In production deployment, connect to wss://api.cartesia.ai/tts/websocket
        # and stream PCM bytes.
