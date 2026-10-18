"""Local, call-owned turn completion. No model requests or patient-text logging."""
import asyncio
import re
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class TurnTiming:
    complete_ms: int = 350
    incomplete_ms: int = 1200
    max_turn_ms: int = 20000

    def __post_init__(self):
        if not 250 <= self.complete_ms <= 400:
            raise ValueError("Complete-thought pause must be 250–400ms")
        if not self.complete_ms < self.incomplete_ms <= 1800:
            raise ValueError("Incomplete-thought pause must exceed the short pause and be <=1800ms")
        if self.max_turn_ms < self.incomplete_ms:
            raise ValueError("Maximum turn must exceed the incomplete pause")


def complete_thought(text):
    """Conservative English cues, not a clinical meaning or safety classifier.

    Recognizers often punctuate fragments. Dangling conjunctions, auxiliaries,
    introductions and units therefore take precedence over terminal punctuation.
    Unknown/unpunctuated phrases take the longer pause.
    """
    words = re.findall(r"[\w']+", text.lower())
    if not words:
        return False
    tail = words[-1]
    if tail in {
        'and', 'or', 'but', 'because', 'if', 'when', 'while', 'although', 'so',
        'to', 'of', 'for', 'with', 'without', 'from', 'at', 'in', 'on', 'over',
        'is', 'are', 'was', 'were', 'am', 'been', 'being', 'have', 'has', 'had',
        'the', 'a', 'an', 'my', 'your', 'feeling', 'feel', 'taking', 'take',
        'called', 'named', 'says', 'saying', 'about', 'between', 'than',
    }:
        return False
    # A trailing number may still need a dose unit or the second BP value.
    if tail.isdigit() or re.search(r'\b(?:date of birth|blood pressure|my name)\s*[:=]?\s*$', text.lower()):
        return False
    if words[-1] in {'bye', 'goodbye', 'thanks', 'hello', 'hi', 'yes', 'no'}:
        return True
    return bool(re.search(r'[.!?]["\x27\u201d]*\s*$', text.strip()))


class SemanticTurnCompletion:
    """Pause candidates are reversible until commit; each commit happens once.

    Both transports provide VAD starts and pause candidates. Recognition updates
    may shorten a pending pause, but provider endpoint events alone never commit
    while the caller is speaking. The maximum duration also spans continuations.
    """
    def __init__(self, commit, failure, timing=None, *, clock=time.monotonic, sleep=asyncio.sleep):
        self.commit = commit
        self.failure = failure
        self.timing = timing or TurnTiming()
        self.clock, self.sleep = clock, sleep
        self.turn_id = None
        self.text = ''
        self.confirmed = False
        self.pending = False
        self.began = 0.0
        self.paused_at = None
        self.timer = None
        self.tasks = set()
        self.revision = 0
        self.closed = False

    def start(self, turn_id):
        if self.closed:
            raise RuntimeError('Turn completion is closed')
        continuing = self.turn_id is not None
        if not continuing:
            self.began = self.clock()
            self.text, self.confirmed = '', False
        self.turn_id = turn_id
        self.pending, self.paused_at = False, None
        self._schedule()
        return continuing

    def observe(self, turn_id, text, *, is_final=False, speech_final=False):
        if self.closed or turn_id != self.turn_id or self.turn_id is None:
            return
        self.text = text
        self.confirmed = bool(is_final or speech_final)
        if self.pending:
            self._schedule()

    async def pause(self, turn_id, pause_ms, *, force=False):
        if self.closed or self.turn_id is None or turn_id != self.turn_id:
            return  # Stale/duplicate VAD ends must not submit a second turn.
        self.pending = True
        self.paused_at = self.clock() - pause_ms / 1000
        if force:
            await self._commit(force=True, pause_ms=pause_ms)
        else:
            self._schedule()

    def _schedule(self):
        self._cancel_timer()
        deadline = self.began + self.timing.max_turn_ms / 1000
        if self.pending:
            pause = self.timing.complete_ms if self.confirmed and complete_thought(self.text) else self.timing.incomplete_ms
            deadline = min(deadline, self.paused_at + pause / 1000)
        revision = self.revision
        self.timer = asyncio.create_task(self._wait(deadline, revision))
        self.tasks.add(self.timer)
        self.timer.add_done_callback(self.tasks.discard)

    async def _wait(self, deadline, revision):
        try:
            await self.sleep(max(0, deadline - self.clock()))
            if self.closed or revision != self.revision or self.turn_id is None:
                return
            forced = self.clock() >= self.began + self.timing.max_turn_ms / 1000
            pause_ms = max(0, round((self.clock() - self.paused_at) * 1000)) if self.pending else 0
            await self._commit(force=forced, pause_ms=pause_ms)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.failure()

    async def _commit(self, *, force, pause_ms):
        turn_id = self.turn_id
        self.discard()
        await self.commit(turn_id, pause_ms, force)

    def _cancel_timer(self):
        self.revision += 1
        if self.timer and self.timer is not asyncio.current_task():
            self.timer.cancel()
        self.timer = None

    def discard(self):
        self._cancel_timer()
        self.turn_id, self.pending, self.paused_at = None, False, None
        self.text, self.confirmed = '', False

    async def close(self):
        self.closed = True
        self.discard()
        tasks = [task for task in self.tasks if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
