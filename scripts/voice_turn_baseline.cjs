'use strict';
// Replay the actual browser TurnDetector, without a microphone or provider calls.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const input = JSON.parse(fs.readFileSync(path.join(root, 'benchmarks/voice/scenarios.json'), 'utf8'));
const pauseOption = process.argv.indexOf('--pause-ms');
if (pauseOption >= 0) {
  input.end_pause_ms = Number(process.argv[pauseOption + 1]);
  if (!Number.isFinite(input.end_pause_ms) || input.end_pause_ms < 250 || input.end_pause_ms > 1800) throw new Error('Invalid --pause-ms');
}
const source = fs.readFileSync(path.join(root, 'worker-py/web/call.js'), 'utf8');
const detectorSource = source.slice(source.indexOf('class TurnDetector'), source.indexOf('function linearToMuLaw'));
if (!detectorSource.startsWith('class TurnDetector')) throw new Error('TurnDetector not found; update the harness extraction.');
const scope = vm.createContext({});
vm.runInContext(detectorSource + '\nthis.Detector = TurnDetector;', scope);
const rows = input.scenarios.map(scenario => {
  const detector = new scope.Detector();
  detector.pauseFrames = Math.round(input.end_pause_ms / input.frame_ms);
  const events = [];
  let elapsed = 0, segmentStart = 0;
  const segmentStarts = [];
  for (const [duration, rms] of scenario.segments) {
    if (duration % input.frame_ms) throw new Error('Scenario duration must be a whole frame');
    segmentStarts.push(segmentStart);
    for (let n = 0; n < duration / input.frame_ms; n++) {
      elapsed += input.frame_ms;
      const event = detector.feed(rms);
      if (event === 'start' || event === 'end') events.push({event, at_ms: elapsed});
    }
    segmentStart += duration;
  }
  const ends = events.filter(e => e.event === 'end');
  const lastSpeech = scenario.segments.reduce((last, [duration, rms], i) => rms >= 0.08 ? segmentStarts[i] + duration : last, null);
  const finalEnd = lastSpeech === null ? null : ends.find(e => e.at_ms >= lastSpeech);
  const wait = finalEnd ? finalEnd.at_ms - lastSpeech : null;
  const pauseIndex = scenario.incomplete_pause_index;
  const premature = pauseIndex === undefined ? null : ends.some(e => e.at_ms > segmentStarts[pauseIndex] && e.at_ms <= segmentStarts[pauseIndex] + scenario.segments[pauseIndex][0]);
  return {id: scenario.id, detected_turns: ends.length, expected_turns: scenario.expected_turns,
    segmentation_matches_target: ends.length === scenario.expected_turns,
    premature_commit_during_incomplete_pause: premature, final_end_wait_ms: wait,
    target_max_end_wait_ms: scenario.target_max_end_wait_ms ?? null,
    end_wait_meets_target: scenario.target_max_end_wait_ms === undefined ? null : wait !== null && wait <= scenario.target_max_end_wait_ms,
    events};
});
const revision = execFileSync('git', ['rev-parse', 'HEAD'], {cwd: root, encoding: 'utf8'}).trim();
process.stdout.write(JSON.stringify({schema_version: 1, mode: 'offline_rms_replay', revision,
  source_sha256: createHash('sha256').update(source).digest('hex'),
  scenarios_sha256: createHash('sha256').update(fs.readFileSync(path.join(root, 'benchmarks/voice/scenarios.json'))).digest('hex'),
  generated_at: new Date().toISOString(), configuration: {frame_ms: input.frame_ms, end_pause_ms: input.end_pause_ms},
  scenario_count: rows.length, matching_segmentation_count: rows.filter(r => r.segmentation_matches_target).length,
  limitations: ['Virtual frame time; not measured wall-clock or network latency.', 'RMS envelopes do not test ASR accuracy, echo cancellation, real noise, or clinical answer correctness.', 'Only the browser detector is executed; Twilio segmentation requires separate transport verification.'],
  provider_metrics: {stt_ms: null, first_response_text_ms: null, first_playable_audio_ms: null, word_error_rate: null}, scenarios: rows}, null, 2) + '\n');
