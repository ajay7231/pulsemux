"""One bounded Deepgram connection per call, with explicit transport turn boundaries.

No global credentials, no automatic provider fallback, and no response generation
on interim or provider endpoint events. Audio is raw mono G.711 mu-law at 8kHz.
"""
import asyncio
import json
import logging
import math
import time
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


class RecognitionUnavailable(RuntimeError):
    pass


async def connect_deepgram(url, key):
    try:
        from websockets.asyncio.client import connect
        headers = {"additional_headers": {"Authorization": f"Token {key}"}}
    except ImportError:  # websockets 12, retained for existing installations.
        from websockets.legacy.client import connect
        headers = {"extra_headers": {"Authorization": f"Token {key}"}}
    return await connect(url, **headers, open_timeout=8, close_timeout=2,
                         max_size=1_048_576, max_queue=16, compression=None)


class DeepgramCallStream:
    def __init__(self, key, on_interim, on_failure, *, connector=None,
                 finalize_timeout=3.0, keepalive_seconds=3.0, on_result=None,
                 endpointing_ms=None):
        self.key = key
        self.on_interim = on_interim
        self.on_failure = on_failure
        self.on_result = on_result
        self.endpointing_ms = endpointing_ms
        self.connector = connector or connect_deepgram
        self.finalize_timeout = finalize_timeout
        self.keepalive_seconds = keepalive_seconds
        self.ws = None
        self.closed = False
        self.failed = False
        self.queue = asyncio.Queue(maxsize=250)  # Five seconds; overflow fails visibly.
        self.tasks = set()
        self.collectors = set()
        self.samples = 0
        self.floor = 0.0
        self.current = None
        self.words = {}
        self.provisional = {}
        self.finalized_until = 0.0
        self.changed = asyncio.Event()
        self.flush_lock = asyncio.Lock()
        self.last_send = time.monotonic()

    @property
    def audio_time(self):
        return self.samples / 8000

    async def start(self):
        if self.ws is not None or self.closed:
            raise RecognitionUnavailable("Recognition connection is not restartable")
        if not self.key:
            raise RecognitionUnavailable("Speech recognition connection is missing")
        query = urlencode({"model": "nova-3", "encoding": "mulaw", "sample_rate": 8000,
                           "channels": 1, "interim_results": "true", "smart_format": "true",
                           "endpointing": self.endpointing_ms if self.endpointing_ms is not None else "false"})
        try:
            self.ws = await self.connector("wss://api.deepgram.com/v1/listen?" + query, self.key)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise RecognitionUnavailable("Speech recognition could not connect") from None
        finally:
            self.key = None
        self.tasks = {asyncio.create_task(self._write()), asyncio.create_task(self._read()),
                      asyncio.create_task(self._keepalive())}

    def _check(self):
        if self.closed or self.failed or self.ws is None:
            raise RecognitionUnavailable("Speech recognition is unavailable")

    def feed(self, payload):
        self._check()
        if len(payload) != 160:
            raise ValueError("Expected one 20ms mu-law frame")
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            raise RecognitionUnavailable("Speech recognition audio backlog exceeded") from None
        self.samples += len(payload)

    def begin_turn(self, turn_id, *, continue_turn=False):
        self._check()
        if not isinstance(turn_id, str) or not turn_id or len(turn_id) > 128:
            raise ValueError("Invalid recognition turn ID")
        start = self.current[1] if continue_turn and self.current else max(self.floor, self.audio_time - .3)
        if not continue_turn:
            self.provisional.clear()
        self.current = (turn_id, start)
        self.words = {span: word for span, word in self.words.items() if span[1] >= self.audio_time - 60}

    def request_finalize(self):
        """Flush a pause candidate without committing its reversible turn window."""
        self._check()
        try:
            self.queue.put_nowait(json.dumps({"type": "Finalize"}))
        except asyncio.QueueFull:
            raise RecognitionUnavailable("Speech recognition audio backlog exceeded") from None

    def end_turn(self, turn_id, pause_ms=800):
        self._check()
        if self.current is None or self.current[0] != turn_id:
            raise ValueError("Recognition turn does not match speech start")
        _, start = self.current
        self.current = None
        end = self.audio_time
        self.floor = end
        # Capture time before scheduling, so subsequent frames cannot shift this boundary.
        task = asyncio.create_task(self._collect(start, end, max(start, end - pause_ms / 1000)))
        self.collectors.add(task)
        task.add_done_callback(self._collected)
        return task

    def _collected(self, task):
        self.collectors.discard(task)
        if not task.cancelled():
            task.exception()  # Also retrieve failures when an interrupted caller no longer awaits.

    def discard_turn(self):
        self.floor = self.audio_time
        self.current = None

    async def _collect(self, start, end, speech_end):
        # A cancelled response must not abandon a Finalize already sent to the
        # provider. Serialize flushes until their response or a fatal timeout.
        async with self.flush_lock:
            self._check()
            deadline = time.monotonic() + self.finalize_timeout
            try:
                await asyncio.wait_for(self.queue.put(json.dumps({"type": "Finalize"})), 1)
                while True:
                    self._check()
                    # Finalize may have no ack when the provider already finalized
                    # the entire speech range. Never promote interim text instead.
                    if self.finalized_until >= speech_end and self.finalized_until > start:
                        break
                    self.changed.clear()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    await asyncio.wait_for(self.changed.wait(), remaining)
                return " ".join(word for (a, b), word in sorted(self.words.items())
                                if start <= (a + b) / 2 < end)
            except asyncio.TimeoutError:
                await self._fail("finalization_timeout")
                raise RecognitionUnavailable("Speech recognition did not finalize") from None
    async def _write(self):
        try:
            while not self.closed:
                payload = await self.queue.get()
                try:
                    await asyncio.wait_for(self.ws.send(payload), 2)
                    self.last_send = time.monotonic()
                finally:
                    self.queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail("socket_write", exc)

    async def _keepalive(self):
        try:
            while not self.closed:
                await asyncio.sleep(self.keepalive_seconds)
                if time.monotonic() - self.last_send >= self.keepalive_seconds and self.queue.empty():
                    self.queue.put_nowait(json.dumps({"type": "KeepAlive"}))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail("keepalive", exc)

    async def _read(self):
        try:
            async for payload in self.ws:
                data = json.loads(payload)
                if data.get("type") == "Error":
                    raise RecognitionUnavailable("Provider recognition failure")
                if data.get("type") != "Results":
                    continue
                start = float(data.get("start", 0))
                end = start + float(data.get("duration", 0))
                if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start or end > self.audio_time + .1:
                    raise ValueError("Invalid recognition range")
                alternatives = data.get("channel", {}).get("alternatives", [])
                alternative = alternatives[0] if alternatives else {}
                text = alternative.get("transcript", "").strip()
                words = alternative.get("words", [])
                if text and not words:
                    raise ValueError("Timed recognition words are required")
                parsed = []
                for word in words:
                    a, b = float(word["start"]), float(word["end"])
                    value = str(word.get("punctuated_word") or word["word"])
                    if len(value) > 256 or not math.isfinite(a + b) or a < 0 or b < a or b > self.audio_time + .1:
                        raise ValueError("Invalid recognition word time")
                    parsed.append(((round(a, 4), round(b, 4)), value))
                if data.get("is_final"):
                    for span, value in parsed:
                        self.words[span] = value
                    if len(self.words) > 4096:
                        raise ValueError("Recognition buffer exceeded")
                    self.finalized_until = max(self.finalized_until, end)
                    self.provisional = {span: value for span, value in self.provisional.items() if span[1] > end}
                elif self.current and text:
                    self.provisional = {span: value for span, value in self.provisional.items()
                                        if span[1] <= start or span[0] >= end}
                    self.provisional.update({span: value for span, value in parsed if span[1] > self.finalized_until})
                    if len(self.provisional) > 4096:
                        raise ValueError("Provisional recognition buffer exceeded")
                if self.current:
                    turn_id, boundary = self.current
                    finalized = [(span, value) for span, value in self.words.items()
                                 if (span[0] + span[1]) / 2 >= boundary]
                    # Interim suffixes can overlap finalized segments; prefer the
                    # new timed suffix instead of concatenating duplicate text.
                    suffix = [(span, value) for span, value in self.provisional.items() if sum(span) / 2 >= boundary]
                    suffix.sort()
                    if suffix:
                        finalized = [(span, value) for span, value in finalized if span[1] <= suffix[0][0][0]]
                    combined = " ".join(value for _, value in sorted(finalized + suffix))
                    # Segment-final text is still provisional for the overall
                    # caller turn until semantic/VAD commitment. Preview the full
                    # window separately; only _collect supplies patient history.
                    await self.on_interim(turn_id, combined)
                    if self.on_result:
                        self.on_result(turn_id, combined, is_final=bool(data.get("is_final")) and not suffix,
                                       speech_final=bool(data.get("speech_final")) and not suffix)
                self.changed.set()
            if not self.closed:
                await self._fail("socket_closed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail("socket_read_or_result_validation", exc)

    async def _fail(self, reason="recognition_unavailable", exc=None):
        if self.closed or self.failed:
            return
        self.failed = True
        self.changed.set()
        # Exception messages and provider payloads can contain sensitive data.
        # Log only controlled reasons, exception classes and stream counters.
        logger.warning(
            "recognition_failure reason=%s exception_type=%s audio_seconds=%.2f "
            "finalized_seconds=%.2f backlog_frames=%d",
            reason, type(exc).__name__ if exc else "none", self.audio_time,
            self.finalized_until, self.queue.qsize(),
        )
        await self.on_failure()

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.key = None
        self.changed.set()
        current = asyncio.current_task()
        tasks = self.tasks | self.collectors
        for task in tasks:
            if task is not current:
                task.cancel()
        if self.ws is not None:
            try:
                await asyncio.wait_for(self.ws.close(), 3)
            except Exception:
                pass
        await asyncio.gather(*(task for task in tasks if task is not current), return_exceptions=True)
        self.tasks.clear()
        self.collectors.clear()
        self.words.clear()
        self.provisional.clear()
        self.current = None
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
