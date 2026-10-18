"""Deterministic virtual-time acceptance checks for local turn rules."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pipeline.turn_completion import SemanticTurnCompletion, TurnTiming, complete_thought


class VirtualClock:
    def __init__(self):
        self.now, self.waiters = 0., []

    def __call__(self):
        return self.now

    async def sleep(self, delay):
        if delay <= 0:
            return
        future = asyncio.get_running_loop().create_future()
        self.waiters.append((self.now + delay, future))
        try:
            await future
        finally:
            self.waiters = [(end, item) for end, item in self.waiters if item is not future]

    async def advance(self, milliseconds):
        target = self.now + milliseconds / 1000
        while self.now < target - 1e-8:
            self.now = min(target, self.now + .01)
            for end, future in list(self.waiters):
                if end <= self.now + 1e-8 and not future.done():
                    future.set_result(None)
            for _ in range(4):
                await asyncio.sleep(0)


class RuleTests(unittest.TestCase):
    def test_fragments_take_precedence_over_punctuation(self):
        for text in ('', 'My date of birth is.', 'I have been feeling.', 'I called yesterday, and',
                     'The reading is 155 over.', 'The dose is 90.', 'because', 'I am taking the.'):
            with self.subTest(text=text):
                self.assertFalse(complete_thought(text))
        for text in ('Hello.', 'Please arrange a callback for tomorrow.', 'I feel dizzy.', 'Can I confirm my appointment?'):
            self.assertTrue(complete_thought(text))
        self.assertFalse(complete_thought('I need to confirm my appointment'))

    def test_timing_configuration_is_bounded(self):
        for args in ({'complete_ms': 20}, {'incomplete_ms': 200}, {'incomplete_ms': 2000}, {'max_turn_ms': 500}):
            with self.assertRaises(ValueError):
                TurnTiming(**args)


class CompletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = VirtualClock()
        self.commits, self.failure = [], AsyncMock()
        async def commit(turn_id, pause_ms, forced):
            self.commits.append((turn_id, pause_ms, forced))
        self.policy = SemanticTurnCompletion(commit, self.failure, clock=self.clock, sleep=self.clock.sleep)

    async def asyncTearDown(self):
        await self.policy.close()
        self.failure.assert_not_awaited()

    async def test_complete_thought_commits_after_350ms_once(self):
        self.policy.start('one')
        self.policy.observe('one', 'Confirm my appointment.', is_final=True)
        await self.policy.pause('one', 0)
        await self.clock.advance(340)
        self.assertEqual(self.commits, [])
        await self.clock.advance(10)
        self.assertEqual(self.commits, [('one', 350, False)])
        await self.policy.pause('one', 350)
        await self.clock.advance(1500)
        self.assertEqual(len(self.commits), 1)

    async def test_final_update_shortens_pending_wait(self):
        self.policy.start('one')
        self.policy.observe('one', 'Confirm my appointment.', is_final=False)
        await self.policy.pause('one', 0)
        await self.clock.advance(500)
        self.assertEqual(self.commits, [])
        self.policy.observe('one', 'Confirm my appointment.', is_final=True)
        await self.clock.advance(10)
        self.assertEqual(len(self.commits), 1)

    async def test_unfinished_thought_and_provisional_text_wait_1200ms(self):
        for text, final in [('I have been feeling.', True), ('I feel dizzy.', False), ('', True)]:
            self.policy.start(text or 'empty')
            self.policy.observe(text or 'empty', text, is_final=final)
            await self.policy.pause(text or 'empty', 0)
            count = len(self.commits)
            await self.clock.advance(1190)
            self.assertEqual(len(self.commits), count)
            await self.clock.advance(10)
            self.assertEqual(len(self.commits), count + 1)

    async def test_resume_keeps_turn_and_cancels_pending_commit(self):
        self.assertFalse(self.policy.start('one'))
        self.policy.observe('one', 'I have been feeling.', is_final=True)
        await self.policy.pause('one', 0)
        await self.clock.advance(1000)
        self.assertTrue(self.policy.start('continued'))
        self.policy.observe('continued', 'I have been feeling dizzy since yesterday.', is_final=True)
        await self.clock.advance(500)
        self.assertEqual(self.commits, [])
        await self.policy.pause('continued', 0)
        await self.clock.advance(350)
        self.assertEqual(self.commits, [('continued', 350, False)])

    async def test_new_incomplete_suffix_extends_pending_pause(self):
        self.policy.start('one')
        self.policy.observe('one', 'I called yesterday.', is_final=True)
        await self.policy.pause('one', 0)
        await self.clock.advance(300)
        self.policy.observe('one', 'I called yesterday and', is_final=False)
        await self.clock.advance(890)
        self.assertEqual(self.commits, [])
        await self.clock.advance(10)
        self.assertEqual(len(self.commits), 1)

    async def test_endpoint_without_vad_pause_never_commits(self):
        self.policy.start('one')
        self.policy.observe('one', 'Hello.', speech_final=True)
        await self.clock.advance(1500)
        self.assertEqual(self.commits, [])
        await self.policy.pause('one', 350)
        await self.clock.advance(10)
        self.assertEqual(len(self.commits), 1)

    async def test_mute_force_and_long_turn_bound(self):
        self.policy.start('muted')
        await self.policy.pause('muted', 0, force=True)
        self.assertEqual(self.commits, [('muted', 0, True)])
        self.policy.start('long')
        await self.clock.advance(19000)
        await self.policy.pause('long', 0)
        await self.clock.advance(500)
        self.policy.start('continued-long')
        await self.clock.advance(500)
        self.assertEqual(self.commits[-1], ('continued-long', 0, True))

    async def test_stale_events_close_and_isolation(self):
        other_commit = AsyncMock()
        other = SemanticTurnCompletion(other_commit, self.failure, clock=self.clock, sleep=self.clock.sleep)
        try:
            other.start('other')
            self.policy.start('one')
            self.policy.observe('old', 'Hello.', is_final=True)
            await self.policy.pause('old', 350)
            await self.clock.advance(500)
            self.assertEqual(self.commits, [])
            self.policy.observe('one', 'Hello.', is_final=True)
            await self.policy.pause('one', 0)
            timer = self.policy.timer
            await self.policy.close()
            await self.clock.advance(1500)
            self.assertTrue(timer.done())
            self.assertEqual(self.commits, [])
            other_commit.assert_not_awaited()
        finally:
            await other.close()


if __name__ == '__main__':
    unittest.main()
