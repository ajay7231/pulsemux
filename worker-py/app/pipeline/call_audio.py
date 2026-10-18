"""Bounded Twilio-format ingress for the browser call simulator."""
import io
import wave
from collections import deque

import numpy as np


def mulaw_wav(payload: bytes) -> bytes:
    """Decode standard G.711 mu-law into a portable mono 8kHz PCM WAV."""
    value = np.bitwise_not(np.frombuffer(payload, dtype=np.uint8)).astype(np.int32)
    magnitude = (((value & 15) << 3) + 132) << ((value >> 4) & 7)
    samples = np.where(value & 128, 132 - magnitude, magnitude - 132).astype('<i2')
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(samples.tobytes())
    return output.getvalue()


class CallAudio:
    """Keep 300ms of pre-roll and at most 21 seconds of an utterance."""
    def __init__(self):
        self.preroll = deque(maxlen=15)
        self.frames = None

    def start_speech(self):
        self.frames = list(self.preroll)
        self.preroll.clear()

    def feed(self, frame: bytes):
        if len(frame) != 160:
            raise ValueError('Expected a 20ms / 160-byte mu-law frame')
        if self.frames is None:
            self.preroll.append(frame)
        elif len(self.frames) < 1050:
            self.frames.append(frame)

    def end_speech(self):
        frames, self.frames = self.frames, None
        self.preroll.clear()
        return mulaw_wav(b''.join(frames)) if frames else None
