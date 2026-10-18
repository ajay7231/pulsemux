const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
// Exercise the shared controller body with isolated browser globals.
const source = fs.readFileSync(path.join(__dirname, '../web/call.js'), 'utf8');
const script = source.split('// Controller lifecycle:')[0].replace(
  'export function createCallSimulator(root = document, options = {}) {',
  'const root = document, options = {};'
);
const sandbox = {window: {addEventListener() {}}, document: {getElementById() {}}, console};
vm.createContext(sandbox);
vm.runInContext(script + '\nthis.TurnDetector = TurnDetector; this.encode = linearToMuLaw;', sandbox);

test('steady noise and brief clicks do not create turns', () => {
  const detector = new sandbox.TurnDetector();
  for (let i = 0; i < 400; i++) assert.notEqual(detector.feed(0.006), 'start');
  for (let i = 0; i < 3; i++) assert.notEqual(detector.feed(0.2), 'start');
  for (let i = 0; i < 50; i++) assert.notEqual(detector.feed(0.006), 'end');
});
test('speech triggers once and ends after an 800ms pause', () => {
  const detector = new sandbox.TurnDetector();
  for (let i = 0; i < 25; i++) detector.feed(0.002);
  const events = Array.from({length: 10}, () => detector.feed(0.08));
  assert.equal(events.filter(e => e === 'start').length, 1);
  for (let i = 0; i < 39; i++) assert.notEqual(detector.feed(0.002), 'end');
  assert.equal(detector.feed(0.002), 'end');
});
test('long speech is bounded to twenty seconds', () => {
  const detector = new sandbox.TurnDetector();
  for (let i = 0; i < 25; i++) detector.feed(0.002);
  const events = Array.from({length: 1000}, () => detector.feed(0.08));
  assert.equal(events.at(-1), 'end');
});
test('mu-law uses standard polarity and silence', () => {
  assert.equal(sandbox.encode(0), 255);
  assert.equal(sandbox.encode(1), 128);
  assert.equal(sandbox.encode(-1), 0);
});
test('worklet preserves frame counts at 44.1kHz and 48kHz', () => {
  for (const rate of [44100, 48000]) {
    let Processor; const frames = [];
    const scope = {sampleRate: rate, AudioWorkletProcessor: class {constructor() {this.port = {postMessage: f => frames.push(f)};}},
      registerProcessor: (_, value) => {Processor = value;}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/mic-worklet.js'), 'utf8'), scope);
    const processor = new Processor();
    for (let offset = 0; offset < rate; offset += 128) processor.process([[new Float32Array(Math.min(128, rate - offset)).fill(0.1)]]);
    assert.equal(frames.length, 50);
    assert.ok(frames.every(frame => frame.length === 160 && Math.abs(frame[0] - 0.1) < 0.00001));
  }
});

test('interrupt acknowledgement never echoes another cancellation', () => {
  vm.runInContext('calling = true;', sandbox);
  // An echo would touch the absent WebSocket mock and throw.
  sandbox.document.getElementById = () => ({className: '', textContent: ''});
  sandbox.speechSynthesis = {speaking: false};
  assert.doesNotThrow(() => vm.runInContext("handleMessage({type: 'interrupted'})", sandbox));
});
test('late audio from an interrupted turn is discarded', () => {
  vm.runInContext("turnId = 'new-turn';", sandbox);
  // Invalid base64 must never reach the audio decoder for an old turn.
  assert.doesNotThrow(() => vm.runInContext("handleMessage({type: 'audio_clause', turn_id: 'old-turn', audio_b64: 'invalid'})", sandbox));
  assert.equal(vm.runInContext('receivedAudio', sandbox), false);
});

function callFixture() {
  const elements = new Map();
  const sent = [], audioSources = [], utterances = [], stopped = [];
  const scope = {
    window: {addEventListener() {}}, console,
    document: {getElementById(id) {
      if (!elements.has(id)) elements.set(id, {textContent: '', style: {}, classList: {remove() {}}, disabled: false});
      return elements.get(id);
    }},
    setTimeout, clearTimeout, clearInterval,
    WebSocket: {OPEN: 1},
    atob: value => Buffer.from(value, 'base64').toString('binary'),
    SpeechSynthesisUtterance: class {constructor(text) {this.text = text;}},
    speechSynthesis: {speaking: false, cancel() {}, speak(utterance) {utterances.push(utterance);}},
    socket: {readyState: 1, send: value => sent.push(JSON.parse(value)), close() {stopped.push('socket');}},
    audioContext: {
      destination: {}, decodeAudioData: async () => ({}),
      createBufferSource() {
        const source = {connect(filter) {return filter;}, start() {audioSources.push(source);}, stop() {}};
        return source;
      },
      createBiquadFilter() {return {frequency: {}, connect() {}, disconnect() {}};},
      close() {stopped.push('context'); return Promise.resolve();}
    },
    micStream: {getTracks: () => [{stop() {stopped.push('microphone');}}]}
  };
  vm.createContext(scope);
  vm.runInContext(script, scope);
  vm.runInContext("calling = true; turnId = 'farewell'; ws = socket; context = audioContext; stream = micStream;", scope);
  return {scope, sent, audioSources, utterances, stopped, elements};
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test('hangup waits for all queued Kokoro audio and releases microphone and socket', async () => {
  const f = callFixture();
  vm.runInContext("queueAudio('AAAA'); queueAudio('AAAA'); handleMessage({type: 'turn_complete', turn_id: 'farewell', end_call: true});", f.scope);
  await tick();
  assert.equal(f.audioSources.length, 1);
  assert.equal(vm.runInContext('calling', f.scope), true);
  // Noise while closing must not create a new user turn.
  assert.doesNotThrow(() => vm.runInContext('processFrame(new Float32Array(160).fill(0.2))', f.scope));
  f.audioSources[0].onended(); await tick();
  assert.equal(f.audioSources.length, 2);
  assert.equal(vm.runInContext('calling', f.scope), true);
  f.audioSources[1].onended(); await tick();
  assert.equal(vm.runInContext('calling', f.scope), false);
  assert.deepEqual(f.sent.map(m => m.event), ['stop']);
  assert.deepEqual(f.stopped.sort(), ['context', 'microphone', 'socket']);
  assert.equal(f.elements.get('status-title').textContent, 'Call ended');
});
test('hangup waits for browser fallback voice to finish', async () => {
  const f = callFixture();
  vm.runInContext("fallbackSpeech = true; responseText = 'Goodbye.'; handleMessage({type: 'turn_complete', turn_id: 'farewell', end_call: true});", f.scope);
  await tick();
  assert.equal(f.utterances.length, 1);
  assert.equal(vm.runInContext('calling', f.scope), true);
  f.utterances[0].onend(); await tick();
  assert.equal(vm.runInContext('calling', f.scope), false);
});
test('ordinary completion and stale farewell do not disconnect a call', async () => {
  const f = callFixture();
  vm.runInContext("handleMessage({type: 'turn_complete', turn_id: 'farewell'}); handleMessage({type: 'turn_complete', turn_id: 'old-turn', end_call: true});", f.scope);
  await tick();
  assert.equal(vm.runInContext('calling', f.scope), true);
  assert.equal(f.sent.length, 0);
});
test('a failed farewell playback still hangs up', async () => {
  const f = callFixture();
  f.scope.audioContext.decodeAudioData = async () => {throw new Error('decoder failed');};
  vm.runInContext("queueAudio('AAAA'); handleMessage({type: 'turn_complete', turn_id: 'farewell', end_call: true});", f.scope);
  await tick();
  assert.equal(vm.runInContext('calling', f.scope), false);
});

test('playback measurements use one browser clock and export no speech content', async () => {
  const f = callFixture();
  f.scope.performance = {now: () => 1000};
  vm.runInContext("measurement = {turn_id: 'timed', kind: 'speech', outcome: 'pending', speech_end_at: 100, commit_notice_at: 450}; measurements = [measurement]; queueAudio('AAAA');", f.scope);
  await tick();
  const report = JSON.parse(vm.runInContext('JSON.stringify(getMeasurements())', f.scope));
  assert.equal(report.rows[0].speech_end_to_playback_ms, 900);
  assert.equal(report.rows[0].commit_notice_to_playback_ms, 550);
  assert.equal(report.rows[0].speech_end_to_first_text_ms, null);
  assert.equal(report.rows[0].playback_provider, 'selected_tts');
  assert.equal('transcript' in report.rows[0], false);
  assert.equal('audio' in report.rows[0], false);
});

test('mute flushes the current utterance with zero trailing silence and blocks media', () => {
  const f = callFixture();
  const track = {enabled: true};
  f.scope.micStream.getAudioTracks = () => [track];
  f.scope.document.getElementById = id => {
    if (!f.elements.has(id)) f.elements.set(id, {textContent: '', style: {}, setAttribute() {}});
    const element = f.elements.get(id);
    element.setAttribute = () => {};
    return element;
  };
  vm.runInContext('detector.speaking = true; toggleMute(); processFrame(new Float32Array(160).fill(0.2));', f.scope);
  assert.equal(track.enabled, false);
  assert.equal(f.sent.length, 1);
  assert.equal(f.sent[0].type, 'speech_end');
  assert.equal(f.sent[0].pause_ms, 0);
  assert.equal(f.sent[0].force, true);
  vm.runInContext('toggleMute();', f.scope);
  assert.equal(track.enabled, true);
});

test('semantic settings use a short pause candidate and wait for server commitment', () => {
  const f = callFixture();
  vm.runInContext("handleMessage({type: 'call_started', settings: {end_pause_ms: 800}, turn_detection: {semantic: true, candidate_pause_ms: 350}});", f.scope);
  assert.equal(vm.runInContext('detector.pauseFrames', f.scope), 18);
  assert.equal(vm.runInContext('semanticTurns', f.scope), true);
  vm.runInContext("handleMessage({type: 'turn_committed', turn_id: 'farewell', forced: false});", f.scope);
  assert.equal(vm.runInContext('recognizing', f.scope), true);
  assert.equal(vm.runInContext('generating', f.scope), false);
  vm.runInContext("handleMessage({type: 'call_started', settings: {end_pause_ms: 1000}, turn_detection: {semantic: false, candidate_pause_ms: 1000}});", f.scope);
  assert.equal(vm.runInContext('detector.pauseFrames', f.scope), 50);
});

test('mute also flushes a paused semantic turn without sending microphone media', () => {
  const f = callFixture();
  f.scope.micStream.getAudioTracks = () => [{enabled: true}];
  f.scope.document.getElementById = id => {
    if (!f.elements.has(id)) f.elements.set(id, {textContent: '', style: {}});
    const element = f.elements.get(id);
    element.setAttribute = () => {};
    return element;
  };
  vm.runInContext('semanticTurns = true; pendingSpeech = true; detector.speaking = false; toggleMute();', f.scope);
  assert.equal(f.sent.length, 1);
  assert.equal(f.sent[0].force, true);
  assert.equal(f.sent[0].pause_ms, 0);
});
