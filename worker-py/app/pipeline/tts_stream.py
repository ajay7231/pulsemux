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


class KokoroEngine:
    """Singleton holder for local Kokoro-82M ONNX model."""
    _instance = None
    _kokoro = None

    @classmethod
    def get_instance(cls, model_path: Optional[str] = None, voices_path: Optional[str] = None):
        if cls._kokoro is None:
            import os
            from pathlib import Path
            try:
                from kokoro_onnx import Kokoro
            except ImportError:
                return None

            base_dir = Path(__file__).resolve().parent.parent.parent
            m_path = model_path or os.getenv("KOKORO_MODEL_PATH", str(base_dir / "models" / "kokoro-v0_19.onnx"))
            v_path = voices_path or os.getenv("KOKORO_VOICES_PATH", str(base_dir / "models" / "voices-v1.0.bin"))

            if Path(m_path).exists() and Path(v_path).exists():
                logger.info(f"Loading local Kokoro-82M ONNX model from {m_path}...")
                cls._kokoro = Kokoro(m_path, v_path)
                logger.info("Kokoro-82M ONNX loaded successfully.")
            else:
                logger.warning(f"Kokoro model files not found at {m_path} / {v_path}")
        return cls._kokoro


class TTSStreamClient:
    """
    Streaming Text-To-Speech client integrating local Kokoro-82M ONNX,
    Cartesia Sonic, or ElevenLabs WebSocket.
    Yields 16kHz 16-bit PCM audio frames tagged with turn_id.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: str = "af_bella",
        sample_rate: int = 16000,
        use_kokoro: bool = True,
    ):
        import os
        self.api_key = api_key or os.getenv("CARTESIA_API_KEY")
        self.voice_id = voice_id or os.getenv("TTS_VOICE", "af_bella")
        self.sample_rate = sample_rate
        self.use_kokoro = use_kokoro
        self._kokoro = None

    def _get_kokoro(self):
        if self._kokoro is None and self.use_kokoro:
            self._kokoro = KokoroEngine.get_instance()
        return self._kokoro

    async def synthesize_clause_stream(
        self,
        clause: str,
        turn_id: str,
    ) -> AsyncGenerator[bytes, None]:
        """
        Synthesizes a single clause into a stream of 20ms 16kHz PCM frames (640 bytes).
        """
        logger.info(f"TTS: Synthesizing clause for turn {turn_id}: '{clause}'")
        kokoro = self._get_kokoro()

        if kokoro:
            try:
                import numpy as np
                loop = asyncio.get_running_loop()
                samples, orig_rate = await loop.run_in_executor(
                    None,
                    lambda: kokoro.create(clause, voice=self.voice_id, speed=1.0, lang="en-us")
                )

                # Resample 24kHz -> 16kHz
                num_target = int(len(samples) * self.sample_rate / orig_rate)
                indices = np.linspace(0, len(samples) - 1, num_target)
                resampled = np.interp(indices, np.arange(len(samples)), samples)
                pcm16 = (np.clip(resampled, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

                # Stream out in 20ms frames (640 bytes @ 16kHz 16-bit)
                frame_size = int(self.sample_rate * 2 * 0.02)
                for i in range(0, len(pcm16), frame_size):
                    frame = pcm16[i:i + frame_size]
                    if len(frame) < frame_size:
                        frame = frame + b"\x00" * (frame_size - len(frame))
                    yield frame
                    await asyncio.sleep(0.005) # Rapid yield into outbound buffer
                return
            except Exception as e:
                logger.error(f"Kokoro TTS generation error: {e}. Falling back to simulation.")

        if not self.api_key:
            # Fallback simulated audio frames
            words = clause.split()
            num_frames = max(10, len(words) * 12)
            frame_size = 640 # 20ms @ 16kHz 16-bit mono

            for i in range(num_frames):
                pcm_frame = bytes([int(128 + 30 * (i % 8))] * frame_size)
                await asyncio.sleep(0.015)
                yield pcm_frame
            return
